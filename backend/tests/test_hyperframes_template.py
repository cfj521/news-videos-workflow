from pathlib import Path

from app.providers.composer.hyperframes_composer import HyperframesComposer


def test_render_html_template():
    composer = HyperframesComposer()
    timeline = {
        "entries": [
            {
                "scene_id": 1,
                "start_ms": 0,
                "end_ms": 5000,
                "image_path": "assets/scene_01_image.png",
                "audio_path": "assets/scene_01_audio.mp3",
                "audio_duration_ms": 5000,
                "subtitle_text": "第一段旁白文本",
                "subtitle_lines": [{"text": "第一段旁白文本", "start_ms": 0, "end_ms": 5000}],
            },
            {
                "scene_id": 2,
                "start_ms": 5000,
                "end_ms": 11000,
                "image_path": "assets/scene_02_image.png",
                "audio_path": "assets/scene_02_audio.mp3",
                "audio_duration_ms": 6000,
                "subtitle_text": "第二段旁白文本",
            },
        ],
        "total_duration_ms": 11000,
    }

    html = composer._render_html(timeline, resolution="1080x1920", run_dir=Path("."))

    assert 'data-composition-id="main"' in html
    assert 'data-width="1080"' in html
    assert 'data-height="1920"' in html
    assert 'id="s1"' in html
    assert 'id="s2"' in html
    assert "scene_01_image.png" in html
    assert "scene_01_audio.mp3" in html
    assert "第一段旁白文本" in html
    assert "window.__timelines" in html
    # 预览音频驱动：按时间轴同步播放各分镜旁白
    assert "syncAudio" in html
    assert "gsap.ticker.add(syncAudio)" in html
    # 渲染成片不烧字幕（顶层加载时隐藏字幕元素），仅预览(iframe)显示
    assert "window.self === window.top" in html
    assert "el.style.display = 'none'" in html


def test_render_html_single_scene():
    composer = HyperframesComposer()
    timeline = {
        "entries": [
            {
                "scene_id": 1,
                "start_ms": 0,
                "end_ms": 5000,
                "image_path": "img.png",
                "audio_path": "audio.mp3",
                "audio_duration_ms": 5000,
                "subtitle_text": "单场景",
            },
        ],
        "total_duration_ms": 5000,
    }

    html = composer._render_html(timeline, resolution="1920x1080", run_dir=Path("."))
    assert 'data-width="1920"' in html
    assert 'data-height="1080"' in html
    assert "autoAlpha: 0" not in html  # first scene should NOT have hide toggle


def test_render_html_group_title_overlays():
    from app.config import OverlayCfg
    composer = HyperframesComposer(overlay=OverlayCfg())
    timeline = {"entries": [
        {"scene_id": 1, "start_ms": 0, "end_ms": 4000, "image_path": "i1.png", "audio_path": "a1.mp3",
         "audio_duration_ms": 4000, "subtitle_lines": [], "title": "标题甲", "group_id": 1},
        {"scene_id": 2, "start_ms": 4000, "end_ms": 8000, "image_path": "i2.png", "audio_path": "a2.mp3",
         "audio_duration_ms": 4000, "subtitle_lines": [], "title": "标题甲", "group_id": 1},
        {"scene_id": 3, "start_ms": 8000, "end_ms": 12000, "image_path": "i3.png", "audio_path": "a3.mp3",
         "audio_duration_ms": 4000, "subtitle_lines": [], "title": "标题乙", "group_id": 2},
    ], "total_duration_ms": 12000}
    html = composer._render_html(timeline, resolution="1080x1920", run_dir=Path("."))
    assert "group-title" in html
    assert html.count('class="group-title"') == 2     # 2 组 → 2 个标题块（首组跨两镜合并）
    assert "标题甲" in html and "标题乙" in html
