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


def _seed(tmp_path, run_id, script, articles):
    d = tmp_path / str(run_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "script.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    (d / "articles.json").write_text(json.dumps(articles, ensure_ascii=False), encoding="utf-8")


SCRIPT = {
    "title": "T", "description": "d", "tags": [],
    "groups": [{"id": 1, "title": "文章1", "source_index": 0}, {"id": 2, "title": "文章2", "source_index": 1}],
    "scenes": [
        {"id": 1, "group_id": 1, "group_title": "文章1", "narration": "n1", "image_prompt": "p1", "motion_prompt": "", "duration_hint": 5},
        {"id": 2, "group_id": 2, "group_title": "文章2", "narration": "n2", "image_prompt": "p2", "motion_prompt": "", "duration_hint": 5},
    ],
}
ARTICLES = [{"title": "文章1", "content": "c1"}, {"title": "文章2", "content": "c2"}]


def test_add_scene_appends_to_group(client, tmp_path):
    _seed(tmp_path, 1, SCRIPT, ARTICLES)
    fake = '{"scenes":[{"narration":"new","image_prompt":"np","motion_prompt":"nm","duration_hint":4}]}'
    with patch("app.api.pipeline._build_text_provider") as mk:
        tp = mk.return_value
        tp.generate = AsyncMock(return_value=fake)
        r = client.post("/api/pipeline/runs/1/scenes", json={"group_id": 1, "requirement": "讲讲X"})
    assert r.status_code == 200
    new = r.json()
    assert new["group_id"] == 1 and new["id"] == 3 and new["narration"] == "new"
    saved = json.loads((tmp_path / "1" / "script.json").read_text(encoding="utf-8"))
    g1 = [s for s in saved["scenes"] if s["group_id"] == 1]
    assert len(g1) == 2


def test_delete_scene_ok(client, tmp_path):
    s = json.loads(json.dumps(SCRIPT))
    s["scenes"].append({"id": 3, "group_id": 1, "group_title": "文章1", "narration": "n3", "image_prompt": "p3", "motion_prompt": "", "duration_hint": 5})
    _seed(tmp_path, 1, s, ARTICLES)
    r = client.delete("/api/pipeline/runs/1/scenes/3")
    assert r.status_code == 200
    saved = json.loads((tmp_path / "1" / "script.json").read_text(encoding="utf-8"))
    assert 3 not in [sc["id"] for sc in saved["scenes"]]


def test_delete_last_scene_in_group_blocked(client, tmp_path):
    _seed(tmp_path, 1, SCRIPT, ARTICLES)
    r = client.delete("/api/pipeline/runs/1/scenes/2")
    assert r.status_code == 400
