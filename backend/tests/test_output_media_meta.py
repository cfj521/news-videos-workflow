from pathlib import Path
from app.api.pipeline import _output_media_meta


def test_mp3_meta():
    assert _output_media_meta(Path("/x/output.mp3")) == ("audio/mpeg", "mp3")


def test_mp4_meta():
    assert _output_media_meta(Path("/x/output.mp4")) == ("video/mp4", "mp4")
