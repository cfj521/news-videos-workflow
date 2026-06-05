import asyncio
import time
from pathlib import Path

from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult

log = get_logger("publisher.bilibili")

# biliup 1.2.0 自带的 UA 是 2017 年的 Chrome/63，会被 B 站风控判为异常返回 412，
# 导致 nav/投稿接口拿到 HTML 而非 JSON。这里覆盖为现代 UA 绕过。
_MODERN_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


class BilibiliPublisher(PublisherAdapter):
    """B 站投稿（基于 biliup 逆向 Web API）。

    Cookie 名按 B 站真实名称传给 biliup —— biliup 用 ``cookiejar_from_dict`` 原样转发给
    B 站，**大小写敏感**，所以 ``SESSDATA`` / ``DedeUserID`` 必须保留大写，传小写会认证失败。

    发布（写操作）推荐的 Cookie，重要性与下载场景不同：

    ==============  ========  ==========================================================
    Cookie          重要性    作用
    ==============  ========  ==========================================================
    SESSDATA        必填      登录态凭证，没有它一切免谈
    bili_jct        必填      CSRF token；投稿全程是 POST 写操作，每个接口都校验 csrf=bili_jct
    DedeUserID      强烈建议  上传者 UID，部分接口/风控会校验它与 SESSDATA 是否一致
    buvid3          建议      设备指纹，过风控、降低被判异常登录的概率
    buvid4          建议      新版设备指纹，配合 buvid3 让请求更像真实浏览器
    ac_time_value   可选      登录态自动续期，长时间批量投稿减少掉登录
    ==============  ========  ==========================================================
    """

    # 投稿写操作的硬性门槛：缺任一项直接拒绝（区别于下载场景的三件套）
    REQUIRED = ("SESSDATA", "bili_jct")

    def __init__(self, sessdata: str = "", bili_jct: str = "", dede_user_id: str = "",
                 buvid3: str = "", buvid4: str = "", ac_time_value: str = "", tid: int = 17):
        # 用 B 站真实 cookie 名（大小写敏感），并丢弃空值，避免发送空 cookie 干扰鉴权
        raw = {
            "SESSDATA": sessdata, "bili_jct": bili_jct, "DedeUserID": dede_user_id,
            "buvid3": buvid3, "buvid4": buvid4, "ac_time_value": ac_time_value,
        }
        self._cookie = {k: v for k, v in raw.items() if v}
        self._tid = tid

    def _missing_required(self) -> list[str]:
        return [k for k in self.REQUIRED if not self._cookie.get(k)]

    def _biliup_cookie(self) -> dict:
        """转成 biliup login_by_cookies 期望的嵌套结构 {'cookie_info': {'cookies': [{name,value}]}}。"""
        return {"cookie_info": {"cookies": [{"name": k, "value": v} for k, v in self._cookie.items()]}}

    async def publish(self, video_path: str, thumbnail_path: str | None, title: str, description: str, tags: list[str], subtitle_path: str | None = None) -> PublishResult:
        missing = self._missing_required()
        if missing:
            return PublishResult(platform="bilibili", status="failed",
                                 error_message=f"缺少必填 Cookie: {', '.join(missing)}（投稿至少需 SESSDATA + bili_jct）")
        if not self._cookie.get("DedeUserID"):
            log.warning("Bilibili 未提供 DedeUserID，部分投稿接口/风控可能校验失败，强烈建议补上")

        log.info("Publishing to Bilibili: '%s'", title[:60])
        t0 = time.time()

        try:
            # biliup 是同步且内部自带 asyncio.run()，必须丢到独立线程跑——
            # 否则在 pipeline 的事件循环里会抛 "asyncio.run() cannot be called from a running event loop"。
            url = await asyncio.to_thread(
                self._blocking_publish, video_path, thumbnail_path, title, description, tags)
            log.info("Published to Bilibili in %.1fs: %s", time.time() - t0, url or "(无 bvid 返回)")
            return PublishResult(platform="bilibili", status="success", url=url)
        except ImportError:
            return PublishResult(platform="bilibili", status="failed", error_message="biliup 未安装: pip install biliup")
        except Exception as e:
            msg = str(e)
            # -101 未登录 / 账号未登录 → Cookie 失效（约 30 天过期），给出可操作提示
            if "-101" in msg or "未登录" in msg or "account not login" in msg.lower():
                msg = "Cookie 已失效或过期（约 30 天有效），请重新从浏览器获取 SESSDATA / bili_jct 等并更新"
            log.exception("Bilibili publish failed")
            return PublishResult(platform="bilibili", status="failed", error_message=msg)

    def _blocking_publish(self, video_path: str, thumbnail_path: str | None,
                          title: str, description: str, tags: list[str]) -> str:
        """同步 biliup 投稿逻辑——只能在独立线程中调用（见 publish 中的说明）。返回稿件 URL。"""
        from biliup.plugins.bili_webup import BiliBili, Data

        video = Data()
        video.title = title[:80]
        video.desc = description[:250]
        # B 站 tag 要逗号分隔字符串（biliup Data.tag 为 Union[list,str]，set_tag 即 join）
        video.tag = ",".join(tags[:12] if tags else ["科技"])
        video.tid = self._tid

        with BiliBili(video) as bili:
            # 覆盖 biliup 过旧 UA，避免 412 风控（私有属性，跨版本容错）
            try:
                bili._BiliBili__session.headers["user-agent"] = _MODERN_UA
            except Exception:
                pass
            bili.login_by_cookies(self._biliup_cookie())
            # 封面非必需，失败则回退默认封面，不阻断投稿
            if thumbnail_path and Path(thumbnail_path).exists():
                try:
                    video.cover = bili.cover_up(thumbnail_path)
                except Exception as e:
                    log.warning("Bilibili 封面上传失败，改用默认封面: %s", e)
            video_part = bili.upload_file(video_path)
            video.append(video_part)
            result = bili.submit()

        bvid = self._extract_bvid(result)
        return f"https://www.bilibili.com/video/{bvid}" if bvid else ""

    @staticmethod
    def _extract_bvid(result) -> str:
        """biliup.submit() 在不同版本返回 bvid 字符串或 {'data': {'bvid': ...}}，兼容两种。"""
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            data = result.get("data") if isinstance(result.get("data"), dict) else result
            return data.get("bvid", "") if isinstance(data, dict) else ""
        return ""
