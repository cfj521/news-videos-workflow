from pathlib import Path
from app.providers.composer.hyperframes_composer import HyperframesComposer


def _timeline(cover_audio=""):
    return {"total_duration_ms": 8000, "entries": [
        {"scene_id": 0, "is_cover": True, "start_ms": 0, "end_ms": 5000,
         "image_path": "assets/cover_image.png", "audio_path": cover_audio,
         "audio_duration_ms": 5000, "title": "每日AI资讯", "subtitle": "每天3分钟",
         "cover_font_size": 80, "subtitle_text": "", "subtitle_lines": [], "group_id": None},
        {"scene_id": 1, "is_cover": False, "start_ms": 5000, "end_ms": 8000,
         "image_path": "assets/scene_01_image.png", "audio_path": "assets/scene_01_audio.mp3",
         "audio_duration_ms": 3000, "title": "T1", "subtitle_text": "新闻一句话。",
         "subtitle_lines": [{"text": "新闻一句话。", "start_ms": 0, "end_ms": 3000}], "group_id": 1},
    ]}


def test_cover_html_has_title_subtitle_fontsize():
    html = HyperframesComposer()._render_html(_timeline(), "1080x1920", Path("."))
    assert "每日AI资讯" in html
    assert "每天3分钟" in html
    assert "80px" in html


def test_cover_without_audio_no_empty_audio_src():
    html = HyperframesComposer()._render_html(_timeline(cover_audio=""), "1080x1920", Path("."))
    assert 'src=""' not in html
