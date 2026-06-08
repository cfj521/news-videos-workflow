import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml

import app.store.providers_store as ps
from app.store.migrate import migrate_providers_to_yaml


def _make_sqlite_with_oauth(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE oauth_credentials ("
        "provider TEXT, access_token TEXT, refresh_token TEXT,"
        " id_token TEXT, account_id TEXT, expires_at TEXT,"
        " plan_type TEXT, account_email TEXT, last_refresh TEXT)"
    )
    conn.execute(
        "INSERT INTO oauth_credentials VALUES (?,?,?,?,?,?,?,?,?)",
        ("openai", "acc-tok", "ref-tok", "idt", "acc1",
         datetime(2026, 6, 7, tzinfo=timezone.utc).isoformat(), "plus", "u@e.com", ""),
    )
    conn.commit()
    conn.close()


def test_migrate_seeds_providers_and_oauth(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({
        "providers": {"openai": {"base_url": "https://api.openai.com/v1", "api_key": "sk-old"}},
    }), encoding="utf-8")
    db = tmp_path / "app.db"
    _make_sqlite_with_oauth(db)
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")

    migrate_providers_to_yaml(config_path=cfg, sqlite_path=db)

    assert ps.load_providers()["openai"].api_key == "sk-old"
    assert ps.load_oauth("openai").access_token == "acc-tok"


def test_migrate_idempotent_skips_when_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")
    ps.save_providers({})  # 文件已存在
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump({"providers": {"openai": {"api_key": "sk-should-not-load"}}}),
        encoding="utf-8",
    )
    migrate_providers_to_yaml(config_path=cfg, sqlite_path=tmp_path / "missing.db")
    assert "openai" not in ps.load_providers()


def test_migrate_no_db_no_providers_writes_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "MODEL_PROVIDERS_PATH", tmp_path / "model_providers.yaml")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("pipeline: {}\n", encoding="utf-8")
    migrate_providers_to_yaml(config_path=cfg, sqlite_path=tmp_path / "missing.db")
    assert ps.load_providers() == {}
