import json

import pytest

import app.pipeline.runner as runner
import app.store.sources_store as ss


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "NEWS_SOURCES_PATH", tmp_path / "news_sources.yaml")


class _Run:
    def __init__(self, source_ids=None, aihot_config=None):
        self.source_ids = json.dumps(source_ids) if source_ids is not None else None
        self.aihot_config = json.dumps(aihot_config) if aihot_config is not None else None


def test_aihot_config_uses_aihot_source():
    run = _Run(aihot_config={"method": "daily"})
    cfgs, collectors = runner._collectors_for_run(None, run, None)
    assert cfgs[0]["type"] == "aihot" and "aihot" in collectors


def test_selected_slugs_build_those_sources():
    ss.create_source(name="HN", type="api", url="https://hn.algolia.com/api/v1/", slug="hn")
    ss.create_source(name="RSS One", type="rss", url="https://x.com/feed", slug="rss_one")
    run = _Run(source_ids=["rss_one"])
    cfgs, collectors = runner._collectors_for_run(None, run, None)
    names = [c["name"] for c in cfgs]
    assert "RSS One" in names and "HN" not in names


def test_no_source_ids_falls_back_to_hn():
    run = _Run()
    cfgs, collectors = runner._collectors_for_run(None, run, None)
    assert any(c["type"] == "hackernews_algolia" for c in cfgs)


def test_all_selected_sources_missing_raises():
    run = _Run(source_ids=["ghost_slug"])
    with pytest.raises(ValueError):
        runner._collectors_for_run(None, run, None)


def test_aihot_source_excluded_from_custom():
    ss.create_source(name="AIHot", type="api", url="u", slug="aihot_src", config={"provider": "aihot"})  # noqa: E501
    ss.create_source(name="RSS", type="rss", url="https://x.com/feed", slug="rss_one")
    run = _Run(source_ids=["aihot_src", "rss_one"])
    cfgs, _ = runner._collectors_for_run(None, run, None)
    names = [c["name"] for c in cfgs]
    assert "RSS" in names and "AIHot" not in names
