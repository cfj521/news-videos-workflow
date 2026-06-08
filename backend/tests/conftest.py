import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base


@pytest.fixture(autouse=True)
def _isolate_store_paths(tmp_path, monkeypatch):
    """全局隔离：把 model_providers.yaml / publish_targets.yaml 重定向到每测试临时目录，
    防止任何测试（尤其经 /api/settings → save_settings、/api/publishers → targets_store）
    写到仓库根的真实文件。自行 monkeypatch 这些路径的测试会在其测试体内覆盖此值。"""
    monkeypatch.setattr(
        "app.store.providers_store.MODEL_PROVIDERS_PATH",
        tmp_path / "model_providers.yaml",
    )
    monkeypatch.setattr(
        "app.store.targets_store.TARGETS_PATH",
        tmp_path / "publish_targets.yaml",
    )


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    session_factory = sessionmaker(bind=db_engine)
    session = session_factory()
    yield session
    session.close()
