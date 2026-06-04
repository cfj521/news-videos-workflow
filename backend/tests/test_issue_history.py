"""去重历史接线测试：成功生成后写入 issue_summaries，下次采集读回做 Layer1 去重。

回归此前的断链 bug —— issue_summaries 表存在、dedup Layer1 也支持 history_fingerprints，
但 runner 既不写历史也不读历史，导致跨期重复选题。"""

import json

import pytest

from app.logging import get_logger
from app.models.issue_summary import IssueSummary
from app.models.pipeline_run import PipelineRun
from app.pipeline.runner import _load_history_fingerprints, _record_issue_history
from app.providers.base import RawArticleData
from app.services.dedup import DedupService

log = get_logger("test")


@pytest.fixture
def run(db_session):
    r = PipelineRun(mode="auto", video_route="hyperframes", time_range="7d")
    db_session.add(r)
    db_session.commit()
    return r


def _article(title: str) -> RawArticleData:
    return RawArticleData(
        title=title, content="x", source_url=f"https://e.com/{title}", source_name="T"
    )


def test_record_writes_issue_history(db_session, run):
    articles = [_article("AI 大突破"), _article("量子计算新进展")]
    script = {"title": "本期科技日报"}

    _record_issue_history(db_session, run, articles, script, log)

    rows = db_session.query(IssueSummary).all()
    assert len(rows) == 1
    assert rows[0].run_id == run.id
    assert rows[0].summary_text == "本期科技日报"
    fps = json.loads(rows[0].article_fingerprints_json)
    dedup = DedupService()
    assert fps == [dedup.fingerprint("AI 大突破"), dedup.fingerprint("量子计算新进展")]


def test_load_history_fingerprints_roundtrip(db_session, run):
    _record_issue_history(db_session, run, [_article("AI 大突破")], {"title": "T"}, log)

    history_fps = _load_history_fingerprints(db_session)

    # 读回的历史指纹能让下一期把同一选题去掉
    new_batch = [_article("AI 大突破"), _article("全新选题")]
    result = DedupService().deduplicate(new_batch, history_fps)
    assert [a.title for a in result] == ["全新选题"]


def test_load_history_respects_limit(db_session, run):
    for i in range(35):
        _record_issue_history(db_session, run, [_article(f"选题{i}")], {"title": f"期{i}"}, log)

    fps = _load_history_fingerprints(db_session, limit=30)
    assert len(fps) == 30  # 每期 1 个指纹，最近 30 期
