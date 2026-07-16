#!/usr/bin/env python3
"""Finalize an existing-video postproduction project without video API jobs."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from _common import ScriptError, asset_value, load_json
from _routing import infer_execution_route
from _workflow import atomic_write_json, canonical_digest, sha256_file
from subtitle_policy import is_confirmed_postproduction_subtitle_plan
from finalize_project import (
    _review_evidence_path,
    artifact_entry,
    confirmed_postproduction_subtitles,
    run_worker,
    visual_review_errors,
    write_blocked,
)


SCRIPT_DIR = Path(__file__).resolve().parent


def candidate_must_differ_from_source(plan: dict) -> bool:
    """A confirmed subtitle-only route may use the untouched source as its clean candidate."""
    return not confirmed_postproduction_subtitles(plan)


def validate_postproduction_operations(plan: dict, edit_manifest: dict) -> list[str]:
    errors = []
    operations = edit_manifest.get("operations") or []
    if edit_manifest.get("all_operations_user_approved") is not True:
        errors.append("postproduction operations are not recorded as user approved")
    operation_types = {str(item.get("type") or "").strip().lower() for item in operations if isinstance(item, dict)}
    subtitle_operation_types = {
        "subtitle", "subtitles", "caption", "captions", "subtitle_burn", "caption_burn",
        "local_subtitle_generation_and_burn", "local_chinese_subtitle_generation_and_burn",
    }
    subtitle_plan = plan.get("subtitle_plan") or {}
    subtitles_enabled = bool(subtitle_plan.get("enabled"))
    confirmed_post_burn = is_confirmed_postproduction_subtitle_plan(subtitle_plan)
    requested_subtitle_ops = operation_types.intersection(subtitle_operation_types | {"postproduction_subtitle_burn"})
    if requested_subtitle_ops and not confirmed_post_burn:
        errors.append("subtitle/caption burn requires a user-confirmed postproduction subtitle plan")
    if subtitles_enabled and "postproduction_subtitle_burn" not in operation_types:
        errors.append("enabled subtitles require a planned postproduction_subtitle_burn operation")
    if "postproduction_subtitle_burn" in operation_types:
        subtitle_entries = [
            item for item in operations
            if isinstance(item, dict) and str(item.get("type") or "").strip().lower() == "postproduction_subtitle_burn"
        ]
        if any(item.get("paid_api_call") is not False for item in subtitle_entries):
            errors.append("postproduction subtitle burn must record paid_api_call=false")
        if any(item.get("status") not in {"planned", "applied"} for item in subtitle_entries):
            errors.append("postproduction subtitle burn status must be planned or applied")
    for item in operations:
        if not isinstance(item, dict):
            errors.append("every postproduction operation must be an object")
            continue
        operation_type = str(item.get("type") or "").strip().lower()
        if operation_type == "postproduction_subtitle_burn" and confirmed_post_burn:
            continue
        if item.get("status") != "applied":
            errors.append(f"postproduction operation {operation_type or 'unknown'} is not applied")
    if not operations:
        errors.append("postproduction manifest needs at least one operation")
    if edit_manifest.get("caption_mask_applied") is True or "caption_mask" in operation_types:
        errors.append("caption mask/background bar is forbidden")
    visual_effect_types = {
        "broll", "title_card", "chapter_card", "cutaway", "overlay", "music", "transition", "progress_bar"
    }
    if not bool((plan.get("effects_plan") or {}).get("enabled")) and operation_types.intersection(visual_effect_types):
        errors.append("visual effects are disabled but the postproduction manifest contains effects")
    return errors


def mark_subtitle_operation_applied(
    edit_manifest: dict,
    subtitle_output: Path,
    final_candidate: Path,
    burn_audit: str,
) -> dict:
    updated = json.loads(json.dumps(edit_manifest))
    for item in updated.get("operations") or []:
        if str(item.get("type") or "").strip().lower() != "postproduction_subtitle_burn":
            continue
        item.update({
            "status": "applied",
            "paid_api_call": False,
            "subtitle_file": str(subtitle_output),
            "subtitle_sha256": sha256_file(subtitle_output),
            "output_video": str(final_candidate),
            "output_video_sha256": sha256_file(final_candidate),
            "burn_audit": str(burn_audit or ""),
            "applied_at": int(time.time()),
        })
    updated["subtitle_burn_completed"] = True
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True)
    args = parser.parse_args()
    project_dir = Path(args.project_dir).expanduser().resolve()
    try:
        plan_path = project_dir / "generation-plan.json"
        plan = load_json(plan_path)
        if infer_execution_route(plan) != "postproduction_only":
            raise ScriptError("finalize_postproduction.py only accepts postproduction_only projects")
        preflight_path = project_dir / "preflight-report.json"
        preflight = load_json(preflight_path)
        if not preflight.get("ok") or preflight.get("paid_generation_allowed") is not False:
            raise ScriptError("postproduction preflight must pass with paid_generation_allowed=false")
        if preflight.get("plan_digest") != canonical_digest(plan):
            raise ScriptError("postproduction plan changed after preflight; run preflight and review the edit plan again")

        source_asset = plan.get("existing_video_file") or {}
        source_value = asset_value(source_asset)
        source_video = Path(source_value).expanduser().resolve() if source_value else None
        if source_video is None or not source_video.exists():
            raise ScriptError("postproduction source video is missing")
        postproduction = plan.get("postproduction_plan") or {}
        candidate_value = postproduction.get("candidate_output")
        candidate = Path(candidate_value).expanduser().resolve() if candidate_value else None
        if candidate is None or not candidate.exists():
            raise ScriptError(f"postproduction review candidate is missing: {candidate or 'candidate_output'}")
        if "partial" in candidate.name.lower() or "preview" in candidate.name.lower():
            raise ScriptError(f"partial or preview output cannot be released: {candidate}")
        source_digest = sha256_file(source_video)
        candidate_digest = sha256_file(candidate)
        subtitles_enabled = confirmed_postproduction_subtitles(plan)
        if source_digest == candidate_digest and candidate_must_differ_from_source(plan):
            raise ScriptError("postproduction candidate is unchanged from the source video")
        edit_manifest_path = Path(postproduction.get("edit_manifest") or project_dir / "postproduction-manifest.json").expanduser().resolve()
        edit_manifest = load_json(edit_manifest_path)
        if edit_manifest.get("status") != "pass":
            raise ScriptError("postproduction manifest status is not pass")
        if edit_manifest.get("source_video_sha256") != source_digest:
            raise ScriptError("postproduction manifest source_video_sha256 does not match the current source")
        if edit_manifest.get("candidate_sha256") != candidate_digest:
            raise ScriptError("postproduction manifest candidate_sha256 does not match the current candidate")
        if edit_manifest.get("preserve_source_speech") is not True:
            raise ScriptError("postproduction manifest must confirm preserve_source_speech=true")
        operation_errors = validate_postproduction_operations(plan, edit_manifest)
        if operation_errors:
            raise ScriptError("; ".join(operation_errors))

        review_path = project_dir / ("final-review.clean.json" if subtitles_enabled else "final-review.json")
        run_worker([
            sys.executable,
            str(SCRIPT_DIR / "review_render.py"),
            "--project-dir", str(project_dir),
            "--plan", str(plan_path),
            "--video", str(candidate),
            "--clips", str(candidate),
            "--output", str(review_path),
            *(["--review-stage", "clean_provider", "--review-dir", str(project_dir / "review" / "clean")] if subtitles_enabled else []),
        ])
        technical = load_json(review_path) if review_path.exists() else {"status": "fail"}
        visual_path = Path(
            ((plan.get("subtitle_plan") or {}).get("clean_visual_review_output") if subtitles_enabled else "")
            or project_dir / ("visual-review.clean.json" if subtitles_enabled else "visual-review.json")
        ).expanduser().resolve()
        visual = load_json(visual_path) if visual_path.exists() else {"status": "missing"}
        final_digest = candidate_digest
        visual_errors = visual_review_errors(
            visual,
            candidate,
            final_digest,
            expected_boundaries=0,
            expected_segments=1,
            subtitles_enabled=False,
        )
        clean_checks = {
            "postproduction_preflight_pass": True,
            "paid_video_generation_disabled": preflight.get("expected_paid_requests") == 0,
            "technical_review_pass": technical.get("status") == "pass" and technical.get("output_sha256") == final_digest,
            "visual_review_pass": not visual_errors,
        }
        issues = []
        if not clean_checks["technical_review_pass"]:
            issues.extend(technical.get("issues_found") or ["technical review did not pass or output digest is stale"])
        issues.extend(visual_errors)
        if not all(clean_checks.values()):
            return write_blocked(project_dir, [str(item) for item in issues], clean_checks)

        clean_candidate = candidate
        clean_review_path = review_path
        clean_visual_path = visual_path
        subtitle_output: Path | None = None
        final_candidate = clean_candidate
        if subtitles_enabled:
            subtitle_plan = plan.get("subtitle_plan") or {}
            subtitle_output = Path(
                subtitle_plan.get("srt_output") or project_dir / "subtitles" / "final.srt"
            ).expanduser().resolve()
            generation_code, generation, generation_stderr = run_worker([
                sys.executable,
                str(SCRIPT_DIR / "generate_subtitles.py"),
                "--plan", str(plan_path),
                "--video", str(clean_candidate),
            ])
            if generation_code != 0:
                raise ScriptError(
                    f"local subtitle generation failed: {generation.get('error') or generation_stderr.strip()}"
                )
            final_candidate = Path(
                subtitle_plan.get("burned_video_output") or project_dir / "final.captioned.mp4"
            ).expanduser().resolve()
            burn_code, burn, burn_stderr = run_worker([
                sys.executable,
                str(SCRIPT_DIR / "burn_subtitles.py"),
                "--plan", str(plan_path),
                "--video", str(clean_candidate),
                "--srt", str(subtitle_output),
                "--output", str(final_candidate),
            ])
            if burn_code != 0:
                raise ScriptError(f"local subtitle burn failed: {burn.get('error') or burn_stderr.strip()}")
            review_path = project_dir / "final-review.json"
            run_worker([
                sys.executable,
                str(SCRIPT_DIR / "review_render.py"),
                "--project-dir", str(project_dir),
                "--plan", str(plan_path),
                "--video", str(final_candidate),
                "--clips", str(clean_candidate),
                "--output", str(review_path),
                "--review-dir", str(project_dir / "review" / "captioned"),
            ])
            technical = load_json(review_path) if review_path.exists() else {"status": "fail"}
            visual_path = Path(
                subtitle_plan.get("caption_visual_review_output") or project_dir / "visual-review.json"
            ).expanduser().resolve()
            visual = load_json(visual_path) if visual_path.exists() else {"status": "missing"}
            final_digest = sha256_file(final_candidate) if final_candidate.exists() else ""
            visual_errors = visual_review_errors(
                visual,
                final_candidate,
                final_digest,
                expected_boundaries=0,
                expected_segments=1,
                subtitles_enabled=True,
            )
            checks = {
                **clean_checks,
                "caption_technical_review_pass": technical.get("status") == "pass" and technical.get("output_sha256") == final_digest,
                "caption_visual_review_pass": not visual_errors,
                "subtitle_postproduction_pass": subtitle_output.is_file() and final_candidate.is_file(),
            }
            issues = []
            if not checks["caption_technical_review_pass"]:
                issues.extend(technical.get("issues_found") or ["captioned technical review did not pass"])
            issues.extend(visual_errors)
            if not all(checks.values()):
                return write_blocked(project_dir, [str(item) for item in issues], checks)
            edit_manifest = mark_subtitle_operation_applied(
                edit_manifest,
                subtitle_output,
                final_candidate,
                str(burn.get("audit") or ""),
            )
            atomic_write_json(edit_manifest_path, edit_manifest)
        else:
            checks = clean_checks

        candidate = final_candidate
        candidate_digest = final_digest

        subtitle_asset = plan.get("subtitle_file") or {}
        subtitle_value = asset_value(subtitle_asset)
        source_subtitle_path = Path(subtitle_value).expanduser().resolve() if subtitle_value else None
        delivery = {
            "version": "1.0",
            "status": "pass",
            "execution_route": "postproduction_only",
            "project_dir": str(project_dir),
            "final_video": str(candidate),
            "final_video_sha256": final_digest,
            "clean_video": str(clean_candidate) if subtitles_enabled else "",
            "subtitle_file": str(subtitle_output) if subtitle_output else "",
            "subtitle_policy": "confirmed_postproduction_burn_only" if subtitles_enabled else "default_disabled_no_srt_no_burn",
            "technical_review": str(review_path),
            "visual_review": str(visual_path),
            "checks": checks,
            "paid_submission_attempts": 0,
            "max_paid_submissions": 0,
            "artifact_hashes": {
                "source_video": artifact_entry(source_video),
                "clean_video": artifact_entry(clean_candidate if subtitles_enabled else None),
                "final_video": artifact_entry(candidate),
                "source_subtitle_file": artifact_entry(source_subtitle_path),
                "subtitle_file": artifact_entry(subtitle_output),
                "technical_review": artifact_entry(review_path),
                "visual_review": artifact_entry(visual_path),
                "clean_technical_review": artifact_entry(clean_review_path if subtitles_enabled else None),
                "clean_visual_review": artifact_entry(clean_visual_path if subtitles_enabled else None),
                "generation_plan": artifact_entry(plan_path),
                "preflight_report": artifact_entry(preflight_path),
                "postproduction_manifest": artifact_entry(edit_manifest_path),
                "reviewed_frames": [
                    artifact_entry(_review_evidence_path(item, candidate.parent))
                    for item in (visual.get("reviewed_frames") or [])
                ],
                "reviewed_boundary_frames": [
                    artifact_entry(_review_evidence_path(item, candidate.parent))
                    for item in (visual.get("reviewed_boundary_frames") or [])
                ],
                "speech_transcript": artifact_entry(
                    _review_evidence_path((visual.get("speech_evidence") or {}).get("transcript"), candidate.parent)
                ),
            },
            "delivered_at": int(time.time()),
        }
        atomic_write_json(project_dir / "delivery-manifest.json", delivery)
        atomic_write_json(project_dir / "finalize-report.json", delivery)
        print(json.dumps(delivery, ensure_ascii=False, indent=2))
        return 0
    except (ScriptError, ValueError) as exc:
        return write_blocked(project_dir, [str(exc)])


if __name__ == "__main__":
    raise SystemExit(main())
