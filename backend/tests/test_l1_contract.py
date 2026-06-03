"""L1 API 契约补充测试 — 覆盖既有测试未触及的 P0/安全/运维契约点。

对应《acceptance-test-plan.md》第 3 节：密钥脱敏、回传脱敏值不覆盖真实密钥、
infra 不可改、删运行中→409、删任务清目录、video 404、素材路径穿越、
publishers CRUD、源批量更新。
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.api.dependencies import get_db
from app.auth import get_current_user
from app.main import create_app
from app.models import Base  # noqa: F401 – 注册 ORM 模型
from app.models.pipeline_run import PipelineRun


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr("app.api.pipeline._run_dir", lambda run_id: tmp_path / "runs" / str(run_id))
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
    app.dependency_overrides[get_current_user] = lambda: "admin"
    with patch("app.api.pipeline._run_pipeline_bg"):
        yield TestClient(app), sf, tmp_path


def _create_run(client):
    return client.post("/api/pipeline/runs", json={"time_range": "7d"}).json()["id"]


# ─── 设置：密钥安全（P0） ─────────────────────────────────────

def test_settings_get_redacts_secret(env):
    client, _, _ = env
    client.put("/api/settings/", json={"text": {"api_key": "sk-1234567890abcdef"}})
    got = client.get("/api/settings/").json()
    assert got["text"]["api_key"] == "sk-1...cdef"  # 脱敏显示
    raw = client.get("/api/settings/raw").json()
    assert raw["text"]["api_key"] == "sk-1234567890abcdef"  # /raw 供编辑，返回完整值


def test_settings_put_redacted_key_not_overwrite(env):
    client, _, _ = env
    client.put("/api/settings/", json={"text": {"api_key": "sk-1234567890abcdef"}})
    # 前端把脱敏值原样回传，不应覆盖真实密钥；同组其它字段照常更新
    client.put("/api/settings/", json={"text": {"api_key": "sk-1...cdef", "model": "gpt-x"}})
    raw = client.get("/api/settings/raw").json()
    assert raw["text"]["api_key"] == "sk-1234567890abcdef"
    assert raw["text"]["model"] == "gpt-x"


def test_settings_put_ignores_infra(env):
    client, _, _ = env
    before = client.get("/api/settings/raw").json()["infra"]["database_url"]
    client.put("/api/settings/", json={"infra": {"database_url": "postgresql:///evil"}})
    after = client.get("/api/settings/raw").json()["infra"]["database_url"]
    assert after == before  # infra 组被忽略


# ─── Pipeline：运维契约 ───────────────────────────────────────

def test_resume_run(env):
    client, sf, _ = env
    rid = _create_run(client)
    s = sf(); run = s.get(PipelineRun, rid); run.status = "review"; s.commit(); s.close()
    r = client.post(f"/api/pipeline/runs/{rid}/resume")
    assert r.status_code == 200
    assert r.json()["status"] == "resumed"


def test_delete_processing_run_conflict(env):
    client, sf, _ = env
    rid = _create_run(client)
    s = sf(); run = s.get(PipelineRun, rid); run.status = "processing"; s.commit(); s.close()
    r = client.delete(f"/api/pipeline/runs/{rid}")
    assert r.status_code == 409  # 运行中禁止删除


def test_delete_run_removes_dir(env):
    client, _, tmp = env
    rid = _create_run(client)
    rd = tmp / "runs" / str(rid)
    (rd / "assets").mkdir(parents=True, exist_ok=True)
    (rd / "script.json").write_text("{}", encoding="utf-8")
    r = client.delete(f"/api/pipeline/runs/{rid}")
    assert r.status_code == 200
    assert not rd.exists()  # 任务目录被清理


def test_video_404_when_no_output(env):
    client, _, _ = env
    rid = _create_run(client)
    r = client.get(f"/api/pipeline/runs/{rid}/video")
    assert r.status_code == 404


def test_asset_traversal_blocked(env):
    """素材服务不应被 ../ 穿越读到 assets 目录之外的文件。"""
    client, _, tmp = env
    rid = _create_run(client)
    rd = tmp / "runs" / str(rid)
    (rd / "assets").mkdir(parents=True, exist_ok=True)
    (rd / "secret.txt").write_text("TOPSECRET", encoding="utf-8")
    r = client.get(f"/api/pipeline/runs/{rid}/assets/..%2fsecret.txt")
    assert r.status_code == 404 or "TOPSECRET" not in r.text


# ─── Publishers / Sources ─────────────────────────────────────

def test_publishers_crud(env):
    client, _, _ = env
    r = client.post("/api/publishers/", json={"name": "yt", "platform": "youtube"})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert client.get("/api/publishers/").status_code == 200
    assert client.patch(f"/api/publishers/{pid}", json={"enabled": False}).json()["enabled"] is False
    assert client.delete(f"/api/publishers/{pid}").status_code == 200
    assert client.delete("/api/publishers/9999").status_code == 404


def test_sources_batch_update(env):
    client, _, _ = env
    ids = [client.post("/api/sources/", json={"name": f"s{i}", "type": "rss", "url": f"https://a{i}.com"}).json()["id"]
           for i in range(2)]
    r = client.post("/api/sources/batch", json={"ids": ids, "enabled": False})
    assert r.status_code == 200
    assert all(s["enabled"] is False for s in r.json())
