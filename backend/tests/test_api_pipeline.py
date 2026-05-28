from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.main import create_app
from app.models import Base  # noqa: F401 – side-effect: registers all ORM models


@pytest.fixture
def client():
    # StaticPool ensures all connections share the same in-memory SQLite database.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine)

    app = create_app()
    # create_app() triggers imports of all ORM models via api_router; create tables after.
    Base.metadata.create_all(engine)

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    # 阻止创建 run 时触发真实后台流水线（会跑网络/卡住），测试只验证接口行为
    with patch("app.api.pipeline._run_pipeline_bg"):
        yield TestClient(app)


def test_create_pipeline_run(client):
    response = client.post(
        "/api/pipeline/runs",
        json={
            "mode": "auto",
            "video_route": "hyperframes",
            "time_range": "7d",
            "max_articles": 5,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "pending"
    assert data["id"] is not None


def test_list_pipeline_runs(client):
    client.post("/api/pipeline/runs", json={"time_range": "7d"})
    response = client.get("/api/pipeline/runs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


def test_get_pipeline_run(client):
    create_resp = client.post("/api/pipeline/runs", json={"time_range": "7d"})
    run_id = create_resp.json()["id"]
    response = client.get(f"/api/pipeline/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["id"] == run_id


def test_get_nonexistent_run(client):
    response = client.get("/api/pipeline/runs/9999")
    assert response.status_code == 404


def test_create_source(client):
    response = client.post(
        "/api/sources/",
        json={"name": "Test RSS", "type": "rss", "url": "https://example.com/feed"},
    )
    assert response.status_code == 201
    assert response.json()["name"] == "Test RSS"
    assert response.json()["enabled"] is True


def test_list_sources(client):
    client.post(
        "/api/sources/",
        json={"name": "Source1", "type": "rss", "url": "https://a.com/feed", "priority": 2},
    )
    client.post(
        "/api/sources/",
        json={"name": "Source2", "type": "api", "url": "https://b.com/api", "priority": 1},
    )
    response = client.get("/api/sources/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["priority"] <= data[1]["priority"]


def test_update_source(client):
    create_resp = client.post(
        "/api/sources/",
        json={"name": "Src", "type": "rss", "url": "https://x.com/feed"},
    )
    source_id = create_resp.json()["id"]
    response = client.patch(f"/api/sources/{source_id}", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False
