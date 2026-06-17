from pathlib import Path

from app.logging import get_logger

log = get_logger("composer.overlay")

# 配置的 font_file 不存在时（如 Linux 部署仍用 Windows 默认路径），按此清单自动探测系统 CJK 字体，
# 避免标题烧录在跨平台部署上静默跳过（drawtext 需真实字体文件）。
_CJK_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",      # Debian/Ubuntu fonts-noto-cjk
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",    # Fedora
    "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "C:/Windows/Fonts/msyh.ttc",                                   # Windows 微软雅黑
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",                          # macOS
    "/System/Library/Fonts/STHeiti Medium.ttc",
]


def _resolve_cjk_font(configured: str) -> str | None:
    """配置字体存在则用之；否则自动探测系统常见 CJK 字体；都没有返回 None。"""
    if configured and Path(configured).exists():
        return configured
    for cand in _CJK_FONT_CANDIDATES:
        if Path(cand).exists():
            if configured:
                log.info("overlay 配置字体 %s 不存在，自动改用系统字体 %s", configured, cand)
            return cand
    return None


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
    font = _resolve_cjk_font(overlay.font_file)
    if not font:
        log.warning("overlay 字体缺失（配置 %s 不存在，且未找到系统 CJK 字体）— 跳过标题烧录", overlay.font_file)
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
