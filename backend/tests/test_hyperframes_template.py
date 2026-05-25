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

    html = composer._render_html(timeline, resolution="1080x1920")

    assert 'data-composition-id="main"' in html
    assert 'data-width="1080"' in html
    assert 'data-height="1920"' in html
    assert 'id="s1"' in html
    assert 'id="s2"' in html
    assert "scene_01_image.png" in html
    assert "scene_01_audio.mp3" in html
    assert "第一段旁白文本" in html
    assert "window.__timelines" in html


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

    html = composer._render_html(timeline, resolution="1920x1080")
    assert 'data-width="1920"' in html
    assert 'data-height="1080"' in html
    assert "autoAlpha: 0" not in html  # first scene should NOT have hide toggle
