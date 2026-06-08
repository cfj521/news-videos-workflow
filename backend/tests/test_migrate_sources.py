import json
import sqlite3
from pathlib import Path

import yaml

import app.store.sources_store as ss
from app.store.migrate import migrate_sources_to_yaml


def _make_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE news_sources (id INTEGER PRIMARY KEY, name TEXT, type TEXT,"
                 " url TEXT, category TEXT, language TEXT, priority INTEGER, enabled BOOLEAN,"
                 " tier TEXT, pinned BOOLEAN, config_json TEXT)")
    conn.execute("INSERT INTO news_sources VALUES (1,'Hacker News','api','https://hn.algolia.com/api/v1/',"
                 "'general','en',5,1,'free',0,NULL)")
    conn.execute("INSERT INTO news_sources VALUES (2,'机器之心','rss','https://x.com/feed',"
                 "'general','zh',5,1,'free',0,?)", (json.dumps({"provider": "rss"}),))
    conn.execute("CREATE TABLE pipeline_runs (id INTEGER PRIMARY KEY, source_ids TEXT)")
    conn.execute("INSERT INTO pipeline_runs VALUES (10, ?)", (json.dumps([1, 2]),))
    conn.execute("INSERT INTO pipeline_runs VALUES (11, ?)", (json.dumps([2]),))
    conn.commit()
    conn.close()


def test_migrate_sources_seeds_slugs_and_search_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "NEWS_SOURCES_PATH", tmp_path / "news_sources.yaml")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump({"collectors": {"tavily_key": "tk", "brave_key": "", "serper_key": ""}}),
        encoding="utf-8")
    db = tmp_path / "app.db"
    _make_db(db)

    migrate_sources_to_yaml(config_path=cfg, sqlite_path=db)

    slugs = {s.slug for s in ss.list_sources()}
    assert "hacker_news" in slugs and "rss" in slugs
    assert ss.get_source("hacker_news").type == "api"
    assert ss.load_search_keys()["tavily_key"] == "tk"


def test_migrate_sources_rewrites_run_source_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "NEWS_SOURCES_PATH", tmp_path / "news_sources.yaml")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("pipeline: {}\n", encoding="utf-8")
    db = tmp_path / "app.db"
    _make_db(db)

    migrate_sources_to_yaml(config_path=cfg, sqlite_path=db)

    conn = sqlite3.connect(db)
    rows = dict(conn.execute("SELECT id, source_ids FROM pipeline_runs").fetchall())
    conn.close()
    assert json.loads(rows[10]) == ["hacker_news", "rss"]
    assert json.loads(rows[11]) == ["rss"]


def test_migrate_sources_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "NEWS_SOURCES_PATH", tmp_path / "news_sources.yaml")
    ss.save_search_keys({"tavily_key": "keep", "brave_key": "", "serper_key": ""})
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"collectors": {"tavily_key": "no"}}), encoding="utf-8")
    migrate_sources_to_yaml(config_path=cfg, sqlite_path=tmp_path / "missing.db")
    assert ss.load_search_keys()["tavily_key"] == "keep"
