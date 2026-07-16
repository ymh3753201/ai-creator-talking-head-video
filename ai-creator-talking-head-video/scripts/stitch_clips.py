#!/usr/bin/env python3
"""Validate, normalize, and stitch MP4 clips into one final talking-head video."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from _common import ScriptError, load_json, media_summary, require_ffmpeg, verify_media_file
from review_render import detect_silence, tail_silences


def collect_clips(project_dir: Path, explicit: list[str]) -> list[Path]:
    plan_path = project_dir / "generation-plan.json"
    if explicit:
        clips = [Path(item).expanduser().resolve() for item in explicit]
    elif plan_path.exists():
        plan = load_json(plan_path)
        clips = [Path(shot.get("clip_file") or project_dir / "clips" / f"{shot.get('id')}.mp4").expanduser().resolve() for shot in (plan.get("shots") or [])]
    else:
        clips = sorted((project_dir / "clips").glob("shot_*.mp4"))
    missing = [str(path) for path in clips if not path.exists()]
    if missing:
        raise ScriptError(f"missing expected clip(s): {missing}")
    if not clips:
        raise ScriptError("No clips found")
    return clips


def parse_fps(value: str | None) -> int:
    if not value:
        return 30
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            return max(1, round(float(num) / float(den)))
        return max(1, round(float(value)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 30


def resolve_target(clips: list[Path], target_resolution: str | None, target_fps: int | None) -> tuple[int, int, int]:
    first = media_summary(clips[0])
    video = first.get("video") or {}
    if target_resolution:
        width_s, height_s = target_resolution.lower().split("x", 1)
        width, height = int(width_s), int(height_s)
    else:
        width = int(video.get("width") or 1080)
        height = int(video.get("height") or 1920)
    fps = int(target_fps or parse_fps(video.get("fps")))
    return width, height, fps


def concat_escape(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")


def write_concat_list(path: Path, clips: list[Path]) -> None:
    path.write_text("".join(f"file '{concat_escape(clip)}'\n" for clip in clips), encoding="utf-8")


def run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        raise ScriptError(f"Command failed: {' '.join(cmd)}\n{exc.stderr[-1200:]}") from exc


def choose_tail_trim(
    duration: float,
    silences: list[dict],
    min_tail_silence: float,
    tail_padding: float,
    max_trim_seconds: float,
) -> dict:
    candidates = tail_silences(silences, duration, min_tail_silence)
    if not candidates:
        return {"applied": False, "trim_end_seconds": round(duration, 3), "trimmed_seconds": 0.0, "tail_silence": None}
    tail = candidates[-1]
    trim_end = min(duration, float(tail["start"]) + max(0.0, tail_padding))
    trimmed = max(0.0, duration - trim_end)
    if trimmed <= 0 or trimmed > max_trim_seconds:
        return {
            "applied": False,
            "trim_end_seconds": round(duration, 3),
            "trimmed_seconds": 0.0,
            "tail_silence": tail,
            "reason": "trim exceeds configured safety limit" if trimmed > max_trim_seconds else "nothing to trim",
        }
    return {
        "applied": True,
        "trim_end_seconds": round(trim_end, 3),
        "trimmed_seconds": round(trimmed, 3),
        "tail_silence": tail,
        "tail_padding_seconds": round(max(0.0, tail_padding), 3),
    }


def normalize_clip(src: Path, dest: Path, width: int, height: int, fps: int, crf: int, preset: str, trim_end_seconds: float | None = None) -> dict:
    summary = media_summary(src)
    has_audio = bool(summary.get("has_audio"))
    source_duration = max(float(summary.get("duration_seconds") or 0), 0.1)
    effective_duration = min(source_duration, float(trim_end_seconds or source_duration))
    vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p"
    cmd = ["ffmpeg", "-y", "-i", str(src)]
    if not has_audio:
        duration = max(float(summary.get("duration_seconds") or 0), 0.1)
        cmd.extend(["-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=44100:cl=stereo"])
    cmd.extend(["-map", "0:v:0"])
    cmd.extend(["-map", "0:a:0"] if has_audio else ["-map", "1:a:0"])
    cmd.extend([
        "-vf", vf,
        "-af", "aresample=44100:first_pts=0,asetpts=PTS-STARTPTS",
        "-t", f"{effective_duration:.3f}",
        "-r", str(fps),
        "-vsync", "cfr",
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        str(dest),
    ])
    run(cmd)
    return verify_media_file(dest, require_audio=True)


def concat_with_single_audio_encode(clips: list[Path], concat_list: Path, output: Path) -> None:
    write_concat_list(concat_list, clips)
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-map", "0:v:0", "-map", "0:a:0",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        str(output),
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--clips", nargs="*", default=[])
    parser.add_argument("--output")
    parser.add_argument("--target-resolution")
    parser.add_argument("--target-fps", type=int, default=30)
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--no-normalize", action="store_true")
    parser.add_argument("--auto-trim-tail-silence", action="store_true")
    parser.add_argument("--tail-silence-threshold-db", type=float, default=-35.0)
    parser.add_argument("--min-tail-silence", type=float, default=1.0)
    parser.add_argument("--tail-padding", type=float, default=0.25)
    parser.add_argument("--max-tail-trim", type=float, default=2.5)
    parser.add_argument("--require-audio", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        require_ffmpeg()
        project_dir = Path(args.project_dir).expanduser().resolve()
        clips = collect_clips(project_dir, args.clips)
        plan_path = project_dir / "generation-plan.json"
        plan = load_json(plan_path) if plan_path.exists() else {}
        stitch_plan = plan.get("stitching_plan") or {}
        output = Path(args.output).expanduser().resolve() if args.output else project_dir / "final.mp4"
        concat_list = project_dir / "concat-list.txt"
        temp_dir = project_dir / ".stitch_tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        target_resolution = args.target_resolution or stitch_plan.get("target_resolution")
        target_fps = args.target_fps or stitch_plan.get("target_fps")
        width, height, fps = resolve_target(clips, target_resolution, target_fps)
        report = {
            "clips": [str(clip) for clip in clips],
            "input_media": [media_summary(clip) for clip in clips],
            "concat_list": str(concat_list),
            "output": str(output),
            "target": {"width": width, "height": height, "fps": fps},
            "normalized": not args.no_normalize,
            "dry_run": bool(args.dry_run),
            "auto_trim_tail_silence": bool(args.auto_trim_tail_silence),
            "audio_boundary_policy": {
                "strategy": "source_preserved_one_shot" if args.no_normalize and len(clips) == 1 else "pcm_intermediates_single_final_aac_encode",
                "per_clip_fades_applied": False,
                "crossfade_applied": False,
                "single_final_aac_encode": not (args.no_normalize and len(clips) == 1),
                "rule": "Never fade or crossfade a segment head. Preserve the incoming first phoneme; use PCM normalized intermediates and encode AAC once after concatenation.",
            },
        }
        clip_edits = []
        for clip, summary in zip(clips, report["input_media"]):
            duration = float(summary.get("duration_seconds") or 0)
            if args.auto_trim_tail_silence and summary.get("has_audio"):
                silences = detect_silence(clip, args.tail_silence_threshold_db, min(0.4, args.min_tail_silence))
                decision = choose_tail_trim(duration, silences, args.min_tail_silence, args.tail_padding, args.max_tail_trim)
            else:
                decision = {"applied": False, "trim_end_seconds": round(duration, 3), "trimmed_seconds": 0.0, "tail_silence": None}
            clip_edits.append({"path": str(clip), **decision})
        report["clip_edits"] = clip_edits
        write_concat_list(concat_list, clips)
        if args.dry_run:
            print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
            return 0
        output.parent.mkdir(parents=True, exist_ok=True)
        if args.no_normalize:
            if any(item.get("applied") for item in clip_edits):
                raise ScriptError("Automatic tail trimming requires clip normalization")
            if len(clips) == 1:
                shutil.copy2(clips[0], output)
            else:
                concat_with_single_audio_encode(clips, concat_list, output)
        else:
            normalized = []
            normalized_reports = []
            for index, (clip, edit) in enumerate(zip(clips, clip_edits), start=1):
                dest = temp_dir / f"norm_{index:04d}.mkv"
                normalized_report = normalize_clip(clip, dest, width, height, fps, args.crf, args.preset, edit.get("trim_end_seconds"))
                normalized_report["source_path"] = str(clip)
                normalized_report["edit"] = edit
                normalized_report["head_fade_seconds"] = 0.0
                normalized_report["tail_fade_seconds"] = 0.0
                normalized_reports.append(normalized_report)
                normalized.append(dest)
            norm_concat_list = temp_dir / "concat-normalized.txt"
            concat_with_single_audio_encode(normalized, norm_concat_list, output)
            report["normalized_media"] = normalized_reports
            report["normalized_concat_list"] = str(norm_concat_list)
        media = verify_media_file(output, require_audio=args.require_audio)
        report["final_media"] = media
        report_file = output.with_suffix(".stitch-report.json")
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, **report, "report_file": str(report_file)}, ensure_ascii=False, indent=2))
        return 0
    except (ScriptError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
