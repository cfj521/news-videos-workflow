import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.news_source import NewsSource
from app.pipeline.runner import _aihot_source_config, _collectors_for_run
from app.config import get_settings


def _db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


class _Run:
    def __init__(self, aihot_config=None, source_ids=None):
        self.aihot_config = aihot_config
        self.source_ids = source_ids


def test_aihot_source_config_passes_params():
    cfg = _aihot_source_config({"method": "weekly", "week_start": "2026-01-05"})
    assert cfg["type"] == "aihot" and cfg["method"] == "weekly" and cfg["week_start"] == "2026-01-05"


def test_aihot_source_config_defaults_items():
    assert _aihot_source_config({})["method"] == "items"


def test_collectors_for_run_aihot_mode():
    db = _db()
    scs, cols = _collectors_for_run(db, _Run(aihot_config=json.dumps({"method": "daily"})), get_settings())
    assert len(scs) == 1 and scs[0]["type"] == "aihot" and scs[0]["method"] == "daily"
    assert "aihot" in cols


def test_collectors_for_run_custom_filters_residual_aihot():
    db = _db()
    db.add_all([
        NewsSource(id=1, name="RSS", type="rss", url="https://a/feed", enabled=True),
        NewsSource(id=2, name="AI HOT", type="api", url="https://aihot.virxact.com/api/public",
                   enabled=True, config_json=json.dumps({"provider": "aihot"})),
    ])
    db.commit()
    scs, cols = _collectors_for_run(db, _Run(source_ids=json.dumps([1, 2])), get_settings())
    names = [s["name"] for s in scs]
    assert "RSS" in names and "AI HOT" not in names


def test_collectors_for_run_empty_defaults_hn():
    db = _db()
    scs, cols = _collectors_for_run(db, _Run(), get_settings())
    assert len(scs) == 1 and scs[0]["type"] == "hackernews_algolia"
