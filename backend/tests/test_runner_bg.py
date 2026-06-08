import app.pipeline.runner as runner


def test_run_pipeline_bg_invokes_execute_pipeline(monkeypatch):
    """run_pipeline_bg 应通过 asyncio.run 调用 execute_pipeline 一次。"""
    calls = []

    async def fake_execute(run_id, factory):
        calls.append((run_id, factory))

    monkeypatch.setattr(runner, "execute_pipeline", fake_execute)
    runner.run_pipeline_bg(7, "FACTORY")
    assert calls == [(7, "FACTORY")]


def test_runner_has_no_api_layer_import():
    """runner 不得 import app.api.*（防循环依赖回归）。"""
    import inspect
    src = inspect.getsource(runner)
    assert "app.api" not in src
