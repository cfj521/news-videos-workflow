from app.config import OverlayCfg
from app.providers.composer.overlay import build_drawtext


def test_build_drawtext_escapes_windows_path(tmp_path):
    font = tmp_path / "msyh.ttc"
    font.write_bytes(b"FONT")
    ov = OverlayCfg(font_file=str(font))
    txt = tmp_path / "t1.txt"
    f = build_drawtext("标题甲", 1080, 1920, ov, str(txt))
    assert f is not None
    assert "drawtext=" in f
    assert "\\:" in f                       # 路径冒号被转义（盘符或 tmp 路径）
    assert "x=w-tw-" in f and "box=1" in f
    assert txt.read_text(encoding="utf-8") == "标题甲"   # 文本写入 textfile


def test_build_drawtext_skips_when_font_missing(tmp_path):
    ov = OverlayCfg(font_file=str(tmp_path / "nope.ttc"))
    assert build_drawtext("标题", 1080, 1920, ov, str(tmp_path / "t.txt")) is None


def test_build_drawtext_skips_when_disabled_or_empty(tmp_path):
    font = tmp_path / "f.ttc"; font.write_bytes(b"F")
    assert build_drawtext("标题", 1080, 1920, OverlayCfg(enabled=False, font_file=str(font)), str(tmp_path / "t.txt")) is None
    assert build_drawtext("   ", 1080, 1920, OverlayCfg(font_file=str(font)), str(tmp_path / "t.txt")) is None
