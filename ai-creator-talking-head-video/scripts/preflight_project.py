#!/usr/bin/env python3
"""Run the complete no-cost readiness gate and create a production contract."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from _common import ScriptError, contains_secret, get_model_config, load_config, load_json, model_allowed_durations, require_secure_api_url
from _workflow import atomic_write_json, build_contract, canonical_digest, verify_contract
from _routing import infer_execution_route, uses_external_subtitle_timing
from generate_video import build_payload
from subtitle_runtime import subtitle_runtime_errors
from validate_project import validate_plan


def model_plan_errors(plan: dict, model: dict) -> list[str]:
    errors = []
    route = infer_execution_route(plan)
    if route == "postproduction_only":
        errors.append("postproduction_only route must use the existing-video editing workflow and cannot enter paid video generation")
        return errors
    try:
        require_secure_api_url(str(model.get("base_url") or ""))
    except ScriptError as exc:
        errors.append(str(exc))
    if not model.get("enabled", True):
        errors.append(f"selected model {model.get('key')} is disabled")
    if plan.get("model_key") != model.get("key"):
        errors.append(f"plan model_key {plan.get('model_key')} does not match selected model {model.get('key')}")
    ratios = model.get("supported_aspect_ratios") or []
    if ratios and plan.get("aspect_ratio") not in ratios:
        errors.append(f"aspect_ratio {plan.get('aspect_ratio')} is not in supported_aspect_ratios={ratios}")
    resolutions = model.get("supported_resolutions") or []
    if resolutions and plan.get("resolution") not in resolutions:
        errors.append(f"resolution {plan.get('resolution')} is not in supported_resolutions={resolutions}")
    minimum = int(model.get("min_duration_seconds") or 1)
    maximum = int(model.get("max_duration_seconds") or 0)
    try:
        allowed_durations = model_allowed_durations(model)
    except ScriptError as exc:
        errors.append(str(exc))
        allowed_durations = []
    for shot in plan.get("shots") or []:
        duration = int(shot.get("duration_seconds") or 0)
        if duration < minimum or (maximum and duration > maximum):
            errors.append(f"{shot.get('id')} duration {duration}s is outside model range {minimum}-{maximum}s")
        elif allowed_durations and duration not in allowed_durations:
            errors.append(
                f"{shot.get('id')} duration {duration}s is not a supported request slot; "
                f"allowed durations are {allowed_durations}"
            )
    if route == "external_audio_generation":
        if not plan.get("audio_file"):
            errors.append("external_audio_generation requires audio_file")
        if not model.get("supports_audio_input") or not model.get("audio_field"):
            errors.append("external audio is the timing authority, but selected model supports_audio_input=false or has no audio_field")
    if uses_external_subtitle_timing(plan):
        if not plan.get("subtitle_file"):
            errors.append("external subtitle timing requires subtitle_file")
        errors.append(
            "external subtitle timing cannot drive paid video generation under the Provider no-text policy; "
            "use approved external audio for timing or use subtitles only as offline transcript material"
        )
    if not plan.get("ready_for_paid_generation"):
        errors.extend(str(item) for item in (plan.get("blocking_reasons") or ["plan is not ready_for_paid_generation"]))
    return errors


def build_dry_run_records(plan: dict, model: dict, project_dir: Path, write_records: bool = True) -> tuple[list[dict], list[str]]:
    records = []
    errors = []
    output_dir = project_dir / "requests" / "dry-run"
    output_dir.mkdir(parents=True, exist_ok=True)
    for shot in plan.get("shots") or []:
        try:
            payload, trace = build_payload(plan, shot, model)
            record = {
                "shot_id": shot.get("id"),
                "model_key": model.get("key"),
                "provider": model.get("provider"),
                "payload": payload,
                "asset_trace": trace,
                "dry_run": True,
                "created_at": int(time.time()),
            }
            if contains_secret(json.dumps(record, ensure_ascii=False)):
                raise ScriptError(f"{shot.get('id')} dry-run record appears to contain a secret")
            if write_records:
                atomic_write_json(output_dir / f"{shot.get('id')}.json", record)
            records.append(record)
        except ScriptError as exc:
            errors.append(str(exc))
    return records, errors


def load_existing_dry_run_records(plan: dict, project_dir: Path) -> tuple[list[dict], list[str]]:
    records = []
    errors = []
    for shot in plan.get("shots") or []:
        path = project_dir / "requests" / "dry-run" / f"{shot.get('id')}.json"
        if not path.exists():
            errors.append(f"immutable dry-run request evidence is missing: {path}")
            continue
        try:
            records.append(load_json(path))
        except (ScriptError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"cannot read immutable dry-run request evidence {path}: {exc}")
    return records, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--config")
    parser.add_argument("--model-key")
    args = parser.parse_args()
    try:
        plan_path = Path(args.plan).expanduser().resolve()
        project_dir = plan_path.parent
        plan = load_json(plan_path)
        execution_route = infer_execution_route(plan)
        config = load_config(args.config)
        model = get_model_config(config, args.model_key or plan.get("model_key"))
        postproduction_only = execution_route == "postproduction_only"
        validation_errors, warnings = validate_plan(plan, enforce_script_pacing=not postproduction_only)
        errors = list(validation_errors)
        errors.extend(subtitle_runtime_errors(plan))
        if not postproduction_only:
            errors.extend(model_plan_errors(plan, model))
        records = []
        contract_reused = False
        contract_file = project_dir / "production-contract.json"
        model_snapshot_file = project_dir / "model-snapshot.json"
        if not errors and not postproduction_only:
            records, request_errors = build_dry_run_records(plan, model, project_dir, write_records=False)
            errors.extend(request_errors)
        if not errors and not postproduction_only and len(records) != len(plan.get("shots") or []):
            errors.append(f"dry-run request count {len(records)} does not match shot count {len(plan.get('shots') or [])}")
        if not errors and not postproduction_only:
            contract = build_contract(plan, model, records)
            for fingerprint in contract.get("asset_fingerprints") or []:
                if fingerprint.get("status") in {"missing_value", "missing_file", "remote_unavailable"}:
                    errors.append(
                        f"asset fingerprint failed for {fingerprint.get('role') or fingerprint.get('id')}: "
                        f"{fingerprint.get('status')} {fingerprint.get('error') or fingerprint.get('path') or ''}".strip()
                    )
            if not errors:
                jobs_path = project_dir / "jobs.json"
                confirmation_path = project_dir / "video-confirmation.json"
                jobs = load_json(jobs_path) if jobs_path.exists() else {}
                paid_attempts = int(jobs.get("paid_submission_attempts") or 0)
                protected_state_exists = bool(jobs_path.exists() or confirmation_path.exists())
                if contract_file.exists():
                    existing_contract = load_json(contract_file)
                    same_contract = existing_contract.get("contract_digest") == contract.get("contract_digest")
                    if same_contract:
                        existing_records, immutable_errors = load_existing_dry_run_records(plan, project_dir)
                        errors.extend(immutable_errors)
                        if model_snapshot_file.exists():
                            existing_model_snapshot = load_json(model_snapshot_file)
                            if canonical_digest(existing_model_snapshot) != canonical_digest(existing_contract.get("model_snapshot") or {}):
                                errors.append("immutable model-snapshot.json does not match production-contract.json")
                        else:
                            errors.append("immutable model-snapshot.json is missing")
                        if not immutable_errors:
                            errors.extend(verify_contract(existing_contract, plan, model, existing_records))
                        if not errors:
                            contract = existing_contract
                            records = existing_records
                            contract_reused = True
                    elif paid_attempts > 0:
                        errors.append("production contract is immutable after any paid submission; preflight cannot overwrite it")
                    elif confirmation_path.exists():
                        errors.append("video confirmation already exists; preflight cannot overwrite a changed production contract")
                    elif jobs_path.exists():
                        errors.append("jobs.json already exists; preflight cannot overwrite a changed production contract")
                elif protected_state_exists:
                    errors.append("protected confirmation/jobs state exists without a production contract; preflight cannot reconstruct or overwrite it")

                if not errors and not contract_reused:
                    for record in records:
                        atomic_write_json(
                            project_dir / "requests" / "dry-run" / f"{record.get('shot_id')}.json",
                            record,
                        )
                    atomic_write_json(contract_file, contract)
                    atomic_write_json(model_snapshot_file, contract["model_snapshot"])
        report = {
            "ok": not errors,
            "plan": str(plan_path),
            "plan_digest": canonical_digest(plan),
            "project_dir": str(project_dir),
            "model_key": model.get("key"),
            "execution_route": execution_route,
            "errors": errors,
            "warnings": warnings,
            "expected_paid_requests": 0 if execution_route == "postproduction_only" else len(plan.get("shots") or []),
            "paid_generation_allowed": bool(not postproduction_only and not errors),
            "next_action": (
                "Use the existing-video editing/B-roll/caption workflow; do not run confirm or submit."
                if postproduction_only
                else "Bind the user's existing single-package approval to this matching contract, then submit without a repeated confirmation."
            ),
            "dry_run_request_count": len(records),
            "contract_reused": contract_reused,
            "contract_file": str(contract_file) if not errors and not postproduction_only else "",
            "model_snapshot_file": str(model_snapshot_file) if not errors and not postproduction_only else "",
        }
        atomic_write_json(project_dir / "preflight-report.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not errors else 1
    except (ScriptError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
