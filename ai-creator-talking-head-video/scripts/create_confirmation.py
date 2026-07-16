#!/usr/bin/env python3
"""Bind the second user confirmation and exact image digests to a production contract."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from _common import ScriptError, load_json
from _workflow import atomic_write_json


PAYLOAD_IMAGE_ROLES = {"avatar_reference", "video_source", "first_frame", "segment_source"}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def confirmation_equivalent(existing: dict, desired: dict) -> bool:
    def normalized(value: dict) -> dict:
        result = json.loads(json.dumps(value))
        result.pop("approved_at", None)
        result["confirmed_asset_digests"] = sorted(result.get("confirmed_asset_digests") or [])
        return result

    return normalized(existing) == normalized(desired)


def confirmation_result(output: Path, confirmation: dict, expected_requests: int, idempotent: bool) -> dict:
    return {
        "ok": True,
        "idempotent": idempotent,
        "confirmation_file": str(output),
        "contract_digest": confirmation.get("contract_digest"),
        "confirmation_stage": confirmation.get("confirmation_stage"),
        "confirmed_asset_digests": confirmation.get("confirmed_asset_digests") or [],
        "confirmed_duration_plan_digest": confirmation.get("confirmed_duration_plan_digest"),
        "max_paid_submissions": confirmation.get("max_paid_submissions"),
        "base_paid_request_count": expected_requests,
        "repair_reserve_paid_submissions": 0,
        "autonomous_execution": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--confirmation-intent")
    parser.add_argument("--confirmed-asset-digest", action="append", default=[])
    parser.add_argument("--confirmed-duration-plan-digest")
    parser.add_argument("--max-paid-submissions", type=int)
    parser.add_argument("--per-shot-repair-limit", type=int, default=0)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        contract_path = Path(args.contract).expanduser().resolve()
        project_dir = contract_path.parent
        contract = load_json(contract_path)
        preflight_path = project_dir / "preflight-report.json"
        preflight = load_json(preflight_path)
        if not preflight.get("ok"):
            raise ScriptError("Cannot confirm paid generation because preflight-report.json is not pass")
        if Path(preflight.get("contract_file") or "").expanduser().resolve() != contract_path:
            raise ScriptError("Preflight report does not reference this production contract")
        digest = str(contract.get("contract_digest") or "")
        if not digest:
            raise ScriptError("Production contract is missing contract_digest")
        approved_by = args.approved_by.strip()
        if not approved_by:
            raise ScriptError("approved_by cannot be empty")
        if args.confirmation_intent != "confirm_images_and_start":
            raise ScriptError(
                "Paid production requires the second user confirmation intent confirm_images_and_start; plan approval alone is insufficient"
            )
        contract_duration_plan_digest = str(contract.get("duration_plan_digest") or "")
        confirmed_duration_plan_digest = str(args.confirmed_duration_plan_digest or "").strip().lower()
        if not SHA256_PATTERN.fullmatch(contract_duration_plan_digest):
            raise ScriptError("Production contract is missing a valid duration plan digest")
        if not confirmed_duration_plan_digest:
            raise ScriptError("Paid production requires the first-stage confirmed duration plan digest")
        if not SHA256_PATTERN.fullmatch(confirmed_duration_plan_digest):
            raise ScriptError("Confirmed duration plan digest must be a 64-character lowercase SHA-256")
        if confirmed_duration_plan_digest != contract_duration_plan_digest:
            raise ScriptError("Confirmed duration plan digest does not match the production contract duration plan digest")
        confirmed_asset_digests = [str(item).strip().lower() for item in args.confirmed_asset_digest]
        if not confirmed_asset_digests:
            raise ScriptError("Paid production requires confirmed SHA-256 digests for the exact displayed video payload images")
        if len(confirmed_asset_digests) != len(set(confirmed_asset_digests)):
            raise ScriptError("confirmed asset digests must be unique")
        invalid_digests = [item for item in confirmed_asset_digests if not SHA256_PATTERN.fullmatch(item)]
        if invalid_digests:
            raise ScriptError("Every confirmed asset digest must be a 64-character lowercase SHA-256")
        contract_image_digests = [
            str(item.get("sha256") or "").lower()
            for item in (contract.get("asset_fingerprints") or [])
            if item.get("role") in PAYLOAD_IMAGE_ROLES and item.get("sha256")
        ]
        if not contract_image_digests:
            raise ScriptError("Production contract has no fingerprinted video payload image to confirm")
        if set(confirmed_asset_digests) != set(contract_image_digests):
            raise ScriptError("Confirmed image digests do not exactly match the production contract video payload images")
        expected_requests = len(contract.get("dry_run_requests") or [])
        max_paid_submissions = (
            expected_requests
            if args.max_paid_submissions is None
            else int(args.max_paid_submissions)
        )
        if max_paid_submissions <= 0:
            raise ScriptError("max_paid_submissions must be greater than zero")
        if max_paid_submissions != expected_requests:
            raise ScriptError(
                f"max_paid_submissions must equal the {expected_requests} base paid request(s); "
                "paid retry/regeneration is not authorized by the normal workflow"
            )
        per_shot_repair_limit = int(args.per_shot_repair_limit)
        if per_shot_repair_limit != 0:
            raise ScriptError("per_shot_repair_limit must be 0 because automatic paid regeneration is disabled")
        repair_reserve = 0
        output = Path(args.output).expanduser().resolve() if args.output else project_dir / "video-confirmation.json"
        confirmation = {
            "version": "1.0",
            "confirmation_stage": "production_authorized",
            "plan_confirmed": True,
            "image_assets_confirmed": True,
            "video_generation_confirmed": True,
            "single_production_package_confirmed": True,
            "two_confirmation_package_confirmed": True,
            "image_confirmation_intent": "confirm_images_and_start",
            "confirmed_asset_digests": confirmed_asset_digests,
            "confirmed_duration_plan_digest": confirmed_duration_plan_digest,
            "contract_digest": digest,
            "contract_file": str(contract_path),
            "approved_by": approved_by,
            "approved_at": int(time.time()),
            "max_paid_submissions": max_paid_submissions,
            "approval_scope": "plan_then_exact_images_then_base_paid_requests_and_no_cost_postprocess",
            "autonomous_execution": {
                "enabled": True,
                "no_additional_confirmation_for_approved_actions": True,
                "base_paid_request_count": expected_requests,
                "repair_reserve_paid_submissions": repair_reserve,
                "per_shot_repair_limit": per_shot_repair_limit,
                "allow_no_cost_repairs": True,
                "allow_terminal_provider_retry_within_paid_cap": False,
                "allow_quality_regeneration_within_paid_cap": False,
                "allow_ambiguous_submission_retry": False,
                "stop_conditions": [
                    "production_contract_drift",
                    "approved_paid_cap_exhausted",
                    "ambiguous_paid_submission_without_verified_idempotency",
                    "unrecoverable_safety_rights_or_source_fact_issue",
                    "provider_or_auth_outage_without_safe_recovery",
                ],
            },
        }
        standard_confirmation = project_dir / "video-confirmation.json"
        if standard_confirmation.exists() and standard_confirmation.resolve() != output.resolve():
            raise ScriptError("video-confirmation.json already exists; create_confirmation cannot write a second confirmation file")
        jobs_path = project_dir / "jobs.json"
        jobs = load_json(jobs_path) if jobs_path.exists() else {}
        paid_attempts = int(jobs.get("paid_submission_attempts") or 0)
        if output.exists():
            existing = load_json(output)
            if confirmation_equivalent(existing, confirmation):
                print(json.dumps(confirmation_result(output, existing, expected_requests, idempotent=True), ensure_ascii=False, indent=2))
                return 0
            paid_suffix = " after paid submission" if paid_attempts > 0 else ""
            raise ScriptError(
                f"create_confirmation cannot overwrite the existing video confirmation{paid_suffix}; "
                "create a new independently confirmed project"
            )
        if paid_attempts > 0:
            raise ScriptError("Cannot create or overwrite video confirmation after paid submission has started")
        atomic_write_json(output, confirmation)
        print(json.dumps(confirmation_result(output, confirmation, expected_requests, idempotent=False), ensure_ascii=False, indent=2))
        return 0
    except (ScriptError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
