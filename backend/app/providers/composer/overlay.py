from pathlib import Path

from app.logging import get_logger

log = get_logger("composer.overlay")


def _esc(p: str) -> str:
    """drawtext 选项里的路径转义：反斜杠转正斜杠、盘符/路径冒号转义为 \\:。"""
    return p.replace("\\", "/").replace(":", r"\:")


def build_drawtext(title: str, width: int, height: int, overlay, textfile_path: str) -> str | None:
    """拼右上角标题 drawtext filter；写文本到 textfile。

    返回 None（跳过烧录）当：overlay 关闭 / 标题空 / 字体文件缺失。
    box 为直角（FFmpeg 无圆角）。调用方把返回串拼进 vf。
    """
    if not overlay.enabled or not (title and title.strip()):
        return None
    font = overlay.font_file
    if not font or not Path(font).exists():
        log.warning("overlay 字体缺失：%s — 跳过该镜标题烧录", font)
        return None
    Path(textfile_path).write_text(title, encoding="utf-8")
    fontsize = max(12, int(height * overlay.font_size_ratio))
    margin = int(min(width, height) * overlay.margin_ratio)
    return (
        f"drawtext=fontfile={_esc(font)}:textfile={_esc(textfile_path)}:reload=0"
        f":fontcolor={overlay.color}:fontsize={fontsize}"
        f":box=1:boxcolor=black@{overlay.bg_opacity}:boxborderw={max(6, fontsize // 4)}"
        f":x=w-tw-{margin}:y={margin}"
    )
