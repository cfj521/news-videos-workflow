"""字幕切分与字号相关回归测试。"""

from pathlib import Path

from app.pipeline.stage4_timeline import (
    _split_subtitles,
    _subtitle_max_chars,
    run_stage4,
)
from app.providers.composer.hyperframes_composer import HyperframesComposer


def test_decimal_point_not_split():
    """小数点不应被当作英文句号切开。"""
    lines = _split_subtitles("增长了3.5个百分点，全年达到99.9的水平", duration_ms=5000, max_chars=100)
    joined = "".join(l["text"] for l in lines)
    assert "3.5" in joined
    assert "99.9" in joined
    # 没有出现把 "3." 单独切出来的碎片
    assert not any(l["text"].endswith("3.") or l["text"].endswith("99.") for l in lines)


def test_sentence_period_still_splits():
    """真正的英文句号（其后非数字）仍应断句。"""
    lines = _split_subtitles("This is one. And two.", duration_ms=4000, max_chars=100)
    texts = [l["text"] for l in lines]
    assert "This is one." in texts
    assert "And two." in texts


def test_long_sentence_chunked_within_limit():
    """超长句应被切分，且每段不超过 max_chars。"""
    text = "这是一段没有句末标点的很长很长很长很长很长很长很长很长很长的旁白内容"
    lines = _split_subtitles(text, duration_ms=6000, max_chars=10)
    assert len(lines) > 1
    assert all(len(l["text"]) <= 10 for l in lines)


def test_chunk_prefers_clause_punctuation():
    """长句优先在逗号/顿号处切，片段仍受 max_chars 约束。"""
    text = "第一部分的内容，第二部分的内容，第三部分的内容，第四部分的内容"
    lines = _split_subtitles(text, duration_ms=8000, max_chars=12)
    assert len(lines) > 1
    assert all(len(l["text"]) <= 12 for l in lines)


def test_durations_cover_full_window():
    """切分后各段时间应连续且铺满整个时长。"""
    lines = _split_subtitles("一句。两句。三句。", duration_ms=9000, max_chars=100)
    assert lines[0]["start_ms"] == 0
    assert lines[-1]["end_ms"] == 9000
    for a, b in zip(lines, lines[1:]):
        assert a["end_ms"] == b["start_ms"]


def test_subtitle_max_chars_scales_with_resolution_and_font():
    assert _subtitle_max_chars("1080x1920", font_size=48, max_lines=2) == 36
    # 字号更大 → 每行容纳更少
    assert _subtitle_max_chars("1080x1920", font_size=96, max_lines=2) < 36
    # 更宽画面 → 每行容纳更多
    assert _subtitle_max_chars("1920x1080", font_size=48, max_lines=2) > 36


def test_run_stage4_applies_subtitle_limit():
    long_narration = "这是一段很长很长很长很长很长很长很长很长很长很长很长很长的旁白用于测试切分"
    scene_assets = [{"scene_id": 1, "image": {"file_path": "i.png"},
                     "audio": {"file_path": "a.mp3", "duration_ms": 6000}}]
    script = {"scenes": [{"id": 1, "narration": long_narration, "duration_hint": 6}]}
    timeline = run_stage4(script=script, scene_assets=scene_assets, scene_gap_ms=0,
                          resolution="1080x1920", subtitle_font_size=48, subtitle_max_lines=2)
    lines = timeline["entries"][0]["subtitle_lines"]
    assert all(len(l["text"]) <= 36 for l in lines)


def test_english_words_not_split_mid_word():
    """英文超长句应在空格/单词边界切，绝不把单词从字母中间劈开。

    回归：曾按字符位置硬切，导致 machines→machi+nes、bio-defense→bio-defe+nse。
    """
    text = "launching a new team to build machines that can serve society and infrastructure."
    lines = _split_subtitles(text, duration_ms=8000, max_chars=36)
    texts = [l["text"] for l in lines]
    # 每段不超过上限
    assert all(len(t) <= 36 for t in texts)
    # 重组后的单词序列与原文完全一致——没有单词被切断、也没丢字
    assert " ".join(texts).split() == text.split()
    # 多段（确实触发了切分）
    assert len(lines) > 1


def test_oversized_single_word_falls_back_to_hard_wrap():
    """单个词本身就超过上限（如长链接）时，对该词兜底硬切，短词不受影响。"""
    text = "see https://example.com/a/very/long/path/that/exceeds/limit now"
    lines = _split_subtitles(text, duration_ms=5000, max_chars=20)
    texts = [l["text"] for l in lines]
    assert all(len(t) <= 20 for t in texts)
    joined = " ".join(texts)
    assert "see" in joined.split() and "now" in joined.split()


def test_cjk_without_spaces_still_hard_wraps():
    """中日韩无空格文本保持按字符定长硬切（无“单词”概念）。"""
    text = "欧爱推出了一款名为罗莎琳德的新工具用于生物防御帮助世界应对新出现的生物威胁"
    lines = _split_subtitles(text, duration_ms=6000, max_chars=10)
    assert len(lines) > 1
    assert all(len(l["text"]) <= 10 for l in lines)
    assert "".join(l["text"] for l in lines) == text


def test_render_html_font_size_configurable():
    composer = HyperframesComposer()
    timeline = {"entries": [{"scene_id": 1, "start_ms": 0, "end_ms": 5000,
                             "image_path": "i.png", "audio_path": "a.mp3",
                             "audio_duration_ms": 5000, "subtitle_text": "字幕",
                             "subtitle_lines": [{"text": "字幕", "start_ms": 0, "end_ms": 5000}]}],
                "total_duration_ms": 5000}
    html = composer._render_html(timeline, "1080x1920", Path("."), subtitle_font_size=64)
    assert "font-size: 64px" in html
    # 默认值
    html_default = composer._render_html(timeline, "1080x1920", Path("."))
    assert "font-size: 48px" in html_default
