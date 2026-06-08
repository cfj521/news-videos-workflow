from app.providers.publisher import build_publishers
from app.store.targets_store import TargetData


def test_build_publishers_from_targetdata_bilibili():
    t = TargetData(slug="bili_main", name="B站", platform="bilibili", enabled=True,
                   config={"sessdata": "s", "bili_jct": "j", "tid": "17"})
    pubs = build_publishers([t])
    assert len(pubs) == 1
    target, adapter = pubs[0]
    assert target.slug == "bili_main"
    assert adapter is not None


def test_build_publishers_skips_disabled():
    t = TargetData(slug="x", name="x", platform="bilibili", enabled=False, config={})
    assert build_publishers([t]) == []


def test_build_publishers_skips_unsupported_platform():
    t = TargetData(slug="x", name="x", platform="nonexistent", enabled=True, config={})
    assert build_publishers([t]) == []
