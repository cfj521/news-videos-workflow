from app.pipeline.runner import build_collectors_from_db


def _src(name, url, type_="rss", config_json=None):
    return {"name": name, "url": url, "type": type_, "config_json": config_json}


def test_aihot_and_regular_enabled_keeps_only_aihot():
    """采集兜底：AI HOT 与普通源同时启用时，只保留 AI HOT 组。"""
    sources = [
        _src("AI HOT", "https://aihot.virxact.com/api/public", "api",
             '{"provider":"aihot","method":"items"}'),
        _src("HN", "https://hn.algolia.com/api/v1/", "api"),
        _src("MarkTechPost", "https://www.marktechpost.com/feed/", "rss"),
    ]
    configs, collectors = build_collectors_from_db(sources)
    assert [c["type"] for c in configs] == ["aihot"]
    assert set(collectors.keys()) == {"aihot"}


def test_only_regular_sources_unaffected():
    """仅普通源启用时，全部保留。"""
    sources = [
        _src("HN", "https://hn.algolia.com/api/v1/", "api"),
        _src("MarkTechPost", "https://www.marktechpost.com/feed/", "rss"),
    ]
    configs, _ = build_collectors_from_db(sources)
    assert {c["name"] for c in configs} == {"HN", "MarkTechPost"}


def test_only_aihot_enabled_passthrough():
    """仅 AI HOT 启用时正常保留，且 config 透传。"""
    sources = [
        _src("AI HOT", "https://aihot.virxact.com/api/public", "api",
             '{"provider":"aihot","method":"daily"}'),
    ]
    configs, collectors = build_collectors_from_db(sources)
    assert [c["type"] for c in configs] == ["aihot"]
    assert configs[0]["method"] == "daily"
    assert set(collectors.keys()) == {"aihot"}
