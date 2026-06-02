import json

from app.logging import get_logger

log = get_logger("publisher.factory")


def build_publishers(targets) -> dict:
    """从 PublishTarget 记录构造平台 adapter，返回 {platform: adapter}。

    禁用、配置缺失或暂不支持的平台跳过（Stage6 会对缺失平台报 "No publisher"）。
    targets: list[PublishTarget]
    """
    pubs: dict = {}
    for t in targets:
        if not t.enabled:
            continue
        try:
            cfg = json.loads(t.config_json) if t.config_json else {}
        except (ValueError, TypeError):
            cfg = {}
        adapter = _build_one(t.platform, cfg)
        if adapter is not None:
            pubs[t.platform] = adapter
        else:
            log.warning("暂不支持构造 '%s' publisher，跳过", t.platform)
    return pubs


def _build_one(platform: str, cfg: dict):
    if platform == "bilibili":
        from app.providers.publisher.bilibili import BilibiliPublisher
        try:
            tid = int(cfg.get("tid") or 17)
        except (ValueError, TypeError):
            tid = 17
        return BilibiliPublisher(
            sessdata=cfg.get("sessdata", ""), bili_jct=cfg.get("bili_jct", ""),
            dede_user_id=cfg.get("dede_user_id", ""), buvid3=cfg.get("buvid3", ""),
            buvid4=cfg.get("buvid4", ""), ac_time_value=cfg.get("ac_time_value", ""),
            tid=tid,
        )
    if platform == "youtube":
        from app.providers.publisher.youtube import YouTubePublisher
        return YouTubePublisher(client_id=cfg.get("client_id", ""), client_secret=cfg.get("client_secret", ""),
                                refresh_token=cfg.get("refresh_token", ""))
    return None
