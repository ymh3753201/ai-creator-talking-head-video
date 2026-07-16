#!/usr/bin/env python3
"""Generate an SRT subtitle file from a talking-head generation plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from _common import ScriptError, load_json, media_summary, require_ffmpeg, write_json
from subtitle_policy import enabled_subtitle_contract_errors
from subtitle_runtime import resolved_subtitle_runtime, subtitle_runtime_errors


CJK_SOFT_BOUNDARIES = (
    "我们会",
    "并形成",
    "并明确",
    "先判断",
    "再决定",
    "最后",
    "首先",
    "其次",
    "然后",
    "不是",
    "而是",
    "而要",
    "同时",
    "另外",
    "帮助",
    "先看",
    "再看",
    "下次",
    "减少",
    "或者",
    "并且",
)


def visible_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def hard_split_text(text: str, max_chars: int) -> list[str]:
    chunks = []
    current = ""
    for char in text:
        if current and visible_length(current + char) > max_chars:
            chunks.append(current)
            current = char
        else:
            current += char
    if current:
        chunks.append(current)
    return chunks


def split_cjk_on_soft_boundaries(text: str, max_chars: int) -> list[str]:
    positions = {0, len(text)}
    for marker in CJK_SOFT_BOUNDARIES:
        start = 0
        while True:
            index = text.find(marker, start)
            if index < 0:
                break
            if index > 0:
                positions.add(index)
            start = index + len(marker)
    ordered = sorted(positions)
    phrases = [text[start:end] for start, end in zip(ordered, ordered[1:]) if text[start:end]]
    chunks: list[str] = []
    current = ""
    for phrase in phrases:
        pieces = hard_split_text(phrase, max_chars) if visible_length(phrase) > max_chars else [phrase]
        for piece in pieces:
            candidate = current + piece
            if current and visible_length(candidate) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def split_oversized_unit(text: str, max_chars: int) -> list[str]:
    if max_chars <= 0 or visible_length(text) <= max_chars:
        return [text]
    if not re.search(r"[\u4e00-\u9fff]", text):
        words = text.split()
        if len(words) > 1:
            chunks: list[str] = []
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if current and visible_length(candidate) > max_chars:
                    chunks.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                chunks.append(current)
            return chunks

    chunks = split_cjk_on_soft_boundaries(text, max_chars)
    if len(chunks) > 1 and visible_length(chunks[-1]) == 1 and re.fullmatch(r"[。！？!?；;，,、]", chunks[-1]):
        punctuation = chunks.pop()
        previous = chunks.pop()
        chunks.extend([previous[:-1], previous[-1:] + punctuation] if len(previous) > 1 else [previous + punctuation])
    return [item for item in chunks if item]


def split_caption_units(text: str, max_chars: int) -> list[str]:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return []
    units = [item.strip() for item in re.findall(r"[^。！？!?；;，,、\n]+[。！？!?；;，,、]?", cleaned) if item.strip()]
    captions: list[str] = []
    current = ""
    expanded_units = [piece for unit in (units or [cleaned]) for piece in split_oversized_unit(unit, max_chars)]
    for unit in expanded_units:
        next_text = f"{current}{unit}".strip()
        if current and visible_length(next_text) > max_chars:
            captions.append(current.strip())
            current = unit
        else:
            current = next_text
        if current and re.search(r"[。！？!?；;]$", current) and visible_length(current) >= max_chars * 0.55:
            captions.append(current.strip())
            current = ""
    if current.strip():
        captions.append(current.strip())
    return captions


def srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def caption_weight(text: str) -> int:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z0-9']+", text))
    return max(1, cjk + words * 2)


def _timestamp_seconds(value: str) -> float:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", value.strip())
    if not match:
        raise ScriptError(f"Invalid SRT timestamp: {value}")
    hours, minutes, seconds, millis = (int(item) for item in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def parse_srt_entries(text: str) -> list[dict]:
    entries: list[dict] = []
    for block in re.split(r"\r?\n\s*\r?\n", text.strip().lstrip("\ufeff")):
        lines = [line.rstrip() for line in block.splitlines()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_raw, end_raw = [item.strip() for item in lines[1].split("-->", 1)]
        caption = "".join(line.strip() for line in lines[2:] if line.strip())
        if caption:
            entries.append({
                "start": _timestamp_seconds(start_raw),
                "end": _timestamp_seconds(end_raw),
                "text": caption,
                "display_text": "\n".join(line.strip() for line in lines[2:] if line.strip()),
            })
    if not entries:
        raise ScriptError("SRT contains no valid subtitle entries.")
    return entries


def normalize_srt_for_profile(text: str, profile: dict) -> str:
    """Wrap and time-split SRT entries so one cue never exceeds the platform profile."""
    normalized: list[dict] = []
    max_lines = max(1, int(profile.get("max_lines") or 2))
    for source in parse_srt_entries(text):
        has_cjk = bool(re.search(r"[\u3400-\u9fff]", source["text"]))
        max_chars = int(
            profile.get("max_chars_zh_per_line" if has_cjk else "max_chars_latin_per_line")
            or (16 if has_cjk else 34)
        )
        units = split_caption_units(source["text"], max_chars) or [source["text"]]
        groups = [units[index:index + max_lines] for index in range(0, len(units), max_lines)]
        weights = [sum(caption_weight(line) for line in group) for group in groups]
        total_weight = sum(weights) or len(groups)
        cursor = float(source["start"])
        available = max(0.05, float(source["end"]) - cursor)
        for index, (group, weight) in enumerate(zip(groups, weights)):
            end = float(source["end"]) if index == len(groups) - 1 else cursor + available * weight / total_weight
            normalized.append({
                "index": len(normalized) + 1,
                "start": round(cursor, 3),
                "end": round(max(cursor + 0.05, end), 3),
                "text": "\n".join(group),
            })
            cursor = end
    blocks = [
        f"{entry['index']}\n{srt_time(entry['start'])} --> {srt_time(entry['end'])}\n{entry['text']}\n"
        for entry in normalized
    ]
    return "\n".join(blocks)


def confirmed_script_srt(
    script_text: str,
    start_second: float,
    end_second: float,
    profile: dict,
    timing_entries: list[dict] | None = None,
) -> str:
    """Build caption text from the confirmed script inside the final-audio timing range."""
    cleaned = re.sub(r"\s+", " ", (script_text or "").strip())
    if not cleaned:
        raise ScriptError("Confirmed script text is empty; it cannot be used as the subtitle lexical source.")
    start = max(0.0, float(start_second))
    end = float(end_second)
    if end <= start:
        raise ScriptError("Final-audio timing range is invalid for confirmed-script subtitles.")
    has_cjk = bool(re.search(r"[\u3400-\u9fff]", cleaned))
    max_chars = int(
        profile.get("max_chars_zh_per_line" if has_cjk else "max_chars_latin_per_line")
        or (16 if has_cjk else 34)
    )
    units = split_caption_units(cleaned, max_chars)
    if timing_entries and len(units) == len(timing_entries):
        return "\n".join(
            f"{index}\n{srt_time(float(timing['start']))} --> {srt_time(float(timing['end']))}\n{unit}\n"
            for index, (unit, timing) in enumerate(zip(units, timing_entries), start=1)
        )
    seed = f"1\n{srt_time(start)} --> {srt_time(end)}\n{cleaned}\n"
    return normalize_srt_for_profile(seed, profile)


def confirmed_script_text(plan: dict) -> str:
    direct = re.sub(r"\s+", " ", str(plan.get("script_text") or "").strip())
    if direct:
        return direct
    segments = [
        re.sub(r"\s+", " ", str(shot.get("script_segment") or "").strip())
        for shot in (plan.get("shots") or [])
        if str(shot.get("script_segment") or "").strip()
    ]
    return " ".join(segments).strip()


def clamp_srt_to_duration(text: str, duration_seconds: float) -> str:
    """Clamp local-ASR cue tails to the exact verified video duration."""
    limit = max(0.0, float(duration_seconds))
    clamped: list[dict] = []
    for source in parse_srt_entries(text):
        start = float(source["start"])
        if start >= limit:
            continue
        end = min(float(source["end"]), limit)
        if end <= start:
            continue
        clamped.append({
            "index": len(clamped) + 1,
            "start": start,
            "end": end,
            "text": source.get("display_text") or source["text"],
        })
    if not clamped:
        raise ScriptError("Subtitle timeline has no cue inside the verified video duration.")
    return "\n".join(
        f"{entry['index']}\n{srt_time(entry['start'])} --> {srt_time(entry['end'])}\n{entry['text']}\n"
        for entry in clamped
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def last_srt_end_seconds(text: str) -> float:
    matches = re.findall(r"-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", text)
    if not matches:
        raise ScriptError("SRT contains no valid subtitle timestamp.")
    hours, minutes, seconds, millis = matches[-1]
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def confirmed_subtitle_plan(plan: dict) -> dict:
    subtitle_plan = plan.get("subtitle_plan") or {}
    if not subtitle_plan.get("enabled"):
        raise ScriptError("Postproduction subtitles are disabled for this confirmed plan.")
    errors = enabled_subtitle_contract_errors(subtitle_plan, prefix="Subtitle generation")
    if errors:
        raise ScriptError(" ".join(errors))
    return subtitle_plan


def transcribe_with_whisper(video: Path, runtime: dict, language: str, output: Path) -> Path:
    require_ffmpeg()
    with tempfile.TemporaryDirectory(prefix="talking-head-subtitles-") as tmp:
        tmp_dir = Path(tmp)
        audio = tmp_dir / "final-audio.wav"
        extract = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
                "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if extract.returncode != 0:
            raise ScriptError(f"Final-audio extraction failed: {extract.stderr.strip()}")
        prefix = tmp_dir / "transcript"
        command = [
            runtime["whisper_executable"],
            "-m", runtime["whisper_model"],
            "-f", str(audio),
            "-l", str(language or "auto").split("-")[0],
            "-osrt", "-of", str(prefix),
        ]
        proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        generated = prefix.with_suffix(".srt")
        if proc.returncode != 0 or not generated.exists():
            detail = (proc.stderr or proc.stdout).strip()
            raise ScriptError(f"Local whisper.cpp transcription failed: {detail}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(generated.read_bytes())
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--video", required=True, help="Verified clean final MP4 whose final audio controls subtitle timing.")
    parser.add_argument("--output")
    parser.add_argument("--whisper-model")
    parser.add_argument("--whisper-cli")
    args = parser.parse_args()
    try:
        plan_path = Path(args.plan).expanduser().resolve()
        plan = load_json(plan_path)
        subtitle_plan = confirmed_subtitle_plan(plan)
        if args.whisper_model:
            subtitle_plan["whisper_model"] = args.whisper_model
        if args.whisper_cli:
            subtitle_plan["whisper_executable"] = args.whisper_cli
        plan["subtitle_plan"] = subtitle_plan
        errors = subtitle_runtime_errors(plan)
        if errors:
            raise ScriptError(" ".join(errors))
        video = Path(args.video).expanduser().resolve()
        if not video.is_file():
            raise ScriptError(f"Verified clean video not found: {video}")
        video_summary = media_summary(video)
        output = Path(args.output or subtitle_plan.get("srt_output") or plan_path.parent / "subtitles" / "generated.srt").expanduser().resolve()
        runtime = resolved_subtitle_runtime(plan)
        timing_source = runtime["timing_source"]
        lexical_source = "provided_srt"
        raw_asr_path: Path | None = None
        raw_asr_sha256 = ""
        raw_asr_cue_count = 0
        audio_cue_alignment_used = False
        if timing_source == "provided_srt":
            supplied = Path(runtime["input_subtitle"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(supplied.read_bytes())
            text = normalize_srt_for_profile(
                output.read_text(encoding="utf-8-sig"),
                subtitle_plan.get("profile") or {},
            )
        else:
            raw_asr_path = Path(
                subtitle_plan.get("raw_asr_output") or output.parent / "final.raw-asr.srt"
            ).expanduser().resolve()
            transcribe_with_whisper(
                video,
                runtime,
                str(plan.get("language") or subtitle_plan.get("language") or "auto"),
                raw_asr_path,
            )
            raw_text = raw_asr_path.read_text(encoding="utf-8-sig")
            raw_entries = parse_srt_entries(raw_text)
            raw_asr_cue_count = len(raw_entries)
            raw_asr_sha256 = file_sha256(raw_asr_path)
            script_text = confirmed_script_text(plan)
            if script_text:
                text = confirmed_script_srt(
                    script_text,
                    start_second=float(raw_entries[0]["start"]),
                    end_second=float(raw_entries[-1]["end"]),
                    profile=subtitle_plan.get("profile") or {},
                    timing_entries=raw_entries,
                )
                lexical_source = "confirmed_script"
                audio_cue_alignment_used = len(parse_srt_entries(text)) == len(raw_entries)
            else:
                text = normalize_srt_for_profile(raw_text, subtitle_plan.get("profile") or {})
                lexical_source = "local_whisper_cpp"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        last_end = last_srt_end_seconds(text)
        duration = float(video_summary.get("duration_seconds") or 0)
        tail_clamped = False
        if duration > 0 and last_end > duration + 0.1:
            if timing_source != "local_whisper_cpp":
                raise ScriptError(
                    f"Provided subtitle timeline ends at {last_end:.3f}s, beyond the verified clean video duration {duration:.3f}s."
                )
            text = clamp_srt_to_duration(text, duration)
            output.write_text(text, encoding="utf-8")
            last_end = last_srt_end_seconds(text)
            tail_clamped = True
        audit_path = Path(
            subtitle_plan.get("subtitle_audit_output") or output.with_suffix(".audit.json")
        ).expanduser().resolve()
        audit = {
            "ok": True,
            "timing_source": timing_source,
            "lexical_source": lexical_source,
            "video": str(video),
            "video_sha256": file_sha256(video),
            "video_duration_seconds": duration,
            "subtitle": str(output),
            "subtitle_sha256": file_sha256(output),
            "subtitle_last_end_seconds": last_end,
            "local_asr_tail_clamped_to_video_duration": tail_clamped,
            "raw_asr": str(raw_asr_path) if raw_asr_path else "",
            "raw_asr_sha256": raw_asr_sha256,
            "raw_asr_cue_count": raw_asr_cue_count,
            "final_subtitle_cue_count": len(parse_srt_entries(text)),
            "audio_cue_alignment_used": audio_cue_alignment_used,
            "whisper_executable": runtime["whisper_executable"] if timing_source == "local_whisper_cpp" else "",
            "whisper_model": runtime["whisper_model"] if timing_source == "local_whisper_cpp" else "",
            "provider_payload_used": False,
            "paid_api_call": False,
        }
        write_json(audit_path, audit)
        print(json.dumps({**audit, "audit": str(audit_path)}, ensure_ascii=False, indent=2))
        return 0
    except (ScriptError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
