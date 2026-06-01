import io
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.main import create_app
from app.models import Base  # noqa: F401


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.pipeline._run_dir", lambda run_id: tmp_path / str(run_id))
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sf = sessionmaker(bind=engine)
    app = create_app()
    Base.metadata.create_all(engine)

    def override_get_db():
        s = sf()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with patch("app.api.pipeline._run_pipeline_bg"):
        yield TestClient(app)


def _seed_articles(tmp_path, run_id, arts):
    d = tmp_path / str(run_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "articles.json").write_text(json.dumps(arts, ensure_ascii=False), encoding="utf-8")


def test_put_articles_overwrites_and_preserves_internal(client, tmp_path):
    _seed_articles(tmp_path, 1, [{"title": "old", "content": "c", "aihot_method": "daily", "aggregator_url": "x"}])
    new_list = [{"title": "新", "content": "正文", "summary": "", "source": "s", "url": "u", "aihot_method": "daily", "aggregator_url": "x"}]
    r = client.put("/api/pipeline/runs/1/articles", json=new_list)
    assert r.status_code == 200
    saved = json.loads((tmp_path / "1" / "articles.json").read_text(encoding="utf-8"))
    assert saved[0]["title"] == "新"
    assert saved[0]["aihot_method"] == "daily"


def test_put_articles_rejects_empty_items(client, tmp_path):
    _seed_articles(tmp_path, 1, [])
    r = client.put("/api/pipeline/runs/1/articles", json=[{"title": "", "content": ""}])
    assert r.status_code == 400


def test_import_url_appends(client, tmp_path):
    _seed_articles(tmp_path, 1, [{"title": "a", "content": "c"}])
    with patch("app.api.pipeline.import_url", new=AsyncMock(return_value={"title": "导入", "content": "正文", "summary": "", "source": "example.com", "url": "https://example.com"})):
        r = client.post("/api/pipeline/runs/1/articles/import/url", json={"url": "https://example.com"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[1]["title"] == "导入"


def test_import_file_appends(client, tmp_path):
    _seed_articles(tmp_path, 1, [])
    with patch("app.api.pipeline.import_file", new=AsyncMock(return_value={"title": "memo", "content": "hi", "summary": "", "source": "memo.txt", "url": ""})):
        r = client.post("/api/pipeline/runs/1/articles/import/file", files={"file": ("memo.txt", io.BytesIO(b"hi"), "text/plain")})
    assert r.status_code == 200
    assert r.json()[0]["title"] == "memo"


def test_import_file_unsupported_returns_400(client, tmp_path):
    _seed_articles(tmp_path, 1, [])
    with patch("app.api.pipeline.import_file", new=AsyncMock(side_effect=ValueError("unsupported"))):
        r = client.post("/api/pipeline/runs/1/articles/import/file", files={"file": ("a.zip", io.BytesIO(b"x"), "application/zip")})
    assert r.status_code == 400


# ─── 重新采集按钮按 AI HOT 模式分流 ───────────────────────────
def _new_run(client):
    return client.post("/api/pipeline/runs", json={}).json()["id"]


def test_reroll_daily_rejected(client, tmp_path):
    rid = _new_run(client)
    _seed_articles(tmp_path, rid, [{"title": "今日日报", "aihot_method": "daily"}])
    r = client.post(f"/api/pipeline/runs/{rid}/reroll-articles")
    assert r.status_code == 400  # 日报无意义，禁止


def test_reroll_weekly_is_resummarize(client, tmp_path):
    rid = _new_run(client)
    _seed_articles(tmp_path, rid, [{"title": "本周回顾", "aihot_method": "weekly"}])
    with patch("app.api.pipeline._reroll_articles_bg"):  # 别真跑采集
        r = client.post(f"/api/pipeline/runs/{rid}/reroll-articles")
    assert r.status_code == 200
    assert r.json()["status"] == "resummarizing"


def test_reroll_items_is_reroll(client, tmp_path):
    rid = _new_run(client)
    _seed_articles(tmp_path, rid, [{"title": "动态a", "aihot_method": "items"}])
    with patch("app.api.pipeline._reroll_articles_bg"):
        r = client.post(f"/api/pipeline/runs/{rid}/reroll-articles")
    assert r.status_code == 200
    assert r.json()["status"] == "rerolling"
