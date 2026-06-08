import json
import sqlite3
from pathlib import Path

import app.store.targets_store as ts
from app.store.migrate import migrate_targets_to_yaml


def _make_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE publish_targets (id INTEGER PRIMARY KEY, name TEXT, platform TEXT,"
                 " enabled BOOLEAN, config_json TEXT)")
    conn.execute("INSERT INTO publish_targets VALUES (1,'YouTube','youtube',1,?)",
                 (json.dumps({"client_id": "x"}),))
    conn.execute("INSERT INTO publish_targets VALUES (2,'抖音','douyin',1,'{}')")
    conn.execute("CREATE TABLE pipeline_runs (id INTEGER PRIMARY KEY, publish_platforms TEXT)")
    conn.execute("INSERT INTO pipeline_runs VALUES (10, ?)", (json.dumps([1, 2]),))
    conn.execute("INSERT INTO pipeline_runs VALUES (11, ?)", (json.dumps([1]),))
    conn.commit()
    conn.close()


def test_migrate_targets_seeds_slugs(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "TARGETS_PATH", tmp_path / "publish_targets.yaml")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("pipeline: {}\n", encoding="utf-8")
    db = tmp_path / "app.db"
    _make_db(db)

    migrate_targets_to_yaml(config_path=cfg, sqlite_path=db)

    slugs = {t.slug for t in ts.list_targets()}
    assert slugs == {"youtube", "douyin"}
    assert ts.get_target("youtube").config["client_id"] == "x"


def test_migrate_targets_rewrites_run_publish_platforms(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "TARGETS_PATH", tmp_path / "publish_targets.yaml")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("pipeline: {}\n", encoding="utf-8")
    db = tmp_path / "app.db"
    _make_db(db)

    migrate_targets_to_yaml(config_path=cfg, sqlite_path=db)

    conn = sqlite3.connect(db)
    rows = dict(conn.execute("SELECT id, publish_platforms FROM pipeline_runs").fetchall())
    conn.close()
    assert json.loads(rows[10]) == ["youtube", "douyin"]
    assert json.loads(rows[11]) == ["youtube"]


def test_migrate_targets_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "TARGETS_PATH", tmp_path / "publish_targets.yaml")
    ts.create_target(name="Keep", platform="youtube", config={"client_id": "keep"})  # 文件已存在
    cfg = tmp_path / "config.yaml"
    cfg.write_text("pipeline: {}\n", encoding="utf-8")
    migrate_targets_to_yaml(config_path=cfg, sqlite_path=tmp_path / "missing.db")
    # 文件已存在 → 整体跳过，原 target 不被覆盖、也不新增
    assert {t.slug for t in ts.list_targets()} == {"keep"}
    assert ts.get_target("keep").config["client_id"] == "keep"
