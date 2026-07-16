#!/usr/bin/env python3
"""Create dry-run payloads or submit confirmed talking-head video requests."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from _common import ScriptError, asset_value, find_api_key, get_model_config, http_json, join_url, load_config, load_json, media_url, model_api_key_names, write_json
from _workflow import acquire_paid_submission_lock, canonical_digest, load_or_create_jobs, record_submission_attempt, redact_model_snapshot, release_paid_submission_lock, transition_job, verify_contract
from _routing import infer_execution_route


REFERENCE_ROLES = {"avatar_reference", "scene_reference", "video_source", "first_frame", "segment_source", "storyboard", "storyboard_sheet", "last_frame", "broll_reference", "cover"}
PAYLOAD_IMAGE_ROLES = {"avatar_reference", "video_source", "first_frame", "segment_source"}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def second_confirmation_digests(confirmation: dict) -> list[str]:
    if confirmation.get("confirmation_stage") != "production_authorized":
        raise ScriptError("Refusing paid API call without confirmation_stage=production_authorized from the second user confirmation.")
    if not confirmation.get("plan_confirmed") or not confirmation.get("two_confirmation_package_confirmed"):
        raise ScriptError("Refusing paid API call because the two-confirmation package is incomplete.")
    if confirmation.get("image_confirmation_intent") != "confirm_images_and_start":
        raise ScriptError("Refusing paid API call without image confirmation intent confirm_images_and_start.")
    digests = [str(item).strip().lower() for item in (confirmation.get("confirmed_asset_digests") or [])]
    if not digests or len(digests) != len(set(digests)) or any(not SHA256_PATTERN.fullmatch(item) for item in digests):
        raise ScriptError("Refusing paid API call without unique 64-character SHA-256 digests for confirmed payload images.")
    return digests


def verify_confirmed_images_match_contract(confirmation: dict, contract: dict) -> None:
    confirmed = set(second_confirmation_digests(confirmation))
    expected = {
        str(item.get("sha256") or "").lower()
        for item in (contract.get("asset_fingerprints") or [])
        if item.get("role") in PAYLOAD_IMAGE_ROLES and item.get("sha256")
    }
    if not expected or confirmed != expected:
        raise ScriptError("Refusing paid API call because confirmed image digests do not exactly match the production contract payload images.")


def verify_confirmed_duration_plan(confirmation: dict, contract: dict, plan: dict) -> None:
    confirmed = str(confirmation.get("confirmed_duration_plan_digest") or "").strip().lower()
    contracted = str(contract.get("duration_plan_digest") or "").strip().lower()
    planned = str(
        plan.get("duration_plan_digest")
        or (plan.get("duration_plan") or {}).get("duration_plan_digest")
        or ""
    ).strip().lower()
    if not all(SHA256_PATTERN.fullmatch(item) for item in (confirmed, contracted, planned)):
        raise ScriptError("Refusing paid API call because the confirmed, contracted, or current duration plan digest is missing or invalid.")
    if confirmed != contracted or contracted != planned:
        raise ScriptError("Refusing paid API call because the confirmed duration plan digest does not match the production contract and current plan.")


def selected_shots(plan: dict, shot_id: str | None) -> list[dict]:
    shots = plan.get("shots") or []
    if shot_id:
        shots = [shot for shot in shots if shot.get("id") == shot_id]
        if not shots:
            raise ScriptError(f"Shot not found in plan: {shot_id}")
    return shots


def resolve_confirmation(args, contract_digest: str = "") -> dict:
    if args.dry_run:
        return {"confirmed": False, "source": "dry_run"}
    if args.confirmation_file:
        path = Path(args.confirmation_file).expanduser().resolve()
        confirmation = load_json(path)
        if not confirmation.get("image_assets_confirmed") or not (confirmation.get("video_generation_confirmed") or confirmation.get("confirmed")):
            raise ScriptError("Refusing paid API call without image_assets_confirmed=true and video_generation_confirmed=true.")
        second_confirmation_digests(confirmation)
        if not contract_digest or confirmation.get("contract_digest") != contract_digest:
            raise ScriptError("Refusing paid API call because the confirmation does not match the current production contract.")
        return {
            "confirmed": True,
            "source": "confirmation_file",
            "confirmation_file": str(path),
            "approved_by": confirmation.get("approved_by", ""),
            "approved_at": confirmation.get("approved_at", ""),
            "confirmation_stage": confirmation.get("confirmation_stage", ""),
            "image_confirmation_intent": confirmation.get("image_confirmation_intent", ""),
            "confirmed_asset_digests": confirmation.get("confirmed_asset_digests", []),
            "confirmed_duration_plan_digest": confirmation.get("confirmed_duration_plan_digest", ""),
        }
    if args.confirmed:
        raise ScriptError("Refusing paid API call with --confirmed only. Use a contract-bound --confirmation-file after preflight and user approval.")
    raise ScriptError("Refusing paid API call without explicit final confirmation. Use --confirmation-file after user approval.")


def payload_media(asset: dict | None) -> str | None:
    if not asset:
        return None
    return media_url(asset)


def formatted_media_payload(asset: dict, payload_format: str | None):
    url = payload_media(asset)
    normalized = (payload_format or "url_string").strip().lower()
    if normalized in {"url_array", "array", "url_strings", "string_urls"}:
        return [url]
    if normalized in {"url_object", "object"}:
        return {"url": url}
    if normalized in {"input_reference", "input_reference_object"}:
        return {"image_url": url}
    return url


def formatted_reference_payload(asset: dict, model: dict):
    url = payload_media(asset)
    normalized = (model.get("reference_payload_format") or "url_strings").strip().lower()
    if normalized in {"url_objects", "object_urls"}:
        return {"url": url}
    if normalized in {"role_url_objects", "role_url"}:
        return {"role": asset.get("role", "reference"), "url": url}
    if normalized in {"nested_image_objects", "nested_image"}:
        return {"role": asset.get("role", "reference"), "image": {"url": url}}
    return url


def merge_payload_field(payload: dict, field: str, value) -> None:
    if field not in payload:
        payload[field] = value
        return
    existing = payload[field]
    existing_items = existing if isinstance(existing, list) else [existing]
    new_items = value if isinstance(value, list) else [value]
    payload[field] = existing_items + new_items


def model_supports_references(model: dict) -> bool:
    return bool(model.get("supports_reference_images"))


def confirmed_reference_assets(plan: dict, shot: dict, model: dict, source_asset: dict | None) -> list[dict]:
    if not model_supports_references(model):
        return []
    assets = []
    candidates = list(shot.get("confirmed_assets") or plan.get("confirmed_assets") or []) + list(plan.get("references") or [])
    source_value = asset_value(source_asset)
    seen = {source_value} if source_value else set()
    shot_segment_index = shot.get("segment_index")
    for asset in candidates:
        if asset.get("role") in REFERENCE_ROLES:
            if asset.get("role") == "segment_source" and asset.get("segment_index") and asset.get("segment_index") != shot_segment_index:
                continue
            value = asset_value(asset)
            if value in seen:
                continue
            seen.add(value)
            assets.append(asset)
    max_refs = int(model.get("max_reference_images") or len(assets) or 0)
    if len(assets) > max_refs:
        raise ScriptError(f"Selected model accepts at most {max_refs} reference image(s), but {len(assets)} confirmed references were prepared.")
    return assets


def first_asset_by_role(plan: dict, roles: set[str]) -> dict | None:
    for asset in plan.get("confirmed_assets") or []:
        if asset.get("role") in roles:
            return asset
    if plan.get("avatar_reference") and "avatar_reference" in roles:
        return plan.get("avatar_reference")
    return None


def source_asset_for_shot(plan: dict, shot: dict) -> dict | None:
    if isinstance(shot.get("segment_source_asset"), dict):
        return shot["segment_source_asset"]
    return first_asset_by_role(plan, {"video_source", "first_frame", "segment_source", "avatar_reference", "scene_reference", "cover"})


def selected_shots_for_submission(
    plan: dict,
    ledger: dict,
    shot_id: str | None,
    retry_failed_shot: str | None = None,
    regenerate_shot: str | None = None,
) -> tuple[list[dict], list[dict]]:
    selected = []
    skipped = []
    terminal_or_inflight = {"submitting", "submitted", "polling", "downloaded", "verified"}
    for shot in selected_shots(plan, shot_id):
        job = (ledger.get("jobs") or {}).get(shot.get("id")) or {}
        state = str(job.get("state") or "planned")
        is_legacy_paid_retry = retry_failed_shot == shot.get("id") or regenerate_shot == shot.get("id")
        if is_legacy_paid_retry and (
            state in {"failed", "verified"} or int(job.get("submission_attempts") or 0) > 0
        ):
            skipped.append({
                "shot_id": shot.get("id"),
                "state": state,
                "reason": "second_paid_submission_disabled",
            })
        elif state in terminal_or_inflight:
            skipped.append({"shot_id": shot.get("id"), "state": state, "reason": "already_inflight_or_complete"})
        elif state == "failed":
            if job.get("request_id"):
                skipped.append({
                    "shot_id": shot.get("id"),
                    "state": state,
                    "reason": "existing_request_id_requires_poll_or_user_decision",
                })
            elif int(job.get("submission_attempts") or 0) > 0:
                skipped.append({
                    "shot_id": shot.get("id"),
                    "state": state,
                    "reason": "second_paid_submission_disabled",
                })
            else:
                selected.append(shot)
        else:
            selected.append(shot)
    return selected, skipped


def ensure_submission_budget(ledger: dict, shots: list[dict]) -> None:
    attempts = int(ledger.get("paid_submission_attempts") or 0)
    maximum = int(ledger.get("max_paid_submissions") or 0)
    remaining = maximum - attempts
    if len(shots) > remaining:
        raise ScriptError(
            f"Paid submission budget is insufficient for the selected shots: need {len(shots)}, remaining {remaining}. "
            "Select fewer shots or create a newly approved production run with a sufficient cap."
        )


def load_dry_run_records(project_dir: Path, plan: dict) -> list[dict]:
    records = []
    for shot in plan.get("shots") or []:
        path = project_dir / "requests" / "dry-run" / f"{shot.get('id')}.json"
        if not path.exists():
            raise ScriptError(f"Missing contract dry-run request: {path}")
        records.append(load_json(path))
    return records


def build_payload(plan: dict, shot: dict, model: dict) -> tuple[dict, dict]:
    requirements = plan.get("generation_requirements") or {}
    lipsync_required = bool(requirements.get("lipsync_required"))
    lipsync_supported = bool(model.get("supports_lipsync") and (model.get("supports_audio_input") or model.get("supports_script_to_speech")))
    prompt = shot.get("prompt") or plan.get("script_text") or ""
    duration_field = model.get("duration_field") or "duration"
    payload = {
        "prompt": prompt,
        "aspect_ratio": plan.get("aspect_ratio") or model.get("default_aspect_ratio", "9:16"),
        "resolution": plan.get("resolution") or model.get("default_resolution", "1080p"),
    }
    if not model.get("omit_model_from_payload"):
        payload["model"] = model.get("model")
    if isinstance(model.get("payload_defaults"), dict):
        payload.update(model["payload_defaults"])
    payload[duration_field] = int(shot.get("duration_seconds") or model.get("default_duration_seconds") or 15)

    source_asset = source_asset_for_shot(plan, shot)
    source_included = False
    if source_asset and model.get("supports_image_to_video"):
        merge_payload_field(payload, model.get("source_image_field") or "image", formatted_media_payload(source_asset, model.get("source_payload_format")))
        source_included = True

    references = confirmed_reference_assets(plan, shot, model, source_asset)
    if references:
        merge_payload_field(payload, model.get("reference_field") or "reference_images", [formatted_reference_payload(asset, model) for asset in references])

    audio_asset = plan.get("audio_file")
    audio_included = False
    if audio_asset and model.get("supports_audio_input") and model.get("audio_field"):
        merge_payload_field(payload, model["audio_field"], formatted_media_payload(audio_asset, model.get("audio_payload_format") or "url_string"))
        audio_included = True

    subtitle_included = False

    trace = {
        "confirmed_asset_roles": [asset.get("role") for asset in plan.get("confirmed_assets") or []],
        "source_asset": {"role": source_asset.get("role"), "value": asset_value(source_asset)} if source_asset else None,
        "source_asset_id": source_asset.get("id") if source_asset else "",
        "source_asset_segment_index": source_asset.get("segment_index") if source_asset else None,
        "source_included_in_payload": source_included,
        "reference_count": len(references),
        "reference_roles": [asset.get("role") for asset in references],
        "audio_included_in_payload": audio_included,
        "subtitle_included_in_payload": subtitle_included,
        "subtitle_policy": "never_send_to_provider_postproduction_only",
        "lipsync_required": lipsync_required,
        "lipsync_supported": lipsync_supported,
        "warnings": plan.get("warnings") or [],
    }
    return payload, trace


def normalize_submit_response(data: dict, shot_id: str) -> dict:
    body = data.get("data") if isinstance(data.get("data"), dict) else data
    request_id = body.get("task_id") or body.get("request_id") or body.get("id") or data.get("task_id") or data.get("request_id") or data.get("id")
    if not request_id:
        raise ScriptError(f"Submit response missing request id for {shot_id}: {data}")
    return {
        "request_id": request_id,
        "task_id": request_id,
        "status_url": body.get("status_url") or data.get("status_url"),
        "response_url": body.get("response_url") or data.get("response_url"),
        "raw_response": data,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--config")
    parser.add_argument("--model-key")
    parser.add_argument("--shot-id")
    parser.add_argument("--retry-failed-shot", help="Disabled legacy option; paid retries require a new independently confirmed project.")
    parser.add_argument("--regenerate-shot", help="Disabled legacy option; paid regeneration requires a new independently confirmed project.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirmed", action="store_true", help="Deprecated fail-closed compatibility flag; use a contract-bound --confirmation-file.")
    parser.add_argument("--confirmation-file")
    parser.add_argument("--max-paid-submissions", type=int, help="Hard cap for paid generation submissions recorded in jobs.json.")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    submission_lock = None
    try:
        selectors = [item for item in (args.shot_id, args.retry_failed_shot, args.regenerate_shot) if item]
        if len(selectors) > 1:
            raise ScriptError("Use only one of --shot-id, --retry-failed-shot, or --regenerate-shot.")
        if args.retry_failed_shot or args.regenerate_shot:
            raise ScriptError(
                "Paid retry and regeneration flags are disabled. "
                "Use the existing request id for polling/download recovery; a new generation requires a new independently confirmed project."
            )
        if not args.dry_run:
            if args.confirmed:
                raise ScriptError("Refusing paid API call with --confirmed only. Use --confirmation-file after preflight and user approval.")
            if not args.confirmation_file:
                raise ScriptError("Refusing paid API call without explicit final confirmation. Use --confirmation-file after user approval.")
            preliminary_confirmation = load_json(Path(args.confirmation_file).expanduser().resolve())
            if not preliminary_confirmation.get("image_assets_confirmed") or not preliminary_confirmation.get("video_generation_confirmed"):
                raise ScriptError("Refusing paid API call without image_assets_confirmed=true and video_generation_confirmed=true.")
            if not preliminary_confirmation.get("single_production_package_confirmed"):
                raise ScriptError("Refusing paid API call without single_production_package_confirmed=true.")
            second_confirmation_digests(preliminary_confirmation)
        plan_path = Path(args.plan).expanduser().resolve()
        plan = load_json(plan_path)
        project_dir = plan_path.parent
        if not args.dry_run and infer_execution_route(plan) == "postproduction_only":
            raise ScriptError("Refusing paid API call because this is a postproduction_only existing-video project")
        if not args.dry_run:
            submission_lock = acquire_paid_submission_lock(project_dir)
        model_snapshot_path = project_dir / "model-snapshot.json"
        if not args.dry_run and model_snapshot_path.exists():
            model = load_json(model_snapshot_path)
            if args.model_key and args.model_key != model.get("key"):
                raise ScriptError("Paid model override does not match the confirmed model snapshot")
            if args.config:
                supplied = get_model_config(load_config(args.config), args.model_key or plan.get("model_key"))
                if canonical_digest(redact_model_snapshot(supplied)) != canonical_digest(model):
                    raise ScriptError("Paid config does not match the confirmed model snapshot")
        else:
            config = load_config(args.config)
            model = get_model_config(config, args.model_key or plan.get("model_key"))
        if not args.dry_run and not plan.get("ready_for_paid_generation", False):
            reasons = "; ".join(str(reason) for reason in (plan.get("blocking_reasons") or ["plan is not marked ready_for_paid_generation"]))
            raise ScriptError(f"Refusing paid API call because the project is not ready for paid generation: {reasons}")
        contract = None
        ledger = None
        skipped = []
        if args.dry_run:
            confirmation = resolve_confirmation(args)
            shots_to_process = selected_shots(plan, args.shot_id)
        else:
            preflight = load_json(project_dir / "preflight-report.json")
            if not preflight.get("ok"):
                raise ScriptError("Refusing paid API call because preflight-report.json is not pass")
            contract = load_json(project_dir / "production-contract.json")
            verify_confirmed_images_match_contract(preliminary_confirmation, contract)
            verify_confirmed_duration_plan(preliminary_confirmation, contract, plan)
            dry_run_records = load_dry_run_records(project_dir, plan)
            contract_errors = verify_contract(contract, plan, model, dry_run_records)
            if contract_errors:
                raise ScriptError("Refusing paid API call because the production contract changed: " + "; ".join(contract_errors))
            confirmation = resolve_confirmation(args, str(contract.get("contract_digest") or ""))
            budget = (
                len(plan.get("shots") or [])
                if args.max_paid_submissions is None
                else int(args.max_paid_submissions)
            )
            if budget <= 0:
                raise ScriptError("max_paid_submissions must be greater than zero")
            approved_budget = int(preliminary_confirmation.get("max_paid_submissions") or len(contract.get("dry_run_requests") or []))
            if budget != approved_budget:
                raise ScriptError(
                    f"Requested paid submission cap {budget} does not match the confirmed paid submission cap {approved_budget}."
                )
            ledger = load_or_create_jobs(project_dir, plan, contract["contract_digest"], budget)
            selected_shot_id = args.shot_id
            shots_to_process, skipped = selected_shots_for_submission(
                plan,
                ledger,
                selected_shot_id,
                retry_failed_shot=None,
                regenerate_shot=None,
            )
            ensure_submission_budget(ledger, shots_to_process)
            if not shots_to_process:
                print(json.dumps({"ok": True, "results": [], "skipped": skipped}, ensure_ascii=False, indent=2))
                return 0
        requirements = plan.get("generation_requirements") or {}
        if requirements.get("lipsync_required") and not (model.get("supports_lipsync") and (model.get("supports_audio_input") or model.get("supports_script_to_speech"))):
            message = "Strict lip sync is required, but the selected model does not support lipsync with audio or script-to-speech."
            if not args.dry_run:
                raise ScriptError(message)
        submit_url = join_url(model["base_url"], model.get("generation_path", "/video/generations"))
        api_key = None if args.dry_run else find_api_key(required=True, names=model_api_key_names(model))
        auth_scheme = model.get("auth_scheme") or "Bearer"
        results = []
        for shot in shots_to_process:
            payload, trace = build_payload(plan, shot, model)
            job = ((ledger or {}).get("jobs") or {}).get(shot["id"], {})
            next_attempt = int(job.get("submission_attempts") or 0) + 1
            request_file = Path(shot["request_file"]).expanduser().resolve()
            if not args.dry_run and next_attempt > 1:
                request_file = project_dir / "requests" / f"{shot['id']}_attempt_{next_attempt:02d}_request.json"
            record = {
                "shot_id": shot["id"],
                "model_key": model.get("key"),
                "contract_digest": str((contract or {}).get("contract_digest") or ""),
                "provider": model.get("provider"),
                "submit_url": submit_url,
                "payload": payload,
                "asset_trace": trace,
                "confirmation": confirmation,
                "dry_run": bool(args.dry_run),
                "created_at": int(time.time()),
            }
            if args.dry_run:
                record["response"] = {"request_id": f"dry-run-{shot['id']}"}
            else:
                submission_reason = "initial"
                transition_job(project_dir, ledger, shot["id"], "submitting")
                record_submission_attempt(project_dir, ledger, shot["id"], reason=submission_reason)
                try:
                    idempotency_header = str(model.get("idempotency_header") or "Idempotency-Key")
                    idempotency_key = str((ledger.get("jobs") or {}).get(shot["id"], {}).get("idempotency_key") or "")
                    extra_headers = {idempotency_header: idempotency_key} if idempotency_header and idempotency_key else None
                    record["response"] = normalize_submit_response(
                        http_json(
                            "POST",
                            submit_url,
                            api_key,
                            payload,
                            timeout=args.timeout,
                            auth_scheme=auth_scheme,
                            extra_headers=extra_headers,
                        ),
                        shot["id"],
                    )
                except ScriptError as exc:
                    record["response_error"] = str(exc)
                    write_json(request_file, record)
                    transition_job(project_dir, ledger, shot["id"], "failed", last_error=str(exc))
                    raise
            write_json(request_file, record)
            if not args.dry_run:
                transition_job(
                    project_dir,
                    ledger,
                    shot["id"],
                    "submitted",
                    request_id=record["response"]["request_id"],
                    request_file=str(request_file),
                    last_error="",
                )
            results.append({"shot_id": shot["id"], "request_file": str(request_file), "request_id": record["response"]["request_id"], "dry_run": bool(args.dry_run)})
        print(json.dumps({"ok": True, "results": results, "skipped": skipped}, ensure_ascii=False, indent=2))
        return 0
    except ScriptError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    finally:
        release_paid_submission_lock(submission_lock)


if __name__ == "__main__":
    raise SystemExit(main())
