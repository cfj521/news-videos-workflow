import re

from app.logging import get_logger

log = get_logger("stage4")


def run_stage4(
    script: dict,
    scene_assets: list[dict],
    min_scene_ms: int = 2000,
    max_scene_ms: int = 15000,
    scene_gap_ms: int = 500,
) -> dict:
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
        duration_ms = audio_duration if audio_duration > 0 else hint_ms
        duration_ms = max(min_scene_ms, min(duration_ms, max_scene_ms))
        duration_ms += scene_gap_ms

        narration = scene_data.get("narration", "")
        subtitle_lines = _split_subtitles(narration, duration_ms - scene_gap_ms)

        entry = {
            "scene_id": scene_id,
            "start_ms": current_ms,
            "end_ms": current_ms + duration_ms,
            "image_path": asset.get("image", {}).get("file_path", ""),
            "audio_path": asset.get("audio", {}).get("file_path", ""),
            "audio_duration_ms": audio_duration,
            "subtitle_text": narration,
            "subtitle_lines": subtitle_lines,
        }
        entries.append(entry)
        log.debug("S%d: %dms–%dms (%dms, %d subtitle lines)", scene_id, current_ms, current_ms + duration_ms, duration_ms, len(subtitle_lines))
        current_ms += duration_ms

    if skipped:
        log.warning("Skipped %d scenes due to errors", skipped)
    log.info("Timeline: %d entries, %.1fs total (gap=%dms)", len(entries), current_ms / 1000, scene_gap_ms)

    return {"entries": entries, "total_duration_ms": current_ms}


def _split_subtitles(text: str, duration_ms: int) -> list[dict]:
    sentences = re.split(r"(?<=[。！？；.!?;])", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return [{"text": text, "start_ms": 0, "end_ms": duration_ms}]

    total_chars = sum(len(s) for s in sentences)
    if total_chars == 0:
        return [{"text": text, "start_ms": 0, "end_ms": duration_ms}]

    lines = []
    offset_ms = 0
    for s in sentences:
        ratio = len(s) / total_chars
        line_dur = int(duration_ms * ratio)
        lines.append({"text": s, "start_ms": offset_ms, "end_ms": offset_ms + line_dur})
        offset_ms += line_dur

    if lines:
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
