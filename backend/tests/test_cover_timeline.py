"""封面 entry 插入 timeline 的测试：Task 4 + Task 5。"""
from app.pipeline.stage4_timeline import generate_srt, run_stage4


def _script():
    return {"scenes": [
        {"id": 1, "narration": "第一条新闻内容。", "title": "T1", "group_id": 1},
        {"id": 2, "narration": "第二条新闻内容。", "title": "T2", "group_id": 2},
    ]}


def _assets():
    return [
        {"scene_id": 1, "image": {"file_path": "/r/assets/scene_01_image.png"},
         "audio": {"file_path": "/r/assets/scene_01_audio.mp3", "duration_ms": 3000}},
        {"scene_id": 2, "image": {"file_path": "/r/assets/scene_02_image.png"},
         "audio": {"file_path": "/r/assets/scene_02_audio.mp3", "duration_ms": 4000}},
    ]


def test_no_cover_unchanged():
    tl = run_stage4(_script(), _assets(), scene_gap_ms=0)
    assert tl["entries"][0]["scene_id"] == 1
    assert tl["entries"][0]["start_ms"] == 0


def test_cover_prepended_and_shift():
    cover = {"scene_id": 0, "is_cover": True, "start_ms": 0, "end_ms": 5000,
             "image_path": "assets/cover_image.png", "audio_path": "assets/cover_audio.mp3",
             "audio_duration_ms": 5000, "title": "每日AI资讯", "subtitle": "",
             "cover_font_size": 72, "subtitle_text": "", "subtitle_lines": []}
    tl = run_stage4(_script(), _assets(), scene_gap_ms=0, cover=cover)
    e = tl["entries"]
    assert e[0]["is_cover"] is True and e[0]["start_ms"] == 0 and e[0]["end_ms"] == 5000
    assert e[1]["scene_id"] == 1 and e[1]["start_ms"] == 5000
    assert e[2]["scene_id"] == 2 and e[2]["start_ms"] == 5000 + 3000
    assert tl["total_duration_ms"] == 5000 + 3000 + 4000


def test_srt_skips_cover_and_offsets_news():
    cover = {"scene_id": 0, "is_cover": True, "start_ms": 0, "end_ms": 5000,
             "image_path": "", "audio_path": "", "audio_duration_ms": 5000,
             "title": "每日AI资讯", "subtitle": "", "cover_font_size": 72,
             "subtitle_text": "", "subtitle_lines": []}
    tl = run_stage4(_script(), _assets(), scene_gap_ms=0, cover=cover)
    srt = generate_srt(tl)
    assert "每日AI资讯" not in srt          # 封面不进字幕
    assert "00:00:05" in srt or "00:00:04," in srt  # 首条新闻字幕在封面之后
