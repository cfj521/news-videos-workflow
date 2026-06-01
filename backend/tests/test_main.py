from fastapi.testclient import TestClient

from app.main import create_app


def test_health_check():
    app = create_app()
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_root():
    app = create_app()
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200


def test_ensure_pipeline_run_columns_adds_missing(tmp_path):
    from sqlalchemy import create_engine, text
    from app.main import _ensure_pipeline_run_columns
    db_file = tmp_path / "legacy.db"
    eng = create_engine(f"sqlite:///{db_file}")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE pipeline_runs (id INTEGER PRIMARY KEY, mode TEXT)"))
    _ensure_pipeline_run_columns(eng)
    with eng.connect() as c:
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(pipeline_runs)"))]
    assert "auto_collect" in cols and "resolution" in cols and "aspect_ratio" in cols
    _ensure_pipeline_run_columns(eng)  # idempotent, no error
