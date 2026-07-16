#!/usr/bin/env python3
"""Validate a prepared talking-head video project before video generation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from _common import (
    MINIMUM_MULTI_SEGMENT_SPOKEN_FILL_RATIO,
    ScriptError,
    contains_secret,
    load_json,
    plan_request_durations,
    semantic_boundary_issue,
)
from _routing import infer_execution_route
from subtitle_policy import enabled_subtitle_contract_errors


REQUIRED_PLAN_FIELDS = (
    "content_mode",
    "platform",
    "language",
    "duration_plan",
    "duration_plan_digest",
    "aspect_ratio",
    "resolution",
    "execution_route",
    "intake_route",
    "business_context",
    "source_fact_map",
    "localization_contract",
    "postproduction_plan",
    "avatar_plan",
    "script_file",
    "script_text",
    "script_pacing",
    "broll_plan",
    "effects_plan",
    "creative_choices",
    "subtitle_strategy",
    "subtitle_plan",
    "visual_bible",
    "visual_asset_strategy",
    "image_consistency_plan",
    "longform_generation_strategy",
    "stitching_plan",
    "confirmed_assets",
)


def validate_script_pacing(plan: dict, enforce: bool) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    pacing = plan.get("script_pacing") or {}
    shots = plan.get("shots") or []
    if not pacing:
        message = "script_pacing is missing; run prepare_project.py again before paid generation"
        if enforce:
            errors.append(message)
        else:
            warnings.append(message)
        return errors, warnings

    bad_statuses = {"missing_script", "too_long"}
    if pacing.get("status") != "ok":
        warnings.append(f"script_pacing status is {pacing.get('status')}; inspect segment pacing before paid generation")
    for shot in shots:
        shot_pacing = shot.get("script_pacing") or {}
        status = shot_pacing.get("status")
        if not shot_pacing:
            message = f"{shot.get('id', 'unknown shot')} is missing script_pacing"
            if enforce:
                errors.append(message)
            else:
                warnings.append(message)
            continue
        if status in bad_statuses:
            message = (
                f"{shot.get('id', 'unknown shot')} script_pacing={status}: estimated "
                f"{shot_pacing.get('estimated_spoken_seconds')}s for {shot_pacing.get('target_duration_seconds')}s"
            )
            if enforce:
                errors.append(message)
            else:
                warnings.append(message)
    return errors, warnings


def validate_script_boundaries(plan: dict, enforce: bool) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    shots = plan.get("shots") or []
    if len(shots) <= 1:
        return errors, warnings
    for shot in shots:
        boundary = shot.get("script_boundary") or {}
        if not boundary:
            message = f"{shot.get('id', 'unknown shot')} is missing script_boundary"
        elif boundary.get("stitch_safe") is False:
            message = (
                f"{shot.get('id', 'unknown shot')} script_boundary={boundary.get('boundary_type')}: "
                f"{boundary.get('issue') or 'segment does not end on a clean sentence boundary'}"
            )
        else:
            continue
        if enforce:
            errors.append(message)
        else:
            warnings.append(message)
    return errors, warnings


def validate_plan(plan: dict, enforce_script_pacing: bool = False) -> tuple[list[str], list[str]]:
    errors = []
    warnings = list(plan.get("warnings") or [])
    for field in REQUIRED_PLAN_FIELDS:
        if field not in plan:
            errors.append(f"missing {field}")
    text = json.dumps(plan, ensure_ascii=False)
    if contains_secret(text):
        errors.append("plan appears to contain a raw API key or bearer token")
    choices = plan.get("creative_choices") or {}
    subtitle_choice = (choices.get("subtitle") or {}).get("choice")
    effects_choice = (choices.get("effects") or {}).get("choice")
    if subtitle_choice not in {"enabled", "disabled"}:
        errors.append("subtitle choice is pending; subtitles default disabled and may be enabled only from user_plan_confirmation")
    if effects_choice not in {"enabled", "disabled"}:
        errors.append("effects choice is pending; user must confirm enabled or disabled")
    subtitle_plan = plan.get("subtitle_plan") or {}
    subtitles_enabled = bool(subtitle_plan.get("enabled"))
    if subtitles_enabled != (subtitle_choice == "enabled"):
        errors.append("subtitle_plan.enabled does not match the confirmed subtitle choice")
    if subtitles_enabled:
        errors.extend(enabled_subtitle_contract_errors(subtitle_plan, prefix="Enabled subtitles"))
        if not subtitle_plan.get("srt_output") or not subtitle_plan.get("burned_video_output") or not subtitle_plan.get("clean_video_output"):
            errors.append("enabled subtitles require clean, SRT, and captioned output paths")
        if not (subtitle_plan.get("profile") or {}).get("id"):
            errors.append("enabled subtitles require a platform subtitle profile")
    elif subtitle_plan.get("srt_output") or subtitle_plan.get("burned_video_output") or subtitle_plan.get("clean_video_output"):
        errors.append("disabled subtitles must not declare SRT, clean-caption staging, or captioned-video outputs")
    effects_plan = plan.get("effects_plan") or {}
    broll_entries = (plan.get("broll_plan") or {}).get("entries") or []
    if effects_choice == "disabled" and effects_plan.get("enabled"):
        errors.append("effects choice is disabled but effects_plan.enabled=true")
    if effects_choice == "disabled" and broll_entries:
        errors.append("B-roll is present while effects are disabled")
    if effects_choice == "enabled" and not effects_plan.get("approved_effects"):
        errors.append("effects are enabled but no approved effects were recorded")
    if effects_plan.get("caption_mask_allowed") is not False:
        errors.append("effects_plan.caption_mask_allowed must be false")
    duration_plan = plan.get("duration_plan") or {}
    if duration_plan.get("confirmation_status") != "confirmed":
        errors.append("final duration is not user confirmed")
    if plan.get("source_fact_map_required") and not (plan.get("source_fact_map") or []):
        errors.append("source_fact_map is required for this factual source-based project and cannot be empty")
    for fact in plan.get("source_fact_map") or []:
        status = str(fact.get("verification_status") or "").strip()
        if status != "verified":
            errors.append(
                f"source_fact_map {fact.get('fact_id') or 'unknown fact'} verification_status={status or 'missing'}; "
                "all factual claims must be verified before paid generation"
            )
    business = plan.get("business_context") or {}
    if str(business.get("scenario") or "").strip():
        for field in ("user_intent", "success_metric", "risk_boundary"):
            if not str(business.get(field) or "").strip():
                errors.append(f"business_context.{field} is required when a business scenario is selected")
    if infer_execution_route(plan) == "postproduction_only" and not plan.get("existing_video_file"):
        errors.append("postproduction_only route requires existing_video_file")
    if infer_execution_route(plan) == "postproduction_only":
        postproduction = plan.get("postproduction_plan") or {}
        if not postproduction.get("enabled") or not postproduction.get("candidate_output"):
            errors.append("postproduction_only route requires an enabled postproduction_plan and candidate_output")
        if int(postproduction.get("paid_video_generation_requests") or 0) != 0:
            errors.append("postproduction_only route must declare zero paid video generation requests")
    localization = plan.get("localization_contract") or {}
    if localization.get("enabled"):
        for field in ("source_language", "target_language", "target_locale"):
            if not str(localization.get(field) or "").strip():
                errors.append(f"localization_contract.{field} is required")
        if localization.get("translation_review_status") != "verified":
            errors.append(
                f"localization_contract.translation_review_status={localization.get('translation_review_status') or 'missing'}; "
                "localized script and glossary require confirmation before paid generation"
            )
        current_script_digest = hashlib.sha256(str(plan.get("script_text") or "").encode("utf-8")).hexdigest()
        if localization.get("localized_script_sha256") != current_script_digest:
            errors.append("localization_contract.localized_script_sha256 does not match the current localized script")
        glossary = localization.get("glossary_file") or {}
        if glossary.get("value"):
            glossary_path = Path(glossary["value"]).expanduser().resolve()
            if not glossary_path.exists():
                errors.append("localization glossary file is missing")
            elif localization.get("glossary_sha256") != hashlib.sha256(glossary_path.read_bytes()).hexdigest():
                errors.append("localization_contract.glossary_sha256 does not match the current glossary")
        plan_language = str(plan.get("language") or "").lower().replace("_", "-").split("-", 1)[0]
        target_language = str(localization.get("target_language") or "").lower().replace("_", "-").split("-", 1)[0]
        if plan_language and target_language and plan_language != target_language:
            errors.append("plan language does not match localization_contract.target_language")
    req = plan.get("generation_requirements") or {}
    caps = plan.get("model_capabilities") or {}
    if req.get("lipsync_required") and not caps.get("supports_lipsync"):
        warnings.append("Strict lip sync is requested but selected model does not support lipsync.")
    if req.get("lipsync_required") and not (caps.get("supports_audio_input") or caps.get("supports_script_to_speech")):
        warnings.append("Strict lip sync is requested but selected model cannot use audio input or script-to-speech.")
    if plan.get("audio_file") and req.get("tts_required"):
        errors.append("audio_file exists but tts_required=true; existing audio should avoid forced TTS")
    shots = plan.get("shots") or []
    if duration_plan:
        delivery_max = int(duration_plan.get("delivery_max_seconds") or 0)
        if int(duration_plan.get("segment_count") or 0) != len(shots):
            errors.append("duration_plan.segment_count does not match planned shots")
        request_durations = [int(shot.get("duration_seconds") or 0) for shot in shots]
        if duration_plan.get("request_duration_seconds") != request_durations:
            errors.append("duration_plan.request_duration_seconds does not match planned shots")
        if int(duration_plan.get("planned_request_total_seconds") or 0) != sum(request_durations):
            errors.append("duration_plan.planned_request_total_seconds does not match planned shots")
        allowed_durations = [int(value) for value in (duration_plan.get("allowed_request_durations_seconds") or [])]
        if allowed_durations:
            for shot, request_duration in zip(shots, request_durations):
                if request_duration not in allowed_durations:
                    errors.append(
                        f"{shot.get('id', 'unknown shot')} duration {request_duration}s is not in "
                        f"allowed_request_durations_seconds={allowed_durations}"
                    )
            if delivery_max:
                deterministic_model = {
                    "allowed_durations_seconds": allowed_durations,
                    "min_duration_seconds": min(allowed_durations),
                    "max_duration_seconds": max(allowed_durations),
                }
                expected_slots = plan_request_durations(delivery_max, deterministic_model)
                if len(request_durations) != len(expected_slots) or any(
                    actual < minimum_slot for actual, minimum_slot in zip(request_durations, expected_slots)
                ):
                    errors.append(
                        f"request durations {request_durations} do not meet deterministic request slots "
                        f"{expected_slots} for delivery_max_seconds={delivery_max}"
                    )
        if enforce_script_pacing:
            for shot in shots[:-1]:
                semantic_issue = semantic_boundary_issue(str(shot.get("script_segment") or ""))
                if semantic_issue:
                    errors.append(
                        f"{shot.get('id', 'unknown shot')} is not a semantic complete strong sentence boundary: "
                        f"{semantic_issue}"
                    )
        digest_payload = duration_plan.get("duration_plan_digest_payload") or {}
        recorded_digest = str(duration_plan.get("duration_plan_digest") or "")
        root_digest = str(plan.get("duration_plan_digest") or "")
        if not digest_payload or not recorded_digest:
            errors.append("duration_plan digest payload or digest is missing")
        else:
            canonical_payload = json.dumps(
                digest_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            calculated_digest = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
            if recorded_digest != calculated_digest:
                errors.append("duration_plan.duration_plan_digest does not match its canonical payload")
            if root_digest != recorded_digest:
                errors.append("root duration_plan_digest does not match duration_plan.duration_plan_digest")
            expected_segments = [
                {
                    "index": index,
                    "request_duration_seconds": request_duration,
                    "script": str(shot.get("script_segment") or ""),
                }
                for index, (shot, request_duration) in enumerate(zip(shots, request_durations), start=1)
            ]
            if digest_payload.get("delivery_max_seconds") != duration_plan.get("delivery_max_seconds"):
                errors.append("duration plan digest payload delivery cap does not match duration_plan")
            if digest_payload.get("allowed_durations_seconds") != allowed_durations:
                errors.append("duration plan digest payload allowed slots do not match duration_plan")
            if digest_payload.get("segment_count") != len(shots):
                errors.append("duration plan digest payload segment count does not match shots")
            if digest_payload.get("request_duration_seconds") != request_durations:
                errors.append("duration plan digest payload request durations do not match shots")
            if digest_payload.get("segments") != expected_segments:
                errors.append("duration plan digest payload exact segment scripts or slots do not match shots")
            payload_model = digest_payload.get("model") or {}
            if payload_model.get("key") != plan.get("model_key") or payload_model.get("model") != plan.get("model"):
                errors.append("duration plan digest payload model does not match generation plan")
        minimum_count = int(duration_plan.get("minimum_paid_segment_count") or 0)
        if minimum_count and len(shots) != minimum_count:
            errors.append(
                f"plan creates {len(shots)} paid segments but must exactly match minimum_paid_segment_count={minimum_count}"
            )
        if delivery_max and int(plan.get("delivery_duration_seconds") or 0) != delivery_max:
            errors.append("delivery_duration_seconds must equal duration_plan.delivery_max_seconds")
        expected_overshoot = max(0, sum(request_durations) - delivery_max) if delivery_max else 0
        if int(duration_plan.get("planned_delivery_overshoot_seconds") or 0) != expected_overshoot:
            errors.append("duration_plan.planned_delivery_overshoot_seconds is inconsistent with request total and delivery cap")
        estimated_spoken = round(
            sum(float((shot.get("script_pacing") or {}).get("estimated_spoken_seconds") or 0) for shot in shots),
            2,
        )
        if len(shots) > 1 and delivery_max and any(str(shot.get("script_segment") or "").strip() for shot in shots):
            fill_ratio = estimated_spoken / float(delivery_max)
            if fill_ratio + 1e-9 < MINIMUM_MULTI_SEGMENT_SPOKEN_FILL_RATIO:
                errors.append(
                    f"multi-segment script spoken fill {fill_ratio:.0%} is below the required "
                    f"{MINIMUM_MULTI_SEGMENT_SPOKEN_FILL_RATIO:.0%} minimum for delivery_max_seconds={delivery_max}; "
                    "professionally rewrite toward 85%-95% or confirm a shorter delivery duration"
                )
        natural_pause = round(
            sum(
                float((shot.get("script_pacing") or {}).get("head_padding_seconds") or 0)
                + float((shot.get("script_pacing") or {}).get("tail_padding_seconds") or 0)
                for shot in shots
                if float((shot.get("script_pacing") or {}).get("estimated_spoken_seconds") or 0) > 0
            ),
            2,
        )
        estimated_delivery = round(estimated_spoken + natural_pause, 2)
        expected_trim = round(max(0.0, sum(request_durations) - estimated_delivery), 2)
        if abs(float(duration_plan.get("planned_trim_seconds") or 0) - expected_trim) > 0.01:
            errors.append("duration_plan.planned_trim_seconds must represent removable idle request time")
        if abs(float(duration_plan.get("estimated_delivery_seconds") or 0) - estimated_delivery) > 0.01:
            errors.append("duration_plan.estimated_delivery_seconds is inconsistent with speech and natural pauses")
        if delivery_max and estimated_delivery > delivery_max:
            errors.append(
                f"estimated speech plus natural pauses {estimated_delivery}s exceeds delivery_max_seconds={delivery_max}"
            )
        if duration_plan.get("delivery_fit_status") not in {"ok", "revise"}:
            errors.append("duration_plan.delivery_fit_status must be ok or revise")
        elif delivery_max and duration_plan.get("delivery_fit_status") != ("ok" if estimated_delivery <= delivery_max else "revise"):
            errors.append("duration_plan.delivery_fit_status is inconsistent with estimated delivery and delivery cap")
        maximum = int(duration_plan.get("model_max_segment_seconds") or 0)
        planned = int(duration_plan.get("planned_duration_seconds") or 0)
        if (
            maximum
            and planned <= maximum
            and len(shots) > 1
            and duration_plan.get("segmentation_reason") != "explicit_user_confirmed_segments"
        ):
            errors.append("duration fits one model request but the plan created unnecessary multiple segments")
    image_plan = plan.get("image_consistency_plan") or {}
    if not image_plan.get("strategy"):
        errors.append("image_consistency_plan is missing strategy")
    if len(shots) > 1:
        strategy = plan.get("longform_generation_strategy") or {}
        stitching = plan.get("stitching_plan") or {}
        if not plan.get("visual_bible"):
            errors.append("multi-segment plan is missing visual_bible")
        if not strategy.get("requires_multi_segment") or strategy.get("segment_count") != len(shots):
            errors.append("multi-segment plan has an invalid longform_generation_strategy")
        if not stitching.get("required") or not stitching.get("clip_order"):
            errors.append("multi-segment plan is missing a required stitching_plan")
        if image_plan.get("strategy") == "per_segment_source_frames" and int(image_plan.get("segment_source_count") or 0) != len(shots):
            errors.append("per_segment_source_frames requires one segment source image per shot")
        if image_plan.get("strategy") == "per_segment_source_frames":
            expected_indices = list(range(1, len(shots) + 1))
            actual_indices = sorted(int(value) for value in (image_plan.get("segment_source_indices") or []))
            if actual_indices != expected_indices:
                errors.append(f"per_segment_source_frames indices {actual_indices} do not match expected {expected_indices}")
        for shot in shots:
            if not shot.get("continuity_contract"):
                errors.append(f"{shot.get('id', 'unknown shot')} is missing continuity_contract")
            if not shot.get("visual_bible"):
                errors.append(f"{shot.get('id', 'unknown shot')} is missing visual_bible")
            if not shot.get("script_pacing"):
                errors.append(f"{shot.get('id', 'unknown shot')} is missing script_pacing")
            if not shot.get("script_boundary"):
                errors.append(f"{shot.get('id', 'unknown shot')} is missing script_boundary")
    pacing_errors, pacing_warnings = validate_script_pacing(plan, enforce_script_pacing)
    errors.extend(pacing_errors)
    warnings.extend(pacing_warnings)
    boundary_errors, boundary_warnings = validate_script_boundaries(plan, enforce_script_pacing)
    errors.extend(boundary_errors)
    warnings.extend(boundary_warnings)
    blocking_reasons = plan.get("blocking_reasons") or []
    if blocking_reasons:
        warnings.extend(str(reason) for reason in blocking_reasons)
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--enforce-script-pacing", action="store_true", help="Fail only when segment speech is missing or exceeds the model-safe duration; short complete speech is trim-safe.")
    args = parser.parse_args()
    try:
        plan_path = Path(args.plan).expanduser().resolve()
        plan = load_json(plan_path)
        errors, warnings = validate_plan(plan, enforce_script_pacing=args.enforce_script_pacing)
        result = {
            "ok": not errors,
            "plan": str(plan_path),
            "errors": errors,
            "warnings": warnings,
            "script_pacing_enforced": bool(args.enforce_script_pacing),
            "ready_for_paid_generation": bool(plan.get("ready_for_paid_generation")) and not errors,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not errors else 1
    except ScriptError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
