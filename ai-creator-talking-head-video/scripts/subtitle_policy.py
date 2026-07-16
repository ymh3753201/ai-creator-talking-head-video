#!/usr/bin/env python3
"""One strict contract for optional local postproduction subtitles."""

from __future__ import annotations


SUBTITLE_CONTRACT = {
    "request_source": "user_plan_confirmation",
    "confirmation_status": "confirmed",
    "provider_policy": "never_send",
    "render_policy": "postproduction_burn_only",
}


def subtitle_plan_from(value: dict | None) -> dict:
    candidate = value or {}
    nested = candidate.get("subtitle_plan")
    return nested if isinstance(nested, dict) else candidate


def enabled_subtitle_contract_errors(value: dict | None, prefix: str = "Optional subtitles") -> list[str]:
    plan = subtitle_plan_from(value)
    if not plan.get("enabled"):
        return []
    errors = []
    for field, expected in SUBTITLE_CONTRACT.items():
        if plan.get(field) != expected:
            errors.append(f"{prefix} require {field}={expected}.")
    return errors


def is_confirmed_postproduction_subtitle_plan(value: dict | None) -> bool:
    plan = subtitle_plan_from(value)
    return bool(plan.get("enabled") and not enabled_subtitle_contract_errors(plan))
