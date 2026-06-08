import pytest

import app.store.targets_store as ts


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "TARGETS_PATH", tmp_path / "publish_targets.yaml")


def test_list_empty():
    assert ts.list_targets() == []


def test_create_generates_slug_from_name():
    t = ts.create_target(name="YouTube", platform="youtube", config={"client_id": "x"})
    assert t.slug == "youtube"
    assert t.name == "YouTube" and t.platform == "youtube" and t.enabled is True
    assert t.config == {"client_id": "x"}
    assert t.created_at


def test_create_chinese_name_falls_back_to_platform():
    t = ts.create_target(name="抖音官方", platform="douyin", config={})
    assert t.slug == "douyin"


def test_create_collision_appends_number():
    ts.create_target(name="YouTube", platform="youtube", config={})
    t2 = ts.create_target(name="YouTube", platform="youtube", config={})
    assert t2.slug == "youtube_1"


def test_get_update_delete():
    ts.create_target(name="YouTube", platform="youtube", config={"client_id": "a"})
    assert ts.get_target("youtube").config["client_id"] == "a"
    ts.update_target("youtube", {"enabled": False, "config": {"client_id": "b"}})
    got = ts.get_target("youtube")
    assert got.enabled is False and got.config["client_id"] == "b"
    ts.delete_target("youtube")
    assert ts.get_target("youtube") is None


def test_update_missing_returns_none():
    assert ts.update_target("nope", {"enabled": False}) is None


def test_create_explicit_slug():
    t = ts.create_target(name="My YT", platform="youtube", config={}, slug="custom_yt")
    assert t.slug == "custom_yt"
