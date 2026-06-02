# 视频自动发布 — 接口文档 (开发参考)

> 实现各平台 `PublisherAdapter` 时的技术参考。每个 Adapter 统一实现：
> ```python
> class XxxPublisher(PublisherAdapter):
>     async def publish(self, video_path, thumbnail_path, title, description, tags) -> PublishResult
> ```

---

## 统一视频输出规格

所有平台兼容的最大公约数：

```
容器: MP4 (MPEG-4 Part 14)
视频: H.264, High Profile, 逐行扫描, 4:2:0, closed GOP
音频: AAC-LC, 48kHz, 立体声
分辨率: 1080x1920 (9:16)
帧率: 30fps
码率: 视频 6-8 Mbps, 音频 192-320 kbps
moov atom: 文件头部 (Instagram 强制要求, ffmpeg 加 -movflags +faststart)
```

---

## 1. YouTube — `YouTubePublisher`

### API

YouTube Data API v3。项目已有基础实现: `backend/app/providers/publisher/youtube.py`

### 认证

OAuth 2.0 + refresh_token 自动续期。

```python
from google.oauth2.credentials import Credentials

creds = Credentials(
    token=None,
    refresh_token=cfg.youtube.refresh_token,
    client_id=cfg.youtube.client_id,
    client_secret=cfg.youtube.client_secret,
    token_uri="https://oauth2.googleapis.com/token",
)
```

**关键**: 应用必须处于 "In production" 状态, 否则 refresh_token 7 天过期。

### 上传流程

```python
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

service = build("youtube", "v3", credentials=creds)

media = MediaFileUpload(
    video_path,
    mimetype="video/mp4",
    resumable=True,
    chunksize=50 * 1024 * 1024,  # 50MB 分块
)
request = service.videos().insert(
    part="snippet,status",
    body={
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "28",       # Science & Technology
            "defaultLanguage": "zh",
        },
        "status": {
            "privacyStatus": "public",  # public / unlisted / private
            "selfDeclaredMadeForKids": False,
        },
    },
    media_body=media,
)

# 可续传上传 — 处理网络中断
response = None
while response is None:
    status, response = request.next_chunk()
    if status:
        log.info("Upload progress: %.1f%%", status.progress() * 100)

video_id = response["id"]
video_url = f"https://www.youtube.com/watch?v={video_id}"
```

### 缩略图上传

```python
service.thumbnails().set(
    videoId=video_id,
    media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
).execute()
```

### 配额

| 操作 | 消耗 units |
|------|-----------|
| videos.insert (上传) | 1,600 |
| thumbnails.set | 50 |
| videos.list | 1 |

默认 10,000 units/天 → 每天约 6 次上传。

### 依赖

```
google-api-python-client
google-auth-oauthlib
google-auth-httplib2
```

### 参考文档

- 上传指南: https://developers.google.com/youtube/v3/guides/uploading_a_video
- 可续传上传: https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol
- 配额: https://developers.google.com/youtube/v3/determine_quota_cost

---

## 2. Instagram Reels — `InstagramPublisher`

### API

Instagram Graph API (Meta)。三步异步流程。

### 认证

OAuth 2.0 (Meta/Facebook)。需要长期 access_token。

权限 scope:
- `instagram_business_basic`
- `instagram_business_content_publish`

仅支持 **Business 账号** (Creator 不行)，必须关联 Facebook Page。

### 上传流程

```python
import httpx, asyncio

API = "https://graph.instagram.com/v21.0"

async def publish_reel(user_id: str, access_token: str,
                       video_url: str, caption: str) -> str:
    async with httpx.AsyncClient() as client:
        # Step 1: 创建容器
        resp = await client.post(f"{API}/{user_id}/media", data={
            "media_type": "REELS",
            "video_url": video_url,   # 必须是公开可访问的 URL
            "caption": caption,
            "access_token": access_token,
        })
        container_id = resp.json()["id"]

        # Step 2: 轮询状态 (FINISHED / ERROR)
        for _ in range(60):  # 最多等 5 分钟
            status = (await client.get(f"{API}/{container_id}", params={
                "fields": "status_code,status", "access_token": access_token,
            })).json()
            if status["status_code"] == "FINISHED":
                break
            if status["status_code"] == "ERROR":
                raise RuntimeError(f"Container error: {status}")
            await asyncio.sleep(5)

        # Step 3: 发布
        pub = await client.post(f"{API}/{user_id}/media_publish", data={
            "creation_id": container_id,
            "access_token": access_token,
        })
        return pub.json()["id"]
```

### 关键问题: 公开文件 URL

Instagram 不支持直接上传文件，视频必须通过公开 URL 提供。方案：
1. **临时暴露本地文件**: 通过项目 API 的 `/runs/{id}/video` 端点（需要公网可达）
2. **上传到 S3/CDN**: 先 put 到 S3，拿到 URL 后传给 Instagram
3. **ngrok 隧道**: 开发/测试时用 `ngrok http 8000` 暴露本地服务

