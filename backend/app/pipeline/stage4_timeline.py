import re

from app.logging import get_logger

log = get_logger("stage4")


def _subtitle_max_chars(resolution: str, font_size: int, max_lines: int) -> int:
    """按渲染分辨率与字号估算单条字幕的最大字符数（控制在 max_lines 行以内）。

    字幕区最大宽度约为画面 80%（见模板 .subtitle max-width:80%），中文字形宽度 ≈ 字号，
    故每行约 0.8*width/font_size 个字，乘以行数即上限。
    """
    try:
        width = int(resolution.split("x")[0])
    except (ValueError, AttributeError, IndexError):
        width = 1080
    chars_per_line = max(6, int(width * 0.8 / max(font_size, 1)))
    return chars_per_line * max(1, max_lines)


def run_stage4(
    script: dict,
    scene_assets: list[dict],
    min_scene_ms: int = 2000,
    max_scene_ms: int = 15000,
    scene_gap_ms: int = 500,
    resolution: str = "1080x1920",
    subtitle_font_size: int = 48,
    subtitle_max_lines: int = 2,
) -> dict:
    max_chars = _subtitle_max_chars(resolution, subtitle_font_size, subtitle_max_lines)
    narration_map = {s["id"]: s for s in script["scenes"]}
    entries: list[dict] = []
    current_ms = 0
    skipped = 0

    for asset in scene_assets:
        if "error" in asset and not asset.get("audio"):
            skipped += 1
            log.warning("Skipping scene %d — no audio, error: %s", asset["scene_id"], asset.get("error", ""))
            continue

        scene_id = asset["scene_id"]
        scene_data = narration_map.get(scene_id, {})
        audio_duration = asset.get("audio", {}).get("duration_ms", 0)
        hint_ms = int(scene_data.get("duration_hint", 5) * 1000)
        if audio_duration > 0:
            # 有真实音频：分镜时长跟随音频，完整播放，不用 max_scene_ms 截断（否则长旁白会被切）
            duration_ms = max(min_scene_ms, audio_duration)
        else:
            # 无音频（如纯图片/估算回退）：用 hint，受 max_scene_ms 上限约束
            duration_ms = max(min_scene_ms, min(hint_ms, max_scene_ms))
        duration_ms += scene_gap_ms

        narration = scene_data.get("narration", "")
        subtitle_lines = _split_subtitles(narration, duration_ms - scene_gap_ms, max_chars)

        entry = {
            "scene_id": scene_id,
            "start_ms": current_ms,
            "end_ms": current_ms + duration_ms,
            "image_path": asset.get("image", {}).get("file_path", ""),
            "audio_path": asset.get("audio", {}).get("file_path", ""),
            "audio_duration_ms": audio_duration,
            "subtitle_text": narration,
            "subtitle_lines": subtitle_lines,
            "title": scene_data.get("title") or scene_data.get("group_title", ""),
            "group_id": scene_data.get("group_id"),
        }
        entries.append(entry)
        log.debug("S%d: %dms–%dms (%dms, %d subtitle lines)", scene_id, current_ms, current_ms + duration_ms, duration_ms, len(subtitle_lines))
        current_ms += duration_ms

    if skipped:
        log.warning("Skipped %d scenes due to errors", skipped)
    log.info("Timeline: %d entries, %.1fs total (gap=%dms)", len(entries), current_ms / 1000, scene_gap_ms)

    return {"entries": entries, "total_duration_ms": current_ms}


# 句末断句：中文句末标点恒断；英文句末标点恒断；英文句点 "." 仅当其后不是数字时才断，
# 避免把小数点（如 3.5、99.9%）误当成句号切开。
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；!?;])|(?<=\.)(?!\d)")
# 长句二次切分用的次级标点（逗号、顿号、冒号等）
_CLAUSE_SPLIT = re.compile(r"(?<=[，,、：:])")


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _wrap_text(text: str, max_chars: int) -> list[str]:
    """把超长文本折成 ≤ max_chars 的片段：含空格（西文）按单词边界断，绝不切断单词；
    无空格（中日韩）按字符定长硬切。单个词本身超长（如长链接）才对该词硬切。"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    # 无空格（CJK）：保持原定长硬切
    if " " not in text:
        return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
    # 含空格（西文）：按单词贪心打包，避免把单词从中间切开
    chunks: list[str] = []
    cur = ""
    for word in text.split():
        if len(word) > max_chars:  # 单个词就超长（极端）：冲掉 cur 再硬切该词
            if cur:
                chunks.append(cur)
                cur = ""
            for i in range(0, len(word), max_chars):
                chunks.append(word[i:i + max_chars])
        elif not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= max_chars:
            cur += " " + word
        else:
            chunks.append(cur)
            cur = word
    if cur:
        chunks.append(cur)
    return chunks


def _chunk_sentence(sentence: str, max_chars: int) -> list[str]:
    """把过长的句子按次级标点贪心打包成 ≤ max_chars 的片段；单个分句仍超长则按词/字断。"""
    if len(sentence) <= max_chars:
        return [sentence]
    chunks: list[str] = []
    cur = ""
    for clause in (c for c in _CLAUSE_SPLIT.split(sentence) if c):
        if len(clause) > max_chars:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.extend(_wrap_text(clause, max_chars))
        elif len(cur) + len(clause) <= max_chars:
            cur += clause
        else:
            if cur:
                chunks.append(cur)
            cur = clause
    if cur:
        chunks.append(cur)
    return chunks


def _split_subtitles(text: str, duration_ms: int, max_chars: int = 36) -> list[dict]:
    segments: list[str] = []
    for sentence in _split_sentences(text):
        segments.extend(_chunk_sentence(sentence, max_chars))
    segments = [s.strip() for s in segments if s.strip()]
    if not segments:
        return [{"text": text, "start_ms": 0, "end_ms": duration_ms}]

    total_chars = sum(len(s) for s in segments) or 1
    lines = []
    offset_ms = 0
    for s in segments:
        ratio = len(s) / total_chars
        line_dur = int(duration_ms * ratio)
        lines.append({"text": s, "start_ms": offset_ms, "end_ms": offset_ms + line_dur})
        offset_ms += line_dur

    lines[-1]["end_ms"] = duration_ms
    return lines


def generate_srt(timeline: dict) -> str:
    srt_lines: list[str] = []
    idx = 1
    for entry in timeline["entries"]:
        base_ms = entry["start_ms"]
        for line in entry.get("subtitle_lines", []):
            start = _ms_to_srt_time(base_ms + line["start_ms"])
            end = _ms_to_srt_time(base_ms + line["end_ms"])
            srt_lines.append(f"{idx}\n{start} --> {end}\n{line['text']}\n")
            idx += 1
    return "\n".join(srt_lines)


def _ms_to_srt_time(ms: int) -> str:
    hours = ms // 3_600_000
    minutes = (ms % 3_600_000) // 60_000
    seconds = (ms % 60_000) // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
