#!/usr/bin/env python3
"""Validate the two-confirmation Codex talking-head production flow."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PROPOSAL_MARKERS = (
    "数字人口播视频方案",
    "素材与脚本审查",
    "优化后的完整口播稿",
    "分段、模型与制作方案",
    "图片计划与确认说明",
    "确认方案",
)

PRODUCTION_ACTION_SEQUENCE = (
    "prepare",
    "preflight",
    "confirm",
    "submit",
    "poll",
    "finalize",
    "review",
    "local_postprocess_if_needed",
    "delivery",
)
FORBIDDEN_PAID_REPAIR_ACTIONS = {
    "repair_if_needed",
    "quality_regeneration",
    "regenerate_shot",
    "retry_failed_shot",
    "provider_retry",
    "paid_repair",
}
PAYLOAD_IMAGE_ROLES = {"video_source", "first_frame", "segment_source"}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def looks_like_complete_proposal(text: str) -> bool:
    return all(marker in text for marker in PROPOSAL_MARKERS)


def looks_like_proposal_payload(text: str) -> bool:
    """Recognize both the current proposal and the legacy tool-output failure."""
    return all(marker in text for marker in PROPOSAL_MARKERS[:4])


def _add_once(issues: list[str], issue: str) -> None:
    if issue not in issues:
        issues.append(issue)


def validate_trace(trace: dict) -> dict:
    """Check visible message order, authorization gates, and paid-call timing."""
    issues: list[str] = []
    stages: list[str] = []
    primary_proposal = False
    tool_proposal = False
    plan_confirmed = False
    payload_image_delivered = False
    image_assets_confirmed = False
    paid_video_authorized = False
    production_executed = False
    generated_image_seen = False
    displayed_payload_digests: set[str] = set()
    confirmed_asset_digests: set[str] = set()
    confirmation_intents: list[str] = []
    proposal_duration_plan_digest = ""
    confirmed_duration_plan_digest = ""

    for event in trace.get("events", []):
        event_type = event.get("type")
        stage = str(event.get("stage", ""))
        surface = event.get("surface")
        paid_calls = int(event.get("paid_video_calls", 0) or 0)
        content = event.get("content", [])

        if paid_calls > 0 and not image_assets_confirmed:
            _add_once(issues, "paid_before_image_confirmation")

        if event_type == "assistant_confirmation_request" and paid_video_authorized:
            _add_once(issues, "third_routine_confirmation_requested")

        if event_type == "user_confirmation":
            intent = str(event.get("intent") or "")
            confirmation_intents.append(intent)
            if intent not in {"confirm_plan", "confirm_images_and_start"}:
                _add_once(
                    issues,
                    "third_routine_confirmation_requested" if paid_video_authorized or len(confirmation_intents) > 2 else "unexpected_confirmation",
                )

        if event_type == "tool_output":
            for item in content:
                if item.get("type") == "text" and looks_like_proposal_payload(str(item.get("text", ""))):
                    tool_proposal = True
                if item.get("type") == "generated_image":
                    generated_image_seen = True
                    if not plan_confirmed:
                        _add_once(issues, "image_before_plan_confirmation")
                    elif item.get("usage") == "video_payload" and item.get("role") in PAYLOAD_IMAGE_ROLES:
                        payload_image_delivered = True
                        digest = str(item.get("sha256") or "").lower()
                        if SHA256_PATTERN.fullmatch(digest):
                            displayed_payload_digests.add(digest)
                        else:
                            _add_once(issues, "missing_or_invalid_displayed_asset_digest")

        if event_type == "assistant_message" and surface == "primary_assistant_response":
            if not str(event.get("text", "")).strip() and generated_image_seen:
                _add_once(issues, "empty_final_after_image")

        if event_type == "assistant_response" and stage == "awaiting_plan_confirmation":
            if stage not in stages:
                stages.append(stage)
            proposal_items = [
                item for item in content
                if item.get("type") == "proposal_text"
                and looks_like_complete_proposal(str(item.get("text", "")))
            ]
            image_items = [item for item in content if item.get("type") == "generated_image"]
            primary_proposal = bool(proposal_items) and surface == "primary_assistant_response"
            if surface != "primary_assistant_response":
                _add_once(issues, "missing_primary_proposal")
            if image_items or event.get("imagegen_called"):
                _add_once(issues, "imagegen_called_in_plan_stage")
            state = event.get("state", {})
            raw_duration_digest = str(event.get("duration_plan_digest") or state.get("duration_plan_digest") or "").lower()
            if not SHA256_PATTERN.fullmatch(raw_duration_digest):
                _add_once(issues, "missing_or_invalid_duration_plan_digest")
            else:
                proposal_duration_plan_digest = raw_duration_digest
            expected = {
                "proposal_delivered": True,
                "plan_confirmed": False,
                "image_assets_confirmed": False,
                "paid_video_authorized": False,
            }
            if state and any(state.get(key) != value for key, value in expected.items()):
                _add_once(issues, "invalid_plan_stage_state")

        elif event_type == "user_confirmation" and event.get("intent") == "confirm_plan":
            if not primary_proposal:
                _add_once(issues, "plan_confirmed_before_proposal")
            raw_duration_digest = str(event.get("confirmed_duration_plan_digest") or "").lower()
            if (
                not SHA256_PATTERN.fullmatch(raw_duration_digest)
                or not proposal_duration_plan_digest
                or raw_duration_digest != proposal_duration_plan_digest
            ):
                _add_once(issues, "confirmed_duration_plan_digest_mismatch")
            else:
                confirmed_duration_plan_digest = raw_duration_digest
                plan_confirmed = True
            if "plan_confirmed" not in stages:
                stages.append("plan_confirmed")

        elif event_type == "assistant_response" and stage == "awaiting_image_confirmation":
            if stage not in stages:
                stages.append(stage)
            if not plan_confirmed:
                _add_once(issues, "image_before_plan_confirmation")
            payload_items = [
                item for item in content
                if item.get("type") == "generated_image"
                and item.get("usage") == "video_payload"
                and item.get("role") in PAYLOAD_IMAGE_ROLES
            ]
            if event.get("revision_replaces_previous"):
                displayed_payload_digests.clear()
            payload_image_delivered = payload_image_delivered or bool(payload_items)
            if not payload_items:
                _add_once(issues, "missing_video_payload_image")
            for item in payload_items:
                digest = str(item.get("sha256") or "").lower()
                if SHA256_PATTERN.fullmatch(digest):
                    displayed_payload_digests.add(digest)
                else:
                    _add_once(issues, "missing_or_invalid_displayed_asset_digest")
            if not event.get("imagegen_called"):
                _add_once(issues, "missing_builtin_imagegen_call")
            state = event.get("state", {})
            expected = {
                "proposal_delivered": True,
                "plan_confirmed": True,
                "image_assets_confirmed": False,
                "paid_video_authorized": False,
            }
            if state and any(state.get(key) != value for key, value in expected.items()):
                _add_once(issues, "invalid_image_stage_state")

        elif event_type == "user_confirmation" and event.get("intent") == "confirm_images_and_start":
            if not plan_confirmed:
                _add_once(issues, "image_confirmed_before_plan")
            if not payload_image_delivered:
                _add_once(issues, "image_confirmed_without_payload_image")
            raw_confirmed_digests = [str(item).lower() for item in (event.get("confirmed_asset_digests") or [])]
            raw_duration_digest = str(event.get("confirmed_duration_plan_digest") or "").lower()
            duration_plan_matches = bool(
                confirmed_duration_plan_digest
                and SHA256_PATTERN.fullmatch(raw_duration_digest)
                and raw_duration_digest == confirmed_duration_plan_digest
            )
            if not duration_plan_matches:
                _add_once(issues, "confirmed_duration_plan_digest_mismatch")
            if not raw_confirmed_digests:
                _add_once(issues, "missing_confirmed_asset_digest")
            elif (
                len(raw_confirmed_digests) != len(set(raw_confirmed_digests))
                or any(not SHA256_PATTERN.fullmatch(item) for item in raw_confirmed_digests)
                or set(raw_confirmed_digests) != displayed_payload_digests
            ):
                _add_once(issues, "confirmed_asset_digest_mismatch")
            else:
                confirmed_asset_digests = set(raw_confirmed_digests)
                if duration_plan_matches:
                    image_assets_confirmed = True
                    paid_video_authorized = True
            if "production_authorized" not in stages:
                stages.append("production_authorized")

        elif event_type == "workflow_execution":
            actions = list(event.get("actions", []))
            base_paid_request_count = event.get("base_paid_request_count")
            execution_duration_digest = str(event.get("duration_plan_digest") or "").lower()
            if (
                not confirmed_duration_plan_digest
                or not SHA256_PATTERN.fullmatch(execution_duration_digest)
                or execution_duration_digest != confirmed_duration_plan_digest
            ):
                _add_once(issues, "production_duration_plan_digest_mismatch")
            if event.get("requires_routine_confirmation"):
                _add_once(issues, "third_routine_confirmation_requested")
            if not image_assets_confirmed:
                _add_once(issues, "production_before_image_confirmation")
            if any(action in FORBIDDEN_PAID_REPAIR_ACTIONS for action in actions):
                _add_once(issues, "paid_repair_action_forbidden")
            if not isinstance(base_paid_request_count, int) or base_paid_request_count < 0:
                _add_once(issues, "missing_base_paid_request_count")
            elif paid_calls > base_paid_request_count:
                _add_once(issues, "paid_calls_exceed_base")
            if any(action not in actions for action in PRODUCTION_ACTION_SEQUENCE):
                _add_once(issues, "incomplete_automatic_production_loop")
            elif [actions.index(action) for action in PRODUCTION_ACTION_SEQUENCE] != sorted(
                actions.index(action) for action in PRODUCTION_ACTION_SEQUENCE
            ):
                _add_once(issues, "wrong_production_action_order")
            else:
                production_executed = True
            state = event.get("state", {})
            expected = {
                "proposal_delivered": True,
                "plan_confirmed": True,
                "image_assets_confirmed": True,
                "paid_video_authorized": True,
            }
            if state and any(state.get(key) != value for key, value in expected.items()):
                _add_once(issues, "invalid_production_state")

    if tool_proposal and not primary_proposal:
        _add_once(issues, "proposal_in_tool_output_only")
    if len(confirmation_intents) > 2:
        _add_once(issues, "third_routine_confirmation_requested")
    if not primary_proposal:
        _add_once(issues, "missing_primary_proposal")
    if not plan_confirmed:
        _add_once(issues, "missing_plan_confirmation")
    if not payload_image_delivered:
        _add_once(issues, "missing_video_payload_image")
    if not image_assets_confirmed:
        _add_once(issues, "missing_image_confirmation")
    if not production_executed:
        _add_once(issues, "missing_production_execution")

    return {
        "status": "pass" if not issues else "fail",
        "trace_id": trace.get("trace_id"),
        "proposal_surface": "primary_assistant_response" if primary_proposal else "none",
        "stages": stages,
        "plan_confirmed": plan_confirmed,
        "image_assets_confirmed": image_assets_confirmed,
        "paid_video_authorized": paid_video_authorized,
        "displayed_payload_digests": sorted(displayed_payload_digests),
        "confirmed_asset_digests": sorted(confirmed_asset_digests),
        "proposal_duration_plan_digest": proposal_duration_plan_digest,
        "confirmed_duration_plan_digest": confirmed_duration_plan_digest,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="Normalized two-confirmation trace JSON")
    args = parser.parse_args()
    report = validate_trace(json.loads(args.trace.read_text(encoding="utf-8")))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
