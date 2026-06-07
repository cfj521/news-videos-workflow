import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.news_source import NewsSource
from app.pipeline.runner import _sources_for_run


def _db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _seed(db):
    db.add_all([
        NewsSource(id=1, name="A", type="rss", url="https://a/feed", enabled=True),
        NewsSource(id=2, name="B", type="rss", url="https://b/feed", enabled=False),
        NewsSource(id=3, name="C", type="rss", url="https://c/feed", enabled=True),
    ])
    db.commit()


class _Run:
    def __init__(self, source_ids):
        self.source_ids = source_ids


def test_uses_run_source_ids():
    db = _db(); _seed(db)
    rows = _sources_for_run(db, _Run(json.dumps([1, 3])))
    assert sorted(s.id for s in rows) == [1, 3]


def test_falls_back_to_enabled_when_empty():
    db = _db(); _seed(db)
    rows = _sources_for_run(db, _Run(None))
    assert sorted(s.id for s in rows) == [1, 3]


def test_falls_back_when_blank_json():
    db = _db(); _seed(db)
    rows = _sources_for_run(db, _Run("[]"))
    assert sorted(s.id for s in rows) == [1, 3]


def test_falls_back_when_bad_json():
    db = _db(); _seed(db)
    rows = _sources_for_run(db, _Run("not-json"))
    assert sorted(s.id for s in rows) == [1, 3]