### 限制

- 每账号 24 小时最多 100 次发布
- 视频时长: 5-90 秒
- moov atom 必须在文件头部
- 不支持定时发布 API

### 依赖

```
httpx  # 异步 HTTP (项目已有)
```

### 参考文档

- Content Publishing: https://developers.facebook.com/docs/instagram-platform/content-publishing/
- Media endpoint: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media/

---

## 3. Bilibili — `BilibiliPublisher`

### API

无官方 API。使用 `biliup` 库 (逆向 Web API)。

### 认证

Cookie 认证。**Cookie 名大小写敏感**（biliup 用 `cookiejar_from_dict` 原样转发给 B 站），`SESSDATA`/`DedeUserID` 必须大写。

发布（写操作）推荐的 Cookie 集：

| Cookie | 重要性 | 作用 |
|---|---|---|
| `SESSDATA` | 必填 | 登录态 |
| `bili_jct` | 必填 | CSRF token，所有投稿 POST 接口校验 `csrf=bili_jct` |
| `DedeUserID` | 强烈建议 | 上传者 UID，风控校验与 SESSDATA 一致性 |
| `buvid3` / `buvid4` | 建议 | 设备指纹，过风控 |
| `ac_time_value` | 可选 | 登录态续期 |

```python
# 真实 cookie 名（大小写敏感），只传非空项
cookie = {
    "SESSDATA": cfg.bilibili.sessdata,
    "bili_jct": cfg.bilibili.bili_jct,
    "DedeUserID": cfg.bilibili.dede_user_id,
    "buvid3": cfg.bilibili.buvid3,
    "buvid4": cfg.bilibili.buvid4,
    "ac_time_value": cfg.bilibili.ac_time_value,
}
```

Cookie 约 30 天过期, 需定期刷新。接口返回 `-101`（未登录）即 Cookie 失效，`BilibiliPublisher` 会捕获并返回可操作的失效提示。

### 上传流程

```python
from biliup.plugins.bili_webup import BiliBili, Data

async def publish_bilibili(video_path: str, title: str,
                           description: str, tags: list[str],
                           cookie: dict, tid: int = 17) -> str:
    video = Data()
    video.title = title
    video.desc = description
    video.tag = tags
    video.tid = tid  # 分区 ID, 17=科技>数码

    with BiliBili(video) as bili:
        bili.login_by_cookie(cookie)
        video_part = bili.upload_file(video_path)
        video.append(video_part)
        result = bili.submit()
    return result  # 返回 bvid
```

### 常用分区 ID

| tid | 分区 |
|-----|------|
| 17 | 科技 > 数码 |
| 122 | 科技 > 野生技术协会 |
| 95 | 科技 > 数码评测 |
| 124 | 科技 > 趣味科普 |
| 207 | 科技 > 机械 |

### 风控注意

- 上传频率: 建议间隔 ≥5 分钟, 每天 ≤10 个
- 标题/描述不要包含敏感词
- Cookie 失效特征: 接口返回 `-101` (未登录)

### 依赖

```
biliup
```

### 法律风险

2026 年 1 月 bilibili-API-collect 仓库收到 B 站律师函。使用非官方 API 有法律和封号风险。

---

## 4. 抖音 — `DouyinPublisher`

### 方案 A: 官方 API (需企业资质)

#### 认证

OAuth 2.0 授权码模式。

```
authorize_url: https://open.douyin.com/platform/oauth/connect/
token_url:     https://open.douyin.com/oauth/access_token/
```

Scope: `video.create`

#### 上传流程

```python
import httpx

API = "https://open.douyin.com/api/douyin/v1/video"

async def publish_douyin(access_token: str, video_path: str,
                         text: str) -> str:
    async with httpx.AsyncClient() as client:
        # Step 1: 上传视频 (<50MB 直传, >50MB 分片, >300MB 必须分片)
        with open(video_path, "rb") as f:
            resp = await client.post(
                f"{API}/upload_video/",
                headers={"Authorization": f"Bearer {access_token}"},
                files={"video": f},
            )
        video_id = resp.json()["data"]["video"]["video_id"]

        # Step 2: 发布
        pub = await client.post(
            f"{API}/create_video/",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"video_id": video_id, "text": text},
        )
        return pub.json()["data"]["item_id"]
```

#### 分片上传 (>50MB)

```python
# 1. 初始化分片上传
init_resp = await client.post(
    f"{API}/init_video_part_upload/",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"upload_id": upload_id},
)

# 2. 逐片上传
await client.post(
    f"{API}/upload_video_part/",
    headers={"Authorization": f"Bearer {access_token}"},
    data={"upload_id": upload_id, "part_number": i},
    files={"video": chunk},
)

# 3. 完成分片上传
await client.post(
    f"{API}/complete_video_part_upload/",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"upload_id": upload_id},
)
```

#### 参考文档

