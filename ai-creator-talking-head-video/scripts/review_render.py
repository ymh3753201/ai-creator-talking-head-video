#!/usr/bin/env python3
"""Review rendered talking-head MP4 output before delivery."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from _common import ScriptError, load_json, media_summary, require_ffmpeg, write_json
from subtitle_policy import is_confirmed_postproduction_subtitle_plan
from _workflow import sha256_file
from _routing import infer_execution_route


def run_ffmpeg(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise ScriptError(f"Required command not found: {cmd[0]}") from exc
    return f"{proc.stdout}\n{proc.stderr}"


def detect_silence(path: Path, threshold_db: float, min_duration: float) -> list[dict]:
    output = run_ffmpeg([
        "ffmpeg",
        "-hide_banner",
        "-i", str(path),
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
        "-f", "null",
        "-",
    ])
    silences = []
    current_start: float | None = None
    for line in output.splitlines():
        start_match = re.search(r"silence_start:\s*([0-9.]+)", line)
        if start_match:
            current_start = float(start_match.group(1))
        end_match = re.search(r"silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)", line)
        if end_match:
            end = float(end_match.group(1))
            duration = float(end_match.group(2))
            start = current_start if current_start is not None else max(0.0, end - duration)
            silences.append({"start": round(start, 3), "end": round(end, 3), "duration": round(duration, 3)})
            current_start = None
    return silences


def detect_freeze(path: Path, noise: float, min_duration: float) -> list[dict]:
    output = run_ffmpeg([
        "ffmpeg",
        "-hide_banner",
        "-i", str(path),
        "-vf", f"freezedetect=n={noise}:d={min_duration}",
        "-map", "0:v:0",
        "-f", "null",
        "-",
    ])
    freezes = []
    current_start: float | None = None
    for line in output.splitlines():
        start_match = re.search(r"freeze_start:\s*([0-9.]+)", line)
        if start_match:
            current_start = float(start_match.group(1))
        end_match = re.search(r"freeze_end:\s*([0-9.]+)\s*\|\s*freeze_duration:\s*([0-9.]+)", line)
        if end_match:
            end = float(end_match.group(1))
            duration = float(end_match.group(2))
            start = current_start if current_start is not None else max(0.0, end - duration)
            freezes.append({"start": round(start, 3), "end": round(end, 3), "duration": round(duration, 3)})
            current_start = None
    return freezes


def sample_frames(
    path: Path,
    duration: float,
    output_dir: Path,
    points: list[float] | None = None,
    prefix: str = "frame",
) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if duration <= 0:
        return []
    requested_points = points or [0.2, duration * 0.25, duration * 0.5, duration * 0.75, max(0.2, duration - 0.4)]
    points = sorted(set(round(max(0.05, min(duration - 0.05, item)), 2) for item in requested_points))
    frame_paths = []
    for index, second in enumerate(points, start=1):
        dest = output_dir / f"{prefix}_{index:02d}_{second:.2f}s.jpg"
        run_ffmpeg([
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-ss", f"{second:.2f}",
            "-i", str(path),
            "-frames:v", "1",
            "-q:v", "3",
            str(dest),
        ])
        if dest.exists() and dest.stat().st_size > 0:
            frame_paths.append(str(dest))
    return frame_paths


def collect_expected_clips(plan: dict) -> list[Path]:
    if infer_execution_route(plan) == "postproduction_only":
        return []
    clips = []
    for shot in plan.get("shots") or []:
        clip_file = shot.get("clip_file")
        if clip_file:
            clips.append(Path(clip_file).expanduser())
    return clips


def collect_review_clips(project_dir: Path, plan: dict, explicit: list[str]) -> tuple[list[Path], list[Path]]:
    expected = collect_expected_clips(plan)
    if explicit:
        clips = [Path(item).expanduser().resolve() for item in explicit]
    else:
        existing_expected = [path.resolve() for path in expected if path.exists()]
        clips = existing_expected or sorted((project_dir / "clips").glob("shot_*.mp4"))
    missing = [path for path in expected if not path.exists()]
    return clips, missing


def tail_silences(silences: list[dict], duration: float, min_tail: float) -> list[dict]:
    return [item for item in silences if item.get("duration", 0) >= min_tail and item.get("end", 0) >= duration - 0.25]


def detect_volume(path: Path, start: float, duration: float) -> dict:
    output = run_ffmpeg([
        "ffmpeg",
        "-hide_banner",
        "-ss", f"{max(0.0, start):.3f}",
        "-t", f"{max(0.1, duration):.3f}",
        "-i", str(path),
        "-vn",
        "-af", "volumedetect",
        "-f", "null",
        "-",
    ])
    mean_match = re.search(r"mean_volume:\s*([-\d.]+) dB", output)
    max_match = re.search(r"max_volume:\s*([-\d.]+) dB", output)
    return {
        "start": round(max(0.0, start), 3),
        "duration": round(max(0.1, duration), 3),
        "mean_volume_db": float(mean_match.group(1)) if mean_match else None,
        "max_volume_db": float(max_match.group(1)) if max_match else None,
    }


def summarize_clip_audio(clips: list[Path], threshold_db: float, min_silence: float, min_tail: float) -> list[dict]:
    result = []
    for clip in clips:
        item = {"path": str(clip), "exists": clip.exists()}
        if not clip.exists():
            result.append(item)
            continue
        summary = media_summary(clip)
        silences = detect_silence(clip, threshold_db, min_silence) if summary.get("has_audio") else []
        duration = float(summary.get("duration_seconds") or 0)
        item.update({
            "media": summary,
            "silences": silences,
            "tail_silences": tail_silences(silences, duration, min_tail),
        })
        result.append(item)
    return result


def classify_boundary_activity(context_volume: dict, guard_volume: dict, active_threshold_db: float) -> bool:
    context_mean = context_volume.get("mean_volume_db")
    context_max = context_volume.get("max_volume_db")
    guard_mean = guard_volume.get("mean_volume_db")
    guard_max = guard_volume.get("max_volume_db")
    return bool(
        context_mean is not None
        and context_max is not None
        and guard_mean is not None
        and guard_max is not None
        and context_mean > active_threshold_db
        and context_max > active_threshold_db
        and guard_mean > active_threshold_db
        and guard_max > active_threshold_db
    )


def boundary_audio_reviews(clip_reviews: list[dict], window: float, guard_window: float, active_threshold_db: float) -> list[dict]:
    reviews = []
    for index, item in enumerate(clip_reviews[:-1], start=1):
        path = Path(item.get("path", ""))
        media = item.get("media") or {}
        duration = float(media.get("duration_seconds") or 0)
        if not item.get("exists") or not media.get("has_audio") or duration <= 0:
            continue
        start = max(0.0, duration - window)
        volume = detect_volume(path, start, window)
        guard_duration = min(max(0.1, guard_window), duration)
        guard_volume = detect_volume(path, max(0.0, duration - guard_duration), guard_duration)
        has_tail_silence = bool(item.get("tail_silences"))
        active = classify_boundary_activity(volume, guard_volume, active_threshold_db) and not has_tail_silence
        reviews.append({
            "clip_index": index,
            "path": str(path),
            "window_seconds": window,
            "active_threshold_db": active_threshold_db,
            "volume": volume,
            "guard_window_seconds": guard_duration,
            "guard_volume": guard_volume,
            "has_tail_silence": has_tail_silence,
            "active_audio_at_stitch_boundary": active,
        })
    return reviews


def boundary_head_audio_reviews(
    video: Path,
    clips: list[Path],
    boundary_seconds: list[float],
    window: float,
    active_threshold_db: float,
    max_attenuation_db: float,
) -> list[dict]:
    reviews = []
    for index, boundary in enumerate(boundary_seconds, start=1):
        if index >= len(clips):
            break
        incoming = clips[index]
        if not incoming.exists() or not video.exists():
            continue
        incoming_media = media_summary(incoming)
        if not incoming_media.get("has_audio"):
            continue
        source_head = detect_volume(incoming, 0.0, window)
        final_head = detect_volume(video, boundary, window)
        source_mean = source_head.get("mean_volume_db")
        source_max = source_head.get("max_volume_db")
        final_mean = final_head.get("mean_volume_db")
        final_max = final_head.get("max_volume_db")
        source_head_active = bool(
            source_mean is not None
            and source_max is not None
            and source_mean > active_threshold_db
            and source_max > active_threshold_db
        )
        attenuation = (
            round(source_mean - final_mean, 2)
            if source_mean is not None and final_mean is not None
            else None
        )
        onset_preserved = bool(
            not source_head_active
            or (attenuation is not None and attenuation <= max_attenuation_db)
        )
        reviews.append({
            "incoming_clip_index": index + 1,
            "incoming_clip": str(incoming),
            "boundary_second": round(boundary, 3),
            "window_seconds": window,
            "source_head_volume": source_head,
            "final_head_volume": final_head,
            "source_head_active": source_head_active,
            "attenuation_db": attenuation,
            "max_allowed_attenuation_db": max_attenuation_db,
            "incoming_onset_preserved": onset_preserved,
        })
    return reviews


def boundary_type(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return "missing_script"
    if re.search(r"[。！？!?；;]$", cleaned):
        return "strong_sentence"
    if re.search(r"(第?[一二三四五六七八九十0-9]+|首先|其次|然后|最后|第一|第二|第三|第四|第五)[，,、：:]$", cleaned):
        return "open_enumerator"
    if re.search(r"[，,、：:]$", cleaned):
        return "weak_clause"
    return "no_terminal_punctuation"


def script_boundary_reviews(plan: dict) -> list[dict]:
    shots = plan.get("shots") or []
    reviews = []
    for index, shot in enumerate(shots, start=1):
        boundary = shot.get("script_boundary") or {}
        is_final = index >= len(shots)
        kind = boundary.get("boundary_type") or boundary_type(shot.get("script_segment") or "")
        stitch_safe = boundary.get("stitch_safe")
        if stitch_safe is None:
            stitch_safe = True if is_final else kind == "strong_sentence"
        issue = boundary.get("issue") or ""
        if not stitch_safe and not issue:
            issue = "Segment does not end on a clean sentence boundary."
        reviews.append({
            "shot_id": shot.get("id", f"shot_{index:02d}"),
            "segment_index": index,
            "is_final_segment": is_final,
            "boundary_type": kind,
            "stitch_safe": bool(stitch_safe),
            "issue": issue,
            "script_tail": (shot.get("script_segment") or "")[-40:],
        })
    return reviews


def collect_subtitle_delivery(project_dir: Path, video: Path, plan: dict) -> dict:
    subtitle_plan = plan.get("subtitle_plan") or {}
    if not subtitle_plan.get("enabled"):
        return {
            "required": False,
            "strategy": "default disabled",
            "subtitle_files": [],
            "burned_video_output": "",
            "burned_video_exists": False,
            "missing": False,
            "policy": "default_disabled_no_srt_no_burn",
        }
    confirmed = is_confirmed_postproduction_subtitle_plan(subtitle_plan)
    srt_raw = subtitle_plan.get("srt_output") or ""
    burned_raw = subtitle_plan.get("burned_video_output") or ""
    srt = Path(srt_raw).expanduser().resolve() if srt_raw else project_dir / "subtitles" / "final.srt"
    burned = Path(burned_raw).expanduser().resolve() if burned_raw else project_dir / "final.captioned.mp4"
    try:
        current_is_burned = video.expanduser().resolve() == burned
    except OSError:
        current_is_burned = False
    return {
        "required": True,
        "strategy": "platform-safe local postproduction captions",
        "subtitle_files": [str(srt)] if srt.exists() else [],
        "burned_video_output": str(burned),
        "burned_video_exists": burned.exists(),
        "current_video_is_burned_output": current_is_burned,
        "missing": not (confirmed and srt.is_file() and burned.is_file() and current_is_burned),
        "policy": "confirmed_postproduction_burn_only" if confirmed else "unconfirmed_subtitle_plan",
    }


def read_stitch_report(video: Path) -> dict:
    candidates = [video.with_suffix(".stitch-report.json")]
    raw_stem = video.stem
    for delivery_suffix in (".subtitled", ".captioned"):
        if raw_stem.endswith(delivery_suffix):
            raw_stem = raw_stem[: -len(delivery_suffix)]
            candidates.append(video.parent / f"{raw_stem}.stitch-report.json")
    candidates.append(video.parent / "final.stitch-report.json")
    for path in candidates:
        if path.exists():
            try:
                return {"path": str(path), "data": load_json(path)}
            except ScriptError as exc:
                return {"path": str(path), "error": str(exc)}
    return {"path": "", "error": "stitch report not found"}


def stitch_boundary_seconds(stitch_report: dict, plan: dict) -> list[float]:
    report_data = stitch_report.get("data") if isinstance(stitch_report.get("data"), dict) else {}
    media = report_data.get("normalized_media") or []
    durations = [float(item.get("duration_seconds") or 0) for item in media]
    if len(durations) < 2:
        durations = [float(shot.get("duration_seconds") or 0) for shot in (plan.get("shots") or [])]
    boundaries = []
    elapsed = 0.0
    for item in durations[:-1]:
        elapsed += item
        if elapsed > 0:
            boundaries.append(round(elapsed, 3))
    return boundaries


def choose_status(issues: list[str], critical: list[str]) -> str:
    if critical:
        return "fail"
    if issues:
        return "revise"
    return "pass"


def effective_duration_tolerance(expected_duration: float, absolute_tolerance: float, ratio_tolerance: float) -> float:
    return max(float(absolute_tolerance), float(expected_duration) * max(0.0, float(ratio_tolerance)))


MAX_DELIVERY_FRAME_ERROR_SECONDS = 0.04


def delivery_duration_hard_limit_error(actual_duration: float, delivery_max_seconds: float) -> str:
    if delivery_max_seconds > 0 and actual_duration > delivery_max_seconds + MAX_DELIVERY_FRAME_ERROR_SECONDS:
        return (
            f"delivery duration hard limit exceeded: output {actual_duration:.3f}s is above "
            f"delivery_max_seconds={delivery_max_seconds:.3f}s plus "
            f"{MAX_DELIVERY_FRAME_ERROR_SECONDS:.2f}s frame-measurement allowance"
        )
    return ""


def choose_action(issues: list[str]) -> str:
    joined = "\n".join(issues).lower()
    if "missing expected clip" in joined:
        return "wait_for_missing_clips"
    if "script boundary" in joined or "active audio at stitch boundary" in joined:
        return "rebalance_script_or_block_source_boundary"
    if "incoming head audio attenuation" in joined or "audio boundary policy" in joined:
        return "restitch_without_segment_fades"
    if "subtitle delivery missing" in joined:
        return "block_legacy_subtitle_plan"
    if "tail silence" in joined or "script pacing" in joined:
        return "trim_verified_idle_tail_or_block_source"
    if "duration mismatch" in joined or "stitch report" in joined:
        return "restitch"
    if "freeze" in joined:
        return "cut_locally_or_block_frozen_segment"
    return "present_to_user"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--plan")
    parser.add_argument("--video")
    parser.add_argument("--clips", nargs="*", default=[])
    parser.add_argument("--output")
    parser.add_argument("--silence-threshold-db", type=float, default=-35.0)
    parser.add_argument("--min-silence-duration", type=float, default=0.4)
    parser.add_argument("--min-tail-silence", type=float, default=1.0)
    parser.add_argument("--freeze-noise", type=float, default=0.003)
    parser.add_argument("--min-freeze-duration", type=float, default=1.0)
    parser.add_argument("--duration-tolerance", type=float, default=1.0)
    parser.add_argument("--duration-tolerance-ratio", type=float, default=0.05)
    parser.add_argument("--boundary-audio-window", type=float, default=0.6)
    parser.add_argument("--boundary-guard-window", type=float, default=0.2)
    parser.add_argument("--boundary-active-threshold-db", type=float, default=-40.0)
    parser.add_argument("--boundary-head-window", type=float, default=0.1)
    parser.add_argument("--max-boundary-head-attenuation-db", type=float, default=3.0)
    parser.add_argument("--allow-revise-exit-zero", action="store_true", help="Return exit code 0 for revise reports. Default is to fail automation unless the review status is pass.")
    parser.add_argument("--review-stage", choices=("delivery", "clean_provider"), default="delivery")
    parser.add_argument("--review-dir", help="Optional isolated frame-evidence directory for clean or captioned review stages.")
    args = parser.parse_args()

    try:
        require_ffmpeg()
        project_dir = Path(args.project_dir).expanduser().resolve()
        plan_path = Path(args.plan).expanduser().resolve() if args.plan else project_dir / "generation-plan.json"
        plan = load_json(plan_path) if plan_path.exists() else {}
        video = Path(args.video).expanduser().resolve() if args.video else project_dir / "final.mp4"
        output = Path(args.output).expanduser().resolve() if args.output else project_dir / "final-review.json"
        review_dir = Path(args.review_dir).expanduser().resolve() if args.review_dir else project_dir / "review"
        issues: list[str] = []
        critical: list[str] = []
        duration = 0.0
        expected_duration = float(
            plan.get("delivery_duration_seconds")
            or (plan.get("duration_plan") or {}).get("planned_duration_seconds")
            or plan.get("total_duration_seconds")
            or 0
        )
        duration_plan = plan.get("duration_plan") or {}
        delivery_max_seconds = float(duration_plan.get("delivery_max_seconds") or 0)
        flexible_duration = duration_plan.get("duration_tolerance") == "content_complete_flexible"
        minimum_expected_duration = float(duration_plan.get("estimated_script_seconds") or expected_duration or 0)

        if not video.exists():
            critical.append(f"output video not found: {video}")
            video_summary = None
            silences = []
            freezes = []
            frame_paths = []
        else:
            video_summary = media_summary(video)
            if not video_summary.get("has_video"):
                critical.append("output has no video stream")
            if not video_summary.get("has_audio"):
                issues.append("output has no audio stream")
            duration = float(video_summary.get("duration_seconds") or 0)
            hard_limit_error = delivery_duration_hard_limit_error(duration, delivery_max_seconds)
            if hard_limit_error:
                critical.append(hard_limit_error)
            allowed_duration_delta = effective_duration_tolerance(expected_duration, args.duration_tolerance, args.duration_tolerance_ratio)
            if flexible_duration:
                outside_range = (
                    duration < max(0.0, minimum_expected_duration - allowed_duration_delta)
                    or duration > expected_duration + allowed_duration_delta
                )
                if expected_duration and outside_range:
                    issues.append(
                        f"duration mismatch: output {duration:.2f}s vs flexible content-complete range "
                        f"{minimum_expected_duration:.2f}-{expected_duration:.2f}s"
                    )
            elif expected_duration and abs(duration - expected_duration) > allowed_duration_delta:
                issues.append(f"duration mismatch: output {duration:.2f}s vs expected {expected_duration:.2f}s")
            silences = detect_silence(video, args.silence_threshold_db, args.min_silence_duration) if video_summary.get("has_audio") else []
            final_tail_silences = tail_silences(silences, duration, args.min_tail_silence)
            if final_tail_silences:
                issues.append(f"tail silence detected in final output: {final_tail_silences}")
            freezes = detect_freeze(video, args.freeze_noise, args.min_freeze_duration)
            if freezes:
                issues.append(f"freeze detected in final output: {freezes}")
            frame_paths = sample_frames(video, duration, review_dir / "frames")

        clips, missing_clips = collect_review_clips(project_dir, plan, args.clips)
        if missing_clips:
            issues.append(f"missing expected clip(s): {[str(path) for path in missing_clips]}")
        clip_reviews = summarize_clip_audio(clips, args.silence_threshold_db, args.min_silence_duration, args.min_tail_silence)
        for item in clip_reviews:
            if item.get("tail_silences"):
                issues.append(f"tail silence detected in clip {item.get('path')}: {item.get('tail_silences')}")
        boundary_audio = boundary_audio_reviews(clip_reviews, args.boundary_audio_window, args.boundary_guard_window, args.boundary_active_threshold_db)
        for item in boundary_audio:
            if item.get("active_audio_at_stitch_boundary"):
                issues.append(f"active audio at stitch boundary in clip {item.get('path')}: {item.get('volume')}")

        expected_clip_count = 1 if infer_execution_route(plan) == "postproduction_only" else len(plan.get("shots") or [])
        if expected_clip_count and len(clips) != expected_clip_count:
            issues.append(f"clip count mismatch: found {len(clips)} clip(s), expected {expected_clip_count}")

        script_pacing = plan.get("script_pacing") or {}
        if script_pacing.get("status") and script_pacing.get("status") != "ok":
            issues.append(f"script pacing requires revision or a blocked delivery decision: {script_pacing.get('status')}")
        script_boundaries = script_boundary_reviews(plan)
        for item in script_boundaries:
            if not item.get("stitch_safe"):
                issues.append(f"script boundary not stitch-safe in {item.get('shot_id')}: {item.get('boundary_type')} ({item.get('script_tail')})")

        subtitle_delivery = collect_subtitle_delivery(project_dir, video, plan)
        if args.review_stage == "delivery" and subtitle_delivery.get("missing"):
            issues.append("subtitle delivery missing: no SRT/VTT file or burned-in captioned output was found")

        stitch_report = read_stitch_report(video)
        if expected_clip_count > 1 and stitch_report.get("error"):
            issues.append(f"stitch report issue: {stitch_report.get('error')}")
        boundary_seconds = stitch_boundary_seconds(stitch_report, plan) if video.exists() else []
        stitch_report_data = stitch_report.get("data") if isinstance(stitch_report.get("data"), dict) else {}
        audio_boundary_policy = stitch_report_data.get("audio_boundary_policy") or {}
        if expected_clip_count > 1 and not stitch_report.get("error"):
            if audio_boundary_policy.get("per_clip_fades_applied") is not False:
                issues.append("audio boundary policy is unsafe or missing: per-clip fades must be explicitly disabled")
            if audio_boundary_policy.get("single_final_aac_encode") is not True:
                issues.append("audio boundary policy is unsafe or missing: multi-clip audio must use one final AAC encode")
        boundary_head_audio = boundary_head_audio_reviews(
            video,
            clips,
            boundary_seconds,
            args.boundary_head_window,
            args.boundary_active_threshold_db,
            args.max_boundary_head_attenuation_db,
        ) if video.exists() else []
        for item in boundary_head_audio:
            if not item.get("incoming_onset_preserved"):
                issues.append(
                    f"incoming head audio attenuation at boundary {item.get('boundary_second')}s for "
                    f"{item.get('incoming_clip')}: {item.get('attenuation_db')}dB exceeds "
                    f"{item.get('max_allowed_attenuation_db')}dB"
                )
        boundary_points = [point for boundary in boundary_seconds for point in (boundary - 0.2, boundary + 0.2)]
        boundary_frame_paths = sample_frames(
            video,
            duration,
            review_dir / "boundary-frames",
            points=boundary_points,
            prefix="boundary",
        ) if video.exists() and boundary_points else []

        status = choose_status(issues, critical)
        result = {
            "version": "1.0",
            "project_dir": str(project_dir),
            "plan": str(plan_path),
            "output_path": str(video),
            "output_sha256": sha256_file(video) if video.exists() and video.is_file() else "",
            "status": status,
            "recommended_action": "block" if status == "fail" else choose_action(issues),
            "checks": {
                "technical_probe": {
                    "valid_container": bool(video_summary and video_summary.get("has_video")),
                    "media": video_summary,
                    "expected_duration_seconds": expected_duration,
                    "minimum_content_complete_seconds": minimum_expected_duration,
                    "delivery_max_seconds": delivery_max_seconds,
                    "delivery_max_frame_error_seconds": MAX_DELIVERY_FRAME_ERROR_SECONDS,
                    "delivery_hard_limit_pass": not bool(delivery_duration_hard_limit_error(duration, delivery_max_seconds)),
                    "duration_tolerance_mode": duration_plan.get("duration_tolerance") or "strict_target",
                    "allowed_duration_delta_seconds": round(effective_duration_tolerance(expected_duration, args.duration_tolerance, args.duration_tolerance_ratio), 3),
                    "issues": [
                        item for item in critical + issues
                        if "duration mismatch" in item or "hard limit" in item or "no video" in item or "no audio" in item
                    ],
                },
                "visual_spotcheck": {
                    "frames_sampled": len(frame_paths),
                    "frame_paths": frame_paths,
                    "stitch_boundary_seconds": boundary_seconds,
                    "boundary_frame_paths": boundary_frame_paths,
                    "freezes": freezes,
                    "issues": [item for item in issues if "freeze" in item],
                },
                "audio_spotcheck": {
                    "silence_threshold_db": args.silence_threshold_db,
                    "min_silence_duration": args.min_silence_duration,
                    "silences": silences,
                    "clip_reviews": clip_reviews,
                    "boundary_audio_reviews": boundary_audio,
                    "incoming_head_audio_reviews": boundary_head_audio,
                    "audio_boundary_policy": audio_boundary_policy,
                    "unexpected_silence": any(item.get("tail_silences") for item in clip_reviews) or any("tail silence" in item for item in issues),
                    "active_audio_at_stitch_boundary": any(item.get("active_audio_at_stitch_boundary") for item in boundary_audio),
                    "incoming_onset_preserved": all(item.get("incoming_onset_preserved") for item in boundary_head_audio),
                    "issues": [item for item in issues if "silence" in item or "active audio" in item or "incoming head" in item or "audio boundary policy" in item],
                },
                "stitching_check": {
                    "expected_clip_count": expected_clip_count,
                    "found_clip_count": len(clips),
                    "clips": [str(path) for path in clips],
                    "missing_clips": [str(path) for path in missing_clips],
                    "stitch_report": stitch_report,
                    "issues": [item for item in issues if "clip" in item or "stitch" in item],
                },
                "script_pacing_check": {
                    "script_pacing": script_pacing,
                    "issues": [item for item in issues if "script pacing" in item],
                },
                "script_boundary_check": {
                    "boundaries": script_boundaries,
                    "issues": [item for item in issues if "script boundary" in item],
                },
                "subtitle_check": {
                    **subtitle_delivery,
                    "issues": [item for item in issues if "subtitle" in item],
                },
            },
            "issues_found": critical + issues,
        }
        write_json(output, result)
        print(json.dumps({"ok": status == "pass", "status": status, "recommended_action": result["recommended_action"], "review": str(output), "issues_found": result["issues_found"]}, ensure_ascii=False, indent=2))
        return 0 if status == "pass" or (status == "revise" and args.allow_revise_exit_zero) else 1
    except ScriptError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
