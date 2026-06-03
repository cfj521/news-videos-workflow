import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.auth import get_current_user
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
    app.dependency_overrides[get_current_user] = lambda: "admin"
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


def test_delete_last_scene_cascades_group_and_article(client, tmp_path):
    # 删某组最后一个分镜 → 连带删该分组及其对应文章（当前行为）
    _seed(tmp_path, 1, SCRIPT, ARTICLES)
    r = client.delete("/api/pipeline/runs/1/scenes/2")
    assert r.status_code == 200
    saved = json.loads((tmp_path / "1" / "script.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in saved["scenes"]] == [1]
    assert [g["id"] for g in saved["groups"]] == [1]
    arts = json.loads((tmp_path / "1" / "articles.json").read_text(encoding="utf-8"))
    assert [a["title"] for a in arts] == ["文章1"]


def test_delete_last_scene_keeps_shared_article(client, tmp_path):
    # 日报/周报：多分组共享同一篇汇总文章(source_index=0)，删一组的最后分镜不应删掉这篇文章
    s = {"title": "T", "description": "d", "tags": [],
         "groups": [{"id": 1, "title": "模型", "source_index": 0}, {"id": 2, "title": "行业", "source_index": 0}],
         "scenes": [{"id": 1, "group_id": 1, "narration": "n1", "image_prompt": "p", "motion_prompt": "", "duration_hint": 5},
                    {"id": 2, "group_id": 2, "narration": "n2", "image_prompt": "p", "motion_prompt": "", "duration_hint": 5}]}
    _seed(tmp_path, 1, s, [{"title": "今日AI日报", "content": "c"}])
    r = client.delete("/api/pipeline/runs/1/scenes/1")
    assert r.status_code == 200
    saved = json.loads((tmp_path / "1" / "script.json").read_text(encoding="utf-8"))
    assert [g["id"] for g in saved["groups"]] == [2]
    assert saved["groups"][0]["source_index"] == 0  # 未被错误前移
    arts = json.loads((tmp_path / "1" / "articles.json").read_text(encoding="utf-8"))
    assert len(arts) == 1  # 共享文章仍在


def test_delete_scene_legacy_no_group_id(client, tmp_path):
    legacy = {"title": "T", "description": "d", "tags": [],
              "scenes": [
                  {"id": 1, "narration": "n1", "image_prompt": "p1", "motion_prompt": "", "duration_hint": 5},
                  {"id": 2, "narration": "n2", "image_prompt": "p2", "motion_prompt": "", "duration_hint": 5},
              ]}
    _seed(tmp_path, 1, legacy, ARTICLES)
    r = client.delete("/api/pipeline/runs/1/scenes/1")
    assert r.status_code == 200  # both are group None → group has 2 → delete allowed