- 开放平台: https://open.douyin.com
- 上传 API: https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/create-video/upload-video
- 创建视频: https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/create-video/video-create

### 方案 B: Playwright 自动化 (无需企业资质)

```python
from social_auto_upload.douyin import DouYinUploader

uploader = DouYinUploader(cookie_path="douyin_cookies.json")
uploader.upload(
    file_path=video_path,
    title=title,
    tags=tags,
)
```

首次运行需扫码登录, 之后 Cookie 自动保存。速度较慢 (~1-2 分钟/视频)。

### 依赖

```
httpx            # 方案 A
social-auto-upload  # 方案 B (包含 playwright)
```

---

## 5. 快手 — `KuaishouPublisher`

### 方案 A: 官方 API (需企业资质)

#### 认证

OAuth 2.0 授权码模式。

```
authorize_url: https://open.kuaishou.com/oauth2/authorize
token_url:     https://open.kuaishou.com/oauth2/access_token
```

#### 上传流程

```python
import httpx

API = "https://open.kuaishou.com/rest/ks/open/photo"

async def publish_kuaishou(access_token: str, video_path: str,
                           caption: str) -> str:
    async with httpx.AsyncClient() as client:
        # Step 1: 发起上传
        start = await client.post(
            f"{API}/start_upload",
            headers={"Authorization": f"Bearer {access_token}"},
            json={},
        )
        data = start.json()["data"]
        upload_token = data["upload_token"]
        endpoint = data["endpoint"]

        # Step 2: 上传文件
        # 直传 (<10MB): body = 文件内容
        # 分片 (>10MB): 每片 ≤10MB, 带 fragment_id
        with open(video_path, "rb") as f:
            await client.put(
                endpoint,
                headers={"Upload-Token": upload_token},
                content=f.read(),
            )

        # Step 3: 发布 (异步, 返回不代表已发布成功)
        pub = await client.post(
            f"{API}/publish",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "upload_token": upload_token,
                "caption": caption,
            },
        )
        return pub.json()["data"].get("photo_id", "")
```

#### 确认发布状态

发布是异步的, 需轮询:
```python
status = await client.post(
    f"{API}/query_publish_status",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"upload_token": upload_token},
)
# status_code: 1=发布中, 2=成功, 3=失败
```

#### 参考文档

- 开放平台: https://open.kuaishou.com
- 创建视频: https://open.kuaishou.com/platformDocs/openAbility/contentManagement/createAVideo.html
- API 参考: https://kuaishou.apifox.cn/

### 方案 B: Playwright 自动化

同抖音, 使用 `social-auto-upload`。

### 依赖

```
httpx               # 方案 A
social-auto-upload   # 方案 B
```

---

## 通用备选: social-auto-upload

GitHub: https://github.com/dreammis/social-auto-upload

基于 Playwright 的浏览器自动化, 支持抖音/B站/快手/小红书。

```bash
pip install social-auto-upload
playwright install chromium
```

适合:
- 无企业资质, 无法申请官方 API
- 快速原型验证
- 作为官方 API 的兜底方案

缺点:
- 速度慢 (1-2 分钟/视频)
- 依赖浏览器环境
- 平台 UI 变动可能导致失效
- 不如 API 稳定

---

## config.yaml 配置结构设计

```yaml
youtube:
  client_id: ""
  client_secret: ""
  refresh_token: ""      # 首次授权后自动保存

instagram:
  user_id: ""
  access_token: ""       # 长期令牌
  file_host: "s3"        # s3 / local / ngrok

bilibili:
  sessdata: ""           # 必填
  bili_jct: ""           # 必填（CSRF）
  dede_user_id: ""       # 强烈建议（上传者 UID）
  buvid3: ""             # 建议（设备指纹）
  buvid4: ""             # 建议（新版设备指纹）
  ac_time_value: ""      # 可选（登录态续期）

douyin:
  method: "api"          # api / playwright
  client_key: ""         # method=api 时使用
  client_secret: ""
  access_token: ""
  cookie_path: ""        # method=playwright 时使用

kuaishou:
  method: "api"          # api / playwright
  app_id: ""
  app_secret: ""
  access_token: ""
  cookie_path: ""
```

---

## PublisherAdapter 接口

```python
# backend/app/providers/base.py (已有)

class PublisherAdapter(ABC):
    @abstractmethod
    async def publish(
        self,
        video_path: str,
        thumbnail_path: str | None,
        title: str,
        description: str,
        tags: list[str],
    ) -> PublishResult:
        ...

@dataclass
class PublishResult:
    platform: str          # "youtube" / "instagram" / "bilibili" / "douyin" / "kuaishou"
    status: str            # "ok" / "failed" / "pending"
    url: str | None        # 发布后的视频 URL
    error_message: str | None
```

每个平台一个文件:
```
backend/app/providers/publisher/
├── youtube.py          # 已有
├── instagram.py        # 待实现
├── bilibili.py         # 待实现
├── douyin.py           # 待实现
└── kuaishou.py         # 待实现
```
