def run_stage4(
    script: dict,
    scene_assets: list[dict],
    min_scene_ms: int = 2000,
    max_scene_ms: int = 15000,
) -> dict:
    narration_map = {s["id"]: s for s in script["scenes"]}
    entries: list[dict] = []
    current_ms = 0

    for asset in scene_assets:
        if "error" in asset and not asset.get("audio"):
            continue

        scene_id = asset["scene_id"]
        scene_data = narration_map.get(scene_id, {})

        audio_duration = 0
        if asset.get("audio"):
            audio_duration = asset["audio"].get("duration_ms", 0)

        hint_ms = int(scene_data.get("duration_hint", 5) * 1000)
        duration_ms = audio_duration if audio_duration > 0 else hint_ms
        duration_ms = max(min_scene_ms, min(duration_ms, max_scene_ms))

        entry = {
            "scene_id": scene_id,
            "start_ms": current_ms,
            "end_ms": current_ms + duration_ms,
            "image_path": asset.get("image", {}).get("file_path", ""),
            "audio_path": asset.get("audio", {}).get("file_path", ""),
            "audio_duration_ms": audio_duration,
            "subtitle_text": scene_data.get("narration", ""),
        }
        entries.append(entry)
        current_ms += duration_ms

    return {
        "entries": entries,
        "total_duration_ms": current_ms,
    }


def generate_srt(timeline: dict) -> str:
    lines: list[str] = []
    for i, entry in enumerate(timeline["entries"], 1):
        start = _ms_to_srt_time(entry["start_ms"])
        end = _ms_to_srt_time(entry["end_ms"])
        text = entry.get("subtitle_text", "")
        if text:
            lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def _ms_to_srt_time(ms: int) -> str:
    hours = ms // 3_600_000
    minutes = (ms % 3_600_000) // 60_000
    seconds = (ms % 60_000) // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
