from app.pipeline.stage4_timeline import generate_srt, run_stage4


def test_stage4_generates_timeline():
    scene_assets = [
        {
            "scene_id": 1,
            "image": {"file_path": "assets/scene_01_image.png"},
            "audio": {"file_path": "assets/scene_01_audio.mp3", "duration_ms": 5000},
        },
        {
            "scene_id": 2,
            "image": {"file_path": "assets/scene_02_image.png"},
            "audio": {"file_path": "assets/scene_02_audio.mp3", "duration_ms": 7000},
        },
    ]
    script = {
        "scenes": [
            {"id": 1, "narration": "第一段旁白", "duration_hint": 5},
            {"id": 2, "narration": "第二段旁白", "duration_hint": 5},
        ],
    }

    timeline = run_stage4(script=script, scene_assets=scene_assets)

    assert timeline["total_duration_ms"] == 12000
    assert len(timeline["entries"]) == 2
    assert timeline["entries"][0]["start_ms"] == 0
    assert timeline["entries"][0]["end_ms"] == 5000
    assert timeline["entries"][1]["start_ms"] == 5000
    assert timeline["entries"][1]["end_ms"] == 12000


def test_stage4_uses_audio_duration_over_hint():
    scene_assets = [
        {
            "scene_id": 1,
            "image": {"file_path": "img.png"},
            "audio": {"file_path": "audio.mp3", "duration_ms": 8000},
        },
    ]
    script = {"scenes": [{"id": 1, "narration": "Text", "duration_hint": 5}]}

    timeline = run_stage4(script=script, scene_assets=scene_assets)
    assert timeline["entries"][0]["end_ms"] == 8000


def test_stage4_skips_errored_scenes():
    scene_assets = [
        {
            "scene_id": 1,
            "image": {"file_path": "img.png"},
            "audio": {"file_path": "a.mp3", "duration_ms": 5000},
        },
        {"scene_id": 2, "error": "generation failed"},
    ]
    script = {
        "scenes": [
            {"id": 1, "narration": "OK", "duration_hint": 5},
            {"id": 2, "narration": "Failed", "duration_hint": 5},
        ],
    }

    timeline = run_stage4(script=script, scene_assets=scene_assets)
    assert len(timeline["entries"]) == 1
    assert timeline["total_duration_ms"] == 5000


def test_generate_srt():
    timeline = {
        "entries": [
            {"scene_id": 1, "start_ms": 0, "end_ms": 5000, "subtitle_text": "第一段"},
            {"scene_id": 2, "start_ms": 5000, "end_ms": 10000, "subtitle_text": "第二段"},
        ],
    }
    srt = generate_srt(timeline)
    assert "1\n00:00:00,000 --> 00:00:05,000\n第一段" in srt
    assert "2\n00:00:05,000 --> 00:00:10,000\n第二段" in srt
