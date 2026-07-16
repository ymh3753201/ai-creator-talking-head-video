#!/usr/bin/env python3
"""Finalize a verified project and release it only when every delivery gate passes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from _common import ScriptError, load_json, media_summary
from _workflow import atomic_write_json, canonical_digest, sha256_file, verify_contract
from review_render import MAX_DELIVERY_FRAME_ERROR_SECONDS, delivery_duration_hard_limit_error
from subtitle_policy import is_confirmed_postproduction_subtitle_plan


SCRIPT_DIR = Path(__file__).resolve().parent
BASE_VISUAL_FIELDS = (
    "identity_consistent",
    "outfit_consistent",
    "scene_consistent",
    "framing_consistent",
    "lip_sync_acceptable",
    "mouth_visible",
    "no_unapproved_visual_insert",
    "no_generated_text",
    "spoken_content_complete",
)
SUBTITLE_VISUAL_FIELDS = (
    "subtitle_present",
    "subtitle_postproduced",
    "subtitle_safe",
    "subtitle_readable",
    "subtitle_matches_speech",
    "subtitle_background_absent",
    "no_unapproved_text",
)
ACCEPTED_REVIEW_STATUSES = {"pass", "pass_with_notes"}
SPEECH_FIDELITY_MODES = {"semantic_tolerance", "critical_facts_exact", "verbatim_required"}
PAYLOAD_IMAGE_ROLES = {"avatar_reference", "video_source", "first_frame", "segment_source"}


def run_worker(args: list[str]) -> tuple[int, dict, str]:
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        data = {}
    return result.returncode, data, result.stderr


def subtitles_disabled(plan: dict) -> bool:
    subtitle_plan = plan.get("subtitle_plan") or {}
    return not bool(subtitle_plan.get("enabled", True))


def confirmed_postproduction_subtitles(plan: dict) -> bool:
    return is_confirmed_postproduction_subtitle_plan(plan)


def should_use_original_single_clip(plan: dict, clips: list[Path]) -> bool:
    stitch_plan = plan.get("stitching_plan") or {}
    effects_plan = plan.get("effects_plan") or {}
    return bool(
        len(clips) == 1
        and subtitles_disabled(plan)
        and not effects_plan.get("enabled", False)
        and not stitch_plan.get("required", False)
        and not stitch_plan.get("auto_trim_tail_silence", False)
    )


def should_auto_trim_tail_silence(plan: dict) -> bool:
    stitch_plan = plan.get("stitching_plan") or {}
    configured = stitch_plan.get("auto_trim_tail_silence")
    if configured is not None:
        return bool(configured)
    intake = plan.get("intake_route") or {}
    speech_source = str(intake.get("speech_source") or "model_generated")
    return plan.get("content_mode") == "avatar_talking_head" and speech_source not in {"external_audio", "existing_video_audio"}


def _review_evidence_path(value, base_dir: Path | None) -> Path | None:
    raw = value.get("path") if isinstance(value, dict) else value
    if not str(raw or "").strip():
        return None
    path = Path(str(raw)).expanduser()
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path.resolve()


def visual_review_errors(
    review: dict,
    final_video: Path | None = None,
    final_digest: str = "",
    expected_boundaries: int = 0,
    expected_segments: int = 1,
    subtitles_enabled: bool = True,
    expected_speech_fidelity_mode: str = "",
) -> list[str]:
    errors = []
    if review.get("status") not in ACCEPTED_REVIEW_STATUSES:
        errors.append(f"visual review status is {review.get('status') or 'missing'}")
    required_fields = BASE_VISUAL_FIELDS + (SUBTITLE_VISUAL_FIELDS if subtitles_enabled else ())
    for field in required_fields:
        if review.get(field) is not True:
            errors.append(f"visual review field {field} is not true")
    reviewed_frames = review.get("reviewed_frames") or []
    if not reviewed_frames:
        errors.append("visual review has no reviewed_frames evidence")
    base_dir = final_video.parent if final_video is not None else None
    for item in reviewed_frames:
        path = _review_evidence_path(item, base_dir)
        if path is None or not path.exists():
            errors.append(f"visual review frame evidence is missing: {item}")
    boundary_frames = review.get("reviewed_boundary_frames") or []
    if expected_boundaries and len(boundary_frames) < expected_boundaries * 2:
        errors.append(f"visual review needs before/after boundary frame evidence for {expected_boundaries} stitch boundary(s)")
    for item in boundary_frames:
        path = _review_evidence_path(item, base_dir)
        if path is None or not path.exists():
            errors.append(f"visual review boundary frame evidence is missing: {item}")
    speech_evidence = review.get("speech_evidence") or {}
    speech_status = str(speech_evidence.get("status") or "")
    if speech_status not in ACCEPTED_REVIEW_STATUSES:
        errors.append(f"speech evidence status is {speech_evidence.get('status') or 'missing'}")
    if not str(speech_evidence.get("method") or "").strip():
        errors.append("speech evidence method is missing")
    transcript = str(speech_evidence.get("transcript") or "").strip()
    if not transcript:
        errors.append("speech evidence transcript is missing")
    else:
        transcript_path = _review_evidence_path(transcript, base_dir)
        if transcript_path is None or not transcript_path.exists():
            errors.append("speech evidence transcript file is missing")
    segments_reviewed = speech_evidence.get("segments_reviewed") or []
    if len(segments_reviewed) < max(1, expected_segments):
        errors.append(f"speech evidence covers {len(segments_reviewed)} segment(s), expected {max(1, expected_segments)}")
    for field in ("pronunciation_acceptable", "voice_consistent", "volume_consistent"):
        if speech_evidence.get(field) is not True:
            errors.append(f"speech evidence field {field} is not true")
    fidelity_mode = str(speech_evidence.get("speech_fidelity_mode") or "")
    if fidelity_mode and fidelity_mode not in SPEECH_FIDELITY_MODES:
        errors.append(f"unsupported speech_fidelity_mode: {fidelity_mode}")
    if expected_speech_fidelity_mode and fidelity_mode != expected_speech_fidelity_mode:
        errors.append(
            "speech evidence fidelity mode does not match the confirmed plan: "
            f"expected {expected_speech_fidelity_mode}, got {fidelity_mode or 'missing'}"
        )
    minor_discrepancies = speech_evidence.get("minor_discrepancies") or []
    material_discrepancies = speech_evidence.get("material_discrepancies") or []
    if material_discrepancies:
        errors.append("speech evidence has material speech discrepancies")
    if minor_discrepancies and speech_status != "pass_with_notes":
        errors.append("minor speech discrepancies require speech evidence status pass_with_notes")
    if speech_status == "pass_with_notes":
        if fidelity_mode not in SPEECH_FIDELITY_MODES:
            errors.append("pass_with_notes speech evidence requires a valid speech_fidelity_mode")
        for field in ("critical_terms_preserved", "core_facts_preserved", "meaning_preserved", "intelligibility_acceptable"):
            if speech_evidence.get(field) is not True:
                errors.append(f"pass_with_notes speech evidence field {field} is not true")
        if str(speech_evidence.get("asr_consensus") or "") not in {"stable", "uncertain", "not_used"}:
            errors.append("pass_with_notes speech evidence requires asr_consensus")
        if not minor_discrepancies:
            errors.append("pass_with_notes speech evidence requires at least one structured minor_discrepancy")
        for index, item in enumerate(minor_discrepancies, start=1):
            if not isinstance(item, dict):
                errors.append(f"minor speech discrepancy {index} must be an object")
                continue
            if item.get("severity") != "minor":
                errors.append(f"minor speech discrepancy {index} must have severity=minor")
            if item.get("affects_core_fact") is not False:
                errors.append(f"minor speech discrepancy {index} must not affect a core fact")
            if item.get("affects_meaning") is not False:
                errors.append(f"minor speech discrepancy {index} must not affect meaning")
        if fidelity_mode == "verbatim_required" and minor_discrepancies:
            errors.append("speech_fidelity_mode=verbatim_required does not allow minor wording or pronunciation discrepancies")
    if speech_evidence.get("unresolved_discrepancies"):
        errors.append("speech evidence has unresolved discrepancies")
    if speech_evidence.get("strict_frame_accurate_external_audio_alignment_claimed") and not speech_evidence.get("frame_accurate_alignment_evidence"):
        errors.append("strict frame-accurate external-audio alignment was claimed without evidence")
    if final_video is not None:
        reviewed_video = review.get("reviewed_video") or {}
        reviewed_path = str(reviewed_video.get("path") or "")
        reviewed_digest = str(reviewed_video.get("sha256") or "")
        if not reviewed_path or not reviewed_digest:
            errors.append("visual review has no reviewed video path and sha256 binding")
        else:
            try:
                if Path(reviewed_path).expanduser().resolve() != final_video.resolve():
                    errors.append("visual review reviewed video path does not match the current final video")
            except OSError:
                errors.append("visual review reviewed video path is invalid")
            if reviewed_digest != final_digest:
                errors.append("visual review reviewed video sha256 does not match the current final video")
    return errors


def write_blocked(
    project_dir: Path,
    issues: list[str],
    checks: dict | None = None,
    current_postprocess_manifest: Path | None = None,
) -> int:
    delivery_manifest = project_dir / "delivery-manifest.json"
    if delivery_manifest.exists():
        delivery_manifest.unlink()
    report = {"status": "blocked", "issues": issues, "checks": checks or {}, "updated_at": int(time.time())}
    if current_postprocess_manifest is not None and current_postprocess_manifest.exists():
        report["postprocess_manifest"] = str(current_postprocess_manifest)
    atomic_write_json(project_dir / "finalize-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1


def artifact_entry(path: Path | None) -> dict:
    if path is None:
        return {"path": "", "sha256": ""}
    resolved = path.expanduser().resolve()
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved) if resolved.exists() and resolved.is_file() else "",
    }


def paid_generation_ledger_errors(jobs: dict, base_paid_request_count: int) -> list[str]:
    errors = []
    maximum = int(jobs.get("max_paid_submissions") or 0)
    attempts = int(jobs.get("paid_submission_attempts") or 0)
    if maximum != base_paid_request_count:
        errors.append(
            f"max_paid_submissions={maximum} must equal the {base_paid_request_count} base paid request(s)"
        )
    if attempts != base_paid_request_count:
        errors.append(
            f"paid_submission_attempts={attempts} must equal the {base_paid_request_count} base paid request(s)"
        )
    for shot_id, job in (jobs.get("jobs") or {}).items():
        submission_attempts = int(job.get("submission_attempts") or 0)
        repair_attempts = int(job.get("repair_submission_attempts") or 0)
        if str(job.get("state") or "") == "verified" and submission_attempts != 1:
            errors.append(f"verified job {shot_id} must have submission_attempts=1, got {submission_attempts}")
        if str(job.get("state") or "") == "verified" and not str(job.get("request_id") or "").strip():
            errors.append(f"verified job {shot_id} is missing request_id")
        if repair_attempts > 0:
            errors.append(f"job {shot_id} has {repair_attempts} paid repair submission(s)")
        reasons = [str(job.get("last_submission_reason") or "")]
        reasons.extend(str(item.get("reason") or "") for item in (job.get("attempt_history") or []) if isinstance(item, dict))
        for reason in reasons:
            normalized = reason.strip().lower()
            if normalized in {"quality_regeneration", "explicit_failed_retry"} or "regenerat" in normalized or "paid_retry" in normalized:
                errors.append(f"job {shot_id} contains prohibited paid resubmission reason: {reason}")
    return errors


def confirmation_errors(confirmation: dict, contract: dict, plan: dict, base_paid_request_count: int) -> list[str]:
    errors = []
    if confirmation.get("confirmation_stage") != "production_authorized":
        errors.append("video confirmation stage is not production_authorized")
    for field in (
        "plan_confirmed",
        "image_assets_confirmed",
        "video_generation_confirmed",
        "single_production_package_confirmed",
        "two_confirmation_package_confirmed",
    ):
        if confirmation.get(field) is not True:
            errors.append(f"video confirmation field {field} is not true")
    if confirmation.get("image_confirmation_intent") != "confirm_images_and_start":
        errors.append("video confirmation intent is not confirm_images_and_start")
    if confirmation.get("contract_digest") != contract.get("contract_digest"):
        errors.append("video confirmation contract digest does not match production contract")
    contracted_duration = str(contract.get("duration_plan_digest") or "")
    planned_duration = str(
        plan.get("duration_plan_digest")
        or (plan.get("duration_plan") or {}).get("duration_plan_digest")
        or ""
    )
    confirmed_duration = str(confirmation.get("confirmed_duration_plan_digest") or "")
    if not contracted_duration or confirmed_duration != contracted_duration or planned_duration != contracted_duration:
        errors.append("video confirmation duration plan digest does not match the contract and generation plan")
    if int(confirmation.get("max_paid_submissions") or 0) != base_paid_request_count:
        errors.append("video confirmation paid submission cap does not equal the base paid request count")
    expected_assets = {
        str(item.get("sha256") or "")
        for item in (contract.get("asset_fingerprints") or [])
        if item.get("role") in PAYLOAD_IMAGE_ROLES and item.get("sha256")
    }
    confirmed_assets = {str(item) for item in (confirmation.get("confirmed_asset_digests") or [])}
    if expected_assets != confirmed_assets:
        errors.append("video confirmation image digests do not match production contract payload assets")
    policy = confirmation.get("autonomous_execution") or {}
    if int(policy.get("base_paid_request_count") or 0) != base_paid_request_count:
        errors.append("video confirmation autonomous base paid request count is invalid")
    if int(policy.get("repair_reserve_paid_submissions") or 0) != 0 or int(policy.get("per_shot_repair_limit") or 0) != 0:
        errors.append("video confirmation contains a paid repair reserve")
    if policy.get("allow_terminal_provider_retry_within_paid_cap") or policy.get("allow_quality_regeneration_within_paid_cap"):
        errors.append("video confirmation enables prohibited paid retry/regeneration")
    return errors


def _poll_request_id(poll: dict) -> str:
    body = poll.get("data") if isinstance(poll.get("data"), dict) else poll
    return str(poll.get("request_id") or body.get("request_id") or body.get("task_id") or body.get("id") or "")


def paid_delivery_evidence_errors(
    project_dir: Path,
    plan: dict,
    contract: dict,
    jobs: dict,
    dry_run_records: list[dict],
) -> tuple[list[str], list[Path], list[Path]]:
    errors = []
    request_paths = []
    poll_paths = []
    dry_by_shot = {str(item.get("shot_id") or ""): item for item in dry_run_records}
    planned_shot_ids = {str(item.get("id") or "") for item in (plan.get("shots") or [])}
    job_shot_ids = {str(item) for item in (jobs.get("jobs") or {})}
    if job_shot_ids != planned_shot_ids:
        errors.append("jobs.json shot ids do not exactly match the generation plan")
    for shot in plan.get("shots") or []:
        shot_id = str(shot.get("id") or "")
        job = (jobs.get("jobs") or {}).get(shot_id) or {}
        request_id = str(job.get("request_id") or "")
        request_raw = str(job.get("request_file") or "")
        poll_raw = str(job.get("poll_file") or "")
        if not request_raw:
            errors.append(f"job {shot_id} is missing paid request_file")
            continue
        request_path = Path(request_raw).expanduser().resolve()
        request_paths.append(request_path)
        if not request_path.exists():
            errors.append(f"paid request_file is missing for {shot_id}: {request_path}")
            continue
        request = load_json(request_path)
        dry_run = dry_by_shot.get(shot_id) or {}
        if request.get("shot_id") != shot_id:
            errors.append(f"paid request shot id does not match job {shot_id}")
        if request.get("contract_digest") != contract.get("contract_digest"):
            errors.append(f"paid request contract digest does not match for {shot_id}")
        request_response_id = str((request.get("response") or {}).get("request_id") or "")
        if not request_id or request_response_id != request_id:
            errors.append(f"paid request request_id does not match jobs.json for {shot_id}")
        if request.get("dry_run") is not False:
            errors.append(f"paid request record is not marked dry_run=false for {shot_id}")
        if canonical_digest(request.get("payload") or {}) != canonical_digest(dry_run.get("payload") or {}):
            errors.append(f"paid request payload does not match the contract dry-run payload for {shot_id}")
        if canonical_digest(request.get("asset_trace") or {}) != canonical_digest(dry_run.get("asset_trace") or {}):
            errors.append(f"paid request asset trace does not match the contract dry-run record for {shot_id}")
        if not poll_raw:
            errors.append(f"job {shot_id} is missing poll_file")
            continue
        poll_path = Path(poll_raw).expanduser().resolve()
        poll_paths.append(poll_path)
        if not poll_path.exists():
            errors.append(f"poll_file is missing for {shot_id}: {poll_path}")
            continue
        poll = load_json(poll_path)
        poll_body = poll.get("data") if isinstance(poll.get("data"), dict) else poll
        if str(poll_body.get("status") or "").upper() not in {"SUCCESS", "DONE", "COMPLETED"}:
            errors.append(f"poll result is not successful for {shot_id}")
        if _poll_request_id(poll) != request_id:
            errors.append(f"poll request_id does not match jobs.json for {shot_id}")
        if poll.get("contract_digest") != contract.get("contract_digest"):
            errors.append(f"poll contract digest does not match for {shot_id}")
        if str(poll.get("shot_id") or "") != shot_id:
            errors.append(f"poll shot id does not match for {shot_id}")
        clip_path = Path(job.get("clip_file") or shot.get("clip_file") or "").expanduser().resolve()
        poll_local_path = str((poll.get("video") or {}).get("local_path") or "")
        if not poll_local_path or Path(poll_local_path).expanduser().resolve() != clip_path:
            errors.append(f"poll clip binding does not match jobs.json for {shot_id}")
        if str(poll.get("output_sha256") or "") != str(job.get("clip_sha256") or ""):
            errors.append(f"poll clip sha256 does not match jobs.json for {shot_id}")
    return errors, request_paths, poll_paths


def evidence_snapshot(paths: list[Path]) -> str:
    entries = []
    for path in paths:
        resolved = path.expanduser().resolve()
        entries.append({
            "path": str(resolved),
            "sha256": sha256_file(resolved) if resolved.exists() and resolved.is_file() else "",
        })
    return canonical_digest(entries)


def write_postprocess_state(project_dir: Path, current_path: Path, data: dict) -> None:
    latest_path = project_dir / "postprocess-manifest.json"
    history_dir = project_dir / "postprocess-history"
    if latest_path.exists():
        previous = load_json(latest_path)
        previous_run_id = str(previous.get("finalize_run_id") or f"legacy-{latest_path.stat().st_mtime_ns}")
        if previous_run_id != data.get("finalize_run_id"):
            archived_path = history_dir / f"{previous_run_id}.json"
            if not archived_path.exists():
                atomic_write_json(archived_path, previous)
    atomic_write_json(current_path, data)
    atomic_write_json(latest_path, data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True)
    args = parser.parse_args()
    current_postprocess_path: Path | None = None
    try:
        project_dir = Path(args.project_dir).expanduser().resolve()
        finalize_run_id = f"finalize-{time.time_ns()}"
        current_postprocess_path = project_dir / "postprocess-history" / f"{finalize_run_id}.json"
        delivery_path = project_dir / "delivery-manifest.json"
        if delivery_path.exists():
            delivery_path.unlink()
        plan_path = project_dir / "generation-plan.json"
        plan = load_json(plan_path)
        subtitles_enabled = not subtitles_disabled(plan)
        if subtitles_enabled and not confirmed_postproduction_subtitles(plan):
            return write_blocked(project_dir, [
                "subtitle-enabled delivery requires a user-confirmed postproduction-only subtitle plan; Provider subtitle generation remains forbidden"
            ])
        contract_path = project_dir / "production-contract.json"
        jobs_path = project_dir / "jobs.json"
        model_snapshot_path = project_dir / "model-snapshot.json"
        confirmation_path = project_dir / "video-confirmation.json"
        contract = load_json(contract_path)
        jobs = load_json(jobs_path)
        model_snapshot = load_json(model_snapshot_path)
        if not confirmation_path.exists():
            return write_blocked(project_dir, ["video-confirmation.json is missing"])
        confirmation = load_json(confirmation_path)
        dry_run_records = []
        dry_run_paths = []
        for shot in plan.get("shots") or []:
            dry_path = project_dir / "requests" / "dry-run" / f"{shot.get('id')}.json"
            dry_run_paths.append(dry_path)
            dry_run_records.append(load_json(dry_path))
        contract_errors = verify_contract(contract, plan, model_snapshot, dry_run_records)
        if contract_errors:
            return write_blocked(project_dir, contract_errors)
        if jobs.get("contract_digest") != contract.get("contract_digest"):
            return write_blocked(project_dir, ["jobs.json does not match production-contract.json"])
        base_paid_request_count = len(contract.get("dry_run_requests") or [])
        ledger_errors = paid_generation_ledger_errors(jobs, base_paid_request_count)
        ledger_errors.extend(confirmation_errors(confirmation, contract, plan, base_paid_request_count))
        evidence_errors, paid_request_paths, poll_paths = paid_delivery_evidence_errors(
            project_dir,
            plan,
            contract,
            jobs,
            dry_run_records,
        )
        ledger_errors.extend(evidence_errors)
        if ledger_errors:
            return write_blocked(project_dir, ledger_errors)
        clip_evidence_paths = [
            Path(((jobs.get("jobs") or {}).get(str(shot.get("id") or "")) or {}).get("clip_file") or shot.get("clip_file") or "")
            .expanduser().resolve()
            for shot in (plan.get("shots") or [])
        ]
        protected_evidence_paths = [
            plan_path,
            contract_path,
            model_snapshot_path,
            confirmation_path,
            jobs_path,
            *dry_run_paths,
            *paid_request_paths,
            *poll_paths,
            *clip_evidence_paths,
        ]
        initial_evidence_snapshot = evidence_snapshot(protected_evidence_paths)
        paid_attempts_before_postprocess = int(jobs.get("paid_submission_attempts") or 0)

        issues = []
        clips = []
        for shot in plan.get("shots") or []:
            shot_id = str(shot.get("id") or "")
            job = (jobs.get("jobs") or {}).get(shot_id) or {}
            clip = Path(shot.get("clip_file") or job.get("clip_file") or project_dir / "clips" / f"{shot_id}.mp4").expanduser().resolve()
            if job.get("state") != "verified":
                issues.append(f"job {shot_id} is {job.get('state') or 'missing'}, expected verified")
            if not clip.exists():
                issues.append(f"missing expected clip: {clip}")
            else:
                expected_clip_digest = str(job.get("clip_sha256") or "")
                actual_clip_digest = sha256_file(clip)
                if not expected_clip_digest:
                    issues.append(f"job {shot_id} is missing verified clip sha256 evidence")
                elif expected_clip_digest != actual_clip_digest:
                    issues.append(f"verified clip sha256 mismatch for {shot_id}: {clip}")
            clips.append(clip)
        if issues:
            return write_blocked(project_dir, issues)

        stitch_plan = plan.get("stitching_plan") or {}
        if should_use_original_single_clip(plan, clips):
            raw_output = clips[0]
            stitch_result = {
                "ok": True,
                "skipped": True,
                "reason": "single complete clip with subtitles and effects disabled",
                "output": str(raw_output),
                "report_file": "",
                "normalized_media": [{"path": str(raw_output)}],
            }
        else:
            subtitle_plan = plan.get("subtitle_plan") or {}
            raw_output_value = subtitle_plan.get("clean_video_output") if subtitles_enabled else ""
            raw_output = Path(raw_output_value or stitch_plan.get("final_output") or project_dir / "final.mp4").expanduser().resolve()
            stitch_cmd = [
                sys.executable,
                str(SCRIPT_DIR / "stitch_clips.py"),
                "--project-dir", str(project_dir),
                "--clips", *[str(path) for path in clips],
                "--output", str(raw_output),
                "--require-audio",
            ]
            if stitch_plan.get("target_resolution"):
                stitch_cmd.extend(["--target-resolution", str(stitch_plan["target_resolution"])])
            if stitch_plan.get("target_fps"):
                stitch_cmd.extend(["--target-fps", str(stitch_plan["target_fps"])])
            if should_auto_trim_tail_silence(plan):
                stitch_cmd.append("--auto-trim-tail-silence")
                for option, field in (
                    ("--min-tail-silence", "min_tail_silence_seconds"),
                    ("--tail-padding", "tail_padding_seconds"),
                    ("--max-tail-trim", "max_tail_trim_seconds"),
                ):
                    if stitch_plan.get(field) is not None:
                        stitch_cmd.extend([option, str(stitch_plan[field])])
            code, stitch_result, stderr = run_worker(stitch_cmd)
            if code != 0:
                return write_blocked(project_dir, [f"stitch failed: {stitch_result.get('error') or stderr.strip()}"])

        subtitle_source = None
        final_video = raw_output

        stitch_report_path = Path(stitch_result.get("report_file")).expanduser().resolve() if stitch_result.get("report_file") else None
        postprocess_operations = [{
            "type": "direct_verified_clip" if stitch_result.get("skipped") else "local_stitch",
            "paid_api_call": False,
            "tail_trim_enabled": bool(not stitch_result.get("skipped") and should_auto_trim_tail_silence(plan)),
        }]
        processed_clips = [item.get("path") for item in (stitch_result.get("normalized_media") or []) if item.get("path")]
        clean_checks = {"required": subtitles_enabled, "technical_review_pass": True, "visual_review_pass": True}
        clean_review_path: Path | None = None
        clean_visual_path: Path | None = None
        clean_visual_review: dict = {}
        if subtitles_enabled:
            subtitle_plan = plan.get("subtitle_plan") or {}
            clean_review_path = project_dir / "final-review.clean.json"
            clean_visual_path = Path(
                subtitle_plan.get("clean_visual_review_output") or project_dir / "visual-review.clean.json"
            ).expanduser().resolve()
            clean_review_command = [
                sys.executable,
                str(SCRIPT_DIR / "review_render.py"),
                "--project-dir", str(project_dir),
                "--plan", str(plan_path),
                "--video", str(raw_output),
                "--output", str(clean_review_path),
                "--review-stage", "clean_provider",
                "--review-dir", str(project_dir / "review" / "clean"),
            ]
            if processed_clips:
                clean_review_command.extend(["--clips", *processed_clips])
            if stitch_plan.get("duration_tolerance_seconds") is not None:
                clean_review_command.extend(["--duration-tolerance", str(stitch_plan["duration_tolerance_seconds"])])
            if stitch_plan.get("duration_tolerance_ratio") is not None:
                clean_review_command.extend(["--duration-tolerance-ratio", str(stitch_plan["duration_tolerance_ratio"])])
            run_worker(clean_review_command)
            clean_technical = load_json(clean_review_path) if clean_review_path.exists() else {
                "status": "fail", "issues_found": ["final-review.clean.json missing"]
            }
            clean_visual_review = load_json(clean_visual_path) if clean_visual_path.exists() else {"status": "missing"}
            clean_digest = sha256_file(raw_output) if raw_output.exists() else ""
            clean_visual_errors = visual_review_errors(
                clean_visual_review,
                raw_output,
                clean_digest,
                expected_boundaries=max(0, len(plan.get("shots") or []) - 1),
                expected_segments=max(1, len(plan.get("shots") or [])),
                subtitles_enabled=False,
                expected_speech_fidelity_mode=str(plan.get("speech_fidelity_mode") or ""),
            )
            clean_checks = {
                "required": True,
                "technical_review_pass": clean_technical.get("status") == "pass" and clean_technical.get("output_sha256") == clean_digest,
                "visual_review_pass": not clean_visual_errors,
                "no_generated_text_pass": clean_visual_review.get("no_generated_text") is True,
            }
            clean_issues = []
            if not clean_checks["technical_review_pass"]:
                clean_issues.extend(clean_technical.get("issues_found") or ["clean technical review did not pass"])
            clean_issues.extend(clean_visual_errors)
            if not all(value for key, value in clean_checks.items() if key != "required"):
                interim = {
                    "version": "1.0",
                    "status": "clean_provider_review_blocked",
                    "finalize_run_id": finalize_run_id,
                    "contract_digest": contract.get("contract_digest"),
                    "base_paid_request_count": base_paid_request_count,
                    "paid_video_requests_added": 0,
                    "operations": postprocess_operations + [{
                        "type": "clean_provider_technical_and_visual_review",
                        "paid_api_call": False,
                        "status": "blocked",
                    }],
                    "raw_final_video": artifact_entry(raw_output),
                    "final_video": artifact_entry(raw_output),
                    "subtitle_file": artifact_entry(None),
                    "subtitle_policy": "awaiting_clean_provider_review_before_postproduction_burn",
                    "clean_review_checks": clean_checks,
                    "clean_review_issues": clean_issues,
                    "clean_technical_review": artifact_entry(clean_review_path),
                    "clean_visual_review": artifact_entry(clean_visual_path),
                    "recorded_at": int(time.time()),
                }
                write_postprocess_state(project_dir, current_postprocess_path, interim)
                return write_blocked(
                    project_dir,
                    clean_issues or ["clean Provider output review did not pass before subtitle burn"],
                    clean_checks,
                    current_postprocess_manifest=current_postprocess_path,
                )

            subtitle_source = Path(subtitle_plan.get("srt_output") or project_dir / "subtitles" / "final.srt").expanduser().resolve()
            generate_code, generate_result, generate_stderr = run_worker([
                sys.executable,
                str(SCRIPT_DIR / "generate_subtitles.py"),
                "--plan", str(plan_path),
                "--video", str(raw_output),
            ])
            if generate_code != 0:
                return write_blocked(project_dir, [
                    f"local subtitle generation failed after clean review: {generate_result.get('error') or generate_stderr.strip()}"
                ])
            final_video = Path(
                subtitle_plan.get("burned_video_output") or project_dir / "final.captioned.mp4"
            ).expanduser().resolve()
            burn_code, burn_result, burn_stderr = run_worker([
                sys.executable,
                str(SCRIPT_DIR / "burn_subtitles.py"),
                "--plan", str(plan_path),
                "--video", str(raw_output),
                "--srt", str(subtitle_source),
                "--output", str(final_video),
            ])
            if burn_code != 0:
                return write_blocked(project_dir, [
                    f"local subtitle burn failed after clean review: {burn_result.get('error') or burn_stderr.strip()}"
                ])
            postprocess_operations.extend([
                {
                    "type": "local_final_audio_subtitle_generation",
                    "paid_api_call": False,
                    "timing_source": (plan.get("subtitle_plan") or {}).get("timing_source"),
                    "audit": generate_result.get("audit"),
                },
                {
                    "type": "postproduction_subtitle_burn",
                    "paid_api_call": False,
                    "profile_id": burn_result.get("profile_id"),
                    "audit": burn_result.get("audit"),
                },
            ])

        jobs_after_postprocess = load_json(project_dir / "jobs.json")
        paid_attempts_after_postprocess = int(jobs_after_postprocess.get("paid_submission_attempts") or 0)
        if paid_attempts_after_postprocess != paid_attempts_before_postprocess:
            return write_blocked(project_dir, [
                "paid submission count changed during local postprocessing; delivery is blocked"
            ])
        postprocess_manifest = {
            "version": "1.0",
            "status": "completed_pending_review",
            "finalize_run_id": finalize_run_id,
            "contract_digest": contract.get("contract_digest"),
            "base_paid_request_count": base_paid_request_count,
            "paid_video_requests_added": 0,
            "paid_submission_attempts_before": paid_attempts_before_postprocess,
            "paid_submission_attempts_after": paid_attempts_after_postprocess,
            "operations": postprocess_operations,
            "raw_final_video": artifact_entry(raw_output),
            "final_video": artifact_entry(final_video),
            "stitch_report": artifact_entry(stitch_report_path),
            "subtitle_file": artifact_entry(subtitle_source),
            "subtitle_policy": (
                "confirmed_postproduction_burn_only_after_clean_provider_review"
                if subtitles_enabled else "default_disabled_no_srt_no_burn"
            ),
            "clean_review_checks": clean_checks,
            "clean_technical_review": artifact_entry(clean_review_path),
            "clean_visual_review": artifact_entry(clean_visual_path),
            "actual_duration_seconds": float(media_summary(final_video).get("duration_seconds") or 0),
            "delivery_max_seconds": float((plan.get("duration_plan") or {}).get("delivery_max_seconds") or 0),
            "delivery_max_frame_error_seconds": MAX_DELIVERY_FRAME_ERROR_SECONDS,
            "recorded_at": int(time.time()),
        }
        write_postprocess_state(project_dir, current_postprocess_path, postprocess_manifest)

        if "partial" in final_video.name.lower() or "preview" in final_video.name.lower():
            return write_blocked(
                project_dir,
                [f"partial or preview output cannot be released: {final_video}"],
                current_postprocess_manifest=current_postprocess_path,
            )

        review_path = project_dir / "final-review.json"
        review_command = [
            sys.executable,
            str(SCRIPT_DIR / "review_render.py"),
            "--project-dir", str(project_dir),
            "--plan", str(plan_path),
            "--video", str(final_video),
            "--output", str(review_path),
        ]
        if subtitles_enabled:
            review_command.extend(["--review-dir", str(project_dir / "review" / "captioned")])
        if processed_clips:
            review_command.extend(["--clips", *processed_clips])
        if stitch_plan.get("duration_tolerance_seconds") is not None:
            review_command.extend(["--duration-tolerance", str(stitch_plan["duration_tolerance_seconds"])])
        if stitch_plan.get("duration_tolerance_ratio") is not None:
            review_command.extend(["--duration-tolerance-ratio", str(stitch_plan["duration_tolerance_ratio"])])
        run_worker(review_command)
        technical_review = load_json(review_path) if review_path.exists() else {"status": "fail", "issues_found": ["final-review.json missing"]}
        visual_path = Path(
            ((plan.get("subtitle_plan") or {}).get("caption_visual_review_output") if subtitles_enabled else "")
            or project_dir / "visual-review.json"
        ).expanduser().resolve()
        visual_review = load_json(visual_path) if visual_path.exists() else {"status": "missing"}
        final_digest = sha256_file(final_video) if final_video.exists() else ""
        visual_errors = visual_review_errors(
            visual_review,
            final_video,
            final_digest,
            expected_boundaries=max(0, len(plan.get("shots") or []) - 1),
            expected_segments=max(1, len(plan.get("shots") or [])),
            subtitles_enabled=subtitles_enabled,
            expected_speech_fidelity_mode=str(plan.get("speech_fidelity_mode") or ""),
        )
        checks = {
            "all_jobs_verified": all((jobs.get("jobs") or {}).get(shot.get("id"), {}).get("state") == "verified" for shot in plan.get("shots") or []),
            "stitch_pass": bool(raw_output.exists() and stitch_result.get("ok")),
            "clean_provider_review_pass": all(
                value for key, value in clean_checks.items() if key != "required"
            ),
            "subtitle_policy_pass": bool(
                not subtitles_enabled
                or (
                    subtitle_source is not None
                    and subtitle_source.is_file()
                    and final_video.is_file()
                    and final_video != raw_output
                )
            ),
            "technical_review_pass": technical_review.get("status") == "pass" and technical_review.get("output_sha256") == final_digest,
            "visual_review_pass": not visual_errors,
        }
        issues = []
        finalize_hard_duration_error = delivery_duration_hard_limit_error(
            float(media_summary(final_video).get("duration_seconds") or 0),
            float((plan.get("duration_plan") or {}).get("delivery_max_seconds") or 0),
        )
        checks["delivery_duration_hard_cap_pass"] = not bool(finalize_hard_duration_error)
        if finalize_hard_duration_error:
            issues.append(finalize_hard_duration_error)
        if not checks["technical_review_pass"]:
            issues.extend(str(item) for item in (technical_review.get("issues_found") or ["technical review did not pass or output digest is stale"]))
        issues.extend(visual_errors)
        if not all(checks.values()):
            postprocess_manifest.update({
                "status": "completed_review_blocked",
                "review_checks": checks,
                "review_issues": issues or ["one or more delivery checks failed"],
                "technical_review": artifact_entry(review_path),
                "visual_review": artifact_entry(visual_path),
                "reviewed_at": int(time.time()),
            })
            postprocess_manifest["operations"].append({
                "type": "local_technical_and_visual_review",
                "paid_api_call": False,
                "status": "blocked",
            })
            write_postprocess_state(project_dir, current_postprocess_path, postprocess_manifest)
            return write_blocked(
                project_dir,
                issues or ["one or more delivery checks failed"],
                checks,
                current_postprocess_manifest=current_postprocess_path,
            )

        final_plan = load_json(plan_path)
        final_contract = load_json(contract_path)
        final_model_snapshot = load_json(model_snapshot_path)
        final_confirmation = load_json(confirmation_path)
        final_jobs = load_json(jobs_path)
        final_dry_run_records = [load_json(path) for path in dry_run_paths]
        end_errors = verify_contract(final_contract, final_plan, final_model_snapshot, final_dry_run_records)
        if final_contract.get("contract_digest") != contract.get("contract_digest"):
            end_errors.append("production contract changed during finalize")
        if final_jobs.get("contract_digest") != final_contract.get("contract_digest"):
            end_errors.append("jobs.json contract digest changed during finalize")
        end_errors.extend(paid_generation_ledger_errors(final_jobs, base_paid_request_count))
        end_errors.extend(confirmation_errors(final_confirmation, final_contract, final_plan, base_paid_request_count))
        final_evidence_errors, _, _ = paid_delivery_evidence_errors(
            project_dir,
            final_plan,
            final_contract,
            final_jobs,
            final_dry_run_records,
        )
        end_errors.extend(final_evidence_errors)
        if evidence_snapshot(protected_evidence_paths) != initial_evidence_snapshot:
            end_errors.append("protected contract/confirmation/jobs/request evidence changed during finalize")
        if end_errors:
            postprocess_manifest.update({
                "status": "completed_review_blocked",
                "review_checks": checks,
                "review_issues": end_errors,
                "technical_review": artifact_entry(review_path),
                "visual_review": artifact_entry(visual_path),
                "reviewed_at": int(time.time()),
            })
            write_postprocess_state(project_dir, current_postprocess_path, postprocess_manifest)
            return write_blocked(
                project_dir,
                end_errors,
                checks,
                current_postprocess_manifest=current_postprocess_path,
            )

        postprocess_manifest["operations"].append({
            "type": "local_technical_and_visual_review",
            "paid_api_call": False,
            "status": "pass",
        })
        postprocess_manifest.update({
            "status": "pass",
            "review_checks": checks,
            "review_issues": [],
            "technical_review": artifact_entry(review_path),
            "visual_review": artifact_entry(visual_path),
            "clean_technical_review": artifact_entry(clean_review_path),
            "clean_visual_review": artifact_entry(clean_visual_path),
            "reviewed_at": int(time.time()),
        })
        write_postprocess_state(project_dir, current_postprocess_path, postprocess_manifest)
        artifact_hashes = {
            "clips": [artifact_entry(path) for path in clips],
            "raw_final_video": artifact_entry(raw_output),
            "final_video": artifact_entry(final_video),
            "subtitle_file": artifact_entry(subtitle_source),
            "stitch_report": artifact_entry(stitch_report_path),
            "technical_review": artifact_entry(review_path),
            "visual_review": artifact_entry(visual_path),
            "generation_plan": artifact_entry(plan_path),
            "production_contract": artifact_entry(contract_path),
            "video_confirmation": artifact_entry(confirmation_path),
            "jobs": artifact_entry(jobs_path),
            "paid_requests": [artifact_entry(path) for path in paid_request_paths],
            "poll_results": [artifact_entry(path) for path in poll_paths],
            "postprocess_manifest": artifact_entry(current_postprocess_path),
            "reviewed_frames": [artifact_entry(_review_evidence_path(item, final_video.parent)) for item in (visual_review.get("reviewed_frames") or [])],
            "reviewed_boundary_frames": [artifact_entry(_review_evidence_path(item, final_video.parent)) for item in (visual_review.get("reviewed_boundary_frames") or [])],
            "speech_transcript": artifact_entry(_review_evidence_path((visual_review.get("speech_evidence") or {}).get("transcript"), final_video.parent)),
        }
        speech_evidence = visual_review.get("speech_evidence") or {}
        delivery_classification = "pass_with_notes" if (
            visual_review.get("status") == "pass_with_notes"
            or speech_evidence.get("status") == "pass_with_notes"
        ) else "pass"
        delivery = {
            "version": "1.0",
            "status": "pass",
            "delivery_classification": delivery_classification,
            "delivery_notes": speech_evidence.get("minor_discrepancies") or [],
            "project_dir": str(project_dir),
            "contract_digest": contract.get("contract_digest"),
            "final_video": str(final_video),
            "final_video_sha256": final_digest,
            "subtitle_file": str(subtitle_source) if subtitle_source else "",
            "subtitle_policy": (
                "confirmed_postproduction_burn_only_after_clean_provider_review"
                if subtitles_enabled else "default_disabled_no_srt_no_burn"
            ),
            "clean_video": str(raw_output) if subtitles_enabled else "",
            "clean_technical_review": str(clean_review_path) if clean_review_path else "",
            "clean_visual_review": str(clean_visual_path) if clean_visual_path else "",
            "stitch_report": stitch_result.get("report_file"),
            "technical_review": str(review_path),
            "visual_review": str(visual_path),
            "artifact_hashes": artifact_hashes,
            "checks": checks,
            "paid_submission_attempts": jobs.get("paid_submission_attempts"),
            "max_paid_submissions": jobs.get("max_paid_submissions"),
            "postprocess_manifest": str(current_postprocess_path),
            "delivered_at": int(time.time()),
        }
        atomic_write_json(project_dir / "delivery-manifest.json", delivery)
        atomic_write_json(project_dir / "finalize-report.json", delivery)
        print(json.dumps(delivery, ensure_ascii=False, indent=2))
        return 0
    except (ScriptError, ValueError) as exc:
        project_dir = Path(args.project_dir).expanduser().resolve()
        current = current_postprocess_path if current_postprocess_path and current_postprocess_path.exists() else None
        return write_blocked(project_dir, [str(exc)], current_postprocess_manifest=current)


if __name__ == "__main__":
    raise SystemExit(main())
