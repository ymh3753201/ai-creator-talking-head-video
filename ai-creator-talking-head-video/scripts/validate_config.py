#!/usr/bin/env python3
"""Validate ai-creator-talking-head-video model config and private env."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import (
    ScriptError,
    find_api_key,
    get_model_config,
    load_config,
    load_runtime_env,
    model_allowed_durations,
    model_api_key_names,
    require_secure_api_url,
)


REQUIRED_FIELDS = (
    "skill_adapter_status",
    "adapter_contract_version",
    "adapter_supported_inputs",
    "adapter_unsupported_provider_features",
    "adapter_notes",
    "provider",
    "base_url",
    "generation_path",
    "model",
    "supports_image_to_video",
    "supports_reference_images",
    "supports_reference_to_video",
    "source_image_becomes_first_frame",
    "max_reference_images",
    "supports_audio_input",
    "supports_lipsync",
    "supports_script_to_speech",
    "supports_avatar_reference",
    "supports_text_to_video",
    "max_duration_seconds",
    "max_script_chars",
    "source_image_field",
    "reference_field",
    "audio_field",
    "duration_field",
    "auth_scheme",
    "api_key_env_names",
    "payload_defaults",
    "capability_source",
    "verified_at",
    "provider_route",
    "verification_level",
    "external_audio_alignment_level",
)

ENABLED_ADAPTER_STATUSES = {
    "supported_runtime_verified",
    "supported_schema_verified",
}
DISABLED_ADAPTER_STATUSES = {
    "disabled_requires_runtime_verification",
    "custom_unverified",
}


def validate_model(model: dict) -> list[str]:
    issues = []
    for field in REQUIRED_FIELDS:
        if field not in model:
            issues.append(f"missing {field}")
    max_refs = int(model.get("max_reference_images") or 0)
    if bool(model.get("supports_reference_images")) and max_refs <= 0:
        issues.append("supports_reference_images requires max_reference_images > 0")
    if bool(model.get("supports_reference_to_video")) and not bool(model.get("supports_reference_images")):
        issues.append("supports_reference_to_video requires supports_reference_images=true")
    max_duration = int(model.get("max_duration_seconds") or 0)
    if max_duration <= 0:
        issues.append("max_duration_seconds must be positive")
    try:
        allowed_durations = model_allowed_durations(model)
        configured_durations = model.get("allowed_durations_seconds")
        if configured_durations is not None and configured_durations != allowed_durations:
            issues.append("allowed_durations_seconds must be unique integers in ascending order")
    except ScriptError as exc:
        issues.append(str(exc))
    if int(model.get("max_script_chars") or 0) <= 0:
        issues.append("max_script_chars must be positive")
    if bool(model.get("supports_audio_input")) and not model.get("audio_field"):
        issues.append("supports_audio_input requires audio_field")
    if bool(model.get("supports_lipsync")) and not (bool(model.get("supports_audio_input")) or bool(model.get("supports_script_to_speech"))):
        issues.append("supports_lipsync requires audio input or script-to-speech support")
    adapter_status = str(model.get("skill_adapter_status") or "")
    all_adapter_statuses = ENABLED_ADAPTER_STATUSES | DISABLED_ADAPTER_STATUSES
    if adapter_status not in all_adapter_statuses:
        issues.append(f"unknown skill_adapter_status: {adapter_status!r}")
    if model.get("enabled", True) and adapter_status not in ENABLED_ADAPTER_STATUSES:
        issues.append(
            "enabled model requires skill_adapter_status supported_runtime_verified "
            "or supported_schema_verified"
        )
    if not isinstance(model.get("adapter_supported_inputs"), list) or not model.get("adapter_supported_inputs"):
        issues.append("adapter_supported_inputs must be a non-empty list")
    if not isinstance(model.get("adapter_unsupported_provider_features"), list):
        issues.append("adapter_unsupported_provider_features must be a list")
    if not str(model.get("adapter_contract_version") or "").strip():
        issues.append("adapter_contract_version must be non-empty")
    if not str(model.get("adapter_notes") or "").strip():
        issues.append("adapter_notes must be non-empty")
    if model.get("enabled", True):
        try:
            require_secure_api_url(str(model.get("base_url") or ""))
        except ScriptError as exc:
            issues.append(str(exc))
        for field in ("capability_source", "verified_at", "provider_route", "verification_level", "external_audio_alignment_level"):
            if not str(model.get(field) or "").strip():
                issues.append(f"enabled model requires non-empty {field}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--model-key")
    parser.add_argument("--require-key", action="store_true")
    args = parser.parse_args()

    try:
        loaded_env_files = load_runtime_env()
        config = load_config(args.config)
        selected = get_model_config(config, args.model_key)
        selected_key_names = model_api_key_names(selected)
        selected_api_key = find_api_key(required=False, names=selected_key_names)
        errors = []
        report = {
            "config": str(Path(args.config).resolve()) if args.config else "default",
            "adapter_contract_version": config.get("adapter_contract_version"),
            "compatibility_notice": config.get("compatibility_notice"),
            "default_model": config.get("default_model"),
            "selected_model": selected.get("key"),
            "selected_model_id": selected.get("model"),
            "selected_base_url": selected.get("base_url"),
            "selected_generation_path": selected.get("generation_path"),
            "selected_api_key_env_names": selected_key_names,
            "api_key_present": bool(selected_api_key),
            "loaded_env_files": loaded_env_files,
            "models": {},
        }
        for key, model in (config.get("models") or {}).items():
            issues = validate_model(model)
            if model.get("adapter_contract_version") != config.get("adapter_contract_version"):
                issues.append("model adapter_contract_version must match config adapter_contract_version")
            report["models"][key] = {
                "enabled": model.get("enabled", True),
                "skill_adapter_status": model.get("skill_adapter_status", ""),
                "adapter_contract_version": model.get("adapter_contract_version", ""),
                "adapter_supported_inputs": model.get("adapter_supported_inputs", []),
                "adapter_unsupported_provider_features": model.get("adapter_unsupported_provider_features", []),
                "adapter_notes": model.get("adapter_notes", ""),
                "provider": model.get("provider"),
                "model": model.get("model"),
                "official_model": model.get("official_model", ""),
                "model_alias_note": model.get("model_alias_note", ""),
                "capability_source": model.get("capability_source", ""),
                "verified_at": model.get("verified_at", ""),
                "provider_route": model.get("provider_route", ""),
                "verification_level": model.get("verification_level", ""),
                "supports_image_to_video": bool(model.get("supports_image_to_video")),
                "supports_reference_images": bool(model.get("supports_reference_images")),
                "supports_reference_to_video": bool(model.get("supports_reference_to_video")),
                "source_image_becomes_first_frame": bool(model.get("source_image_becomes_first_frame")),
                "max_reference_images": model.get("max_reference_images"),
                "supports_audio_input": bool(model.get("supports_audio_input")),
                "supports_lipsync": bool(model.get("supports_lipsync")),
                "supports_script_to_speech": bool(model.get("supports_script_to_speech")),
                "lipsync_mode": model.get("lipsync_mode", ""),
                "external_audio_lipsync": bool(model.get("external_audio_lipsync")),
                "external_audio_alignment_level": model.get("external_audio_alignment_level", ""),
                "supported_aspect_ratios": model.get("supported_aspect_ratios"),
                "supported_resolutions": model.get("supported_resolutions"),
                "supports_avatar_reference": bool(model.get("supports_avatar_reference")),
                "supports_text_to_video": bool(model.get("supports_text_to_video")),
                "max_duration_seconds": model.get("max_duration_seconds"),
                "allowed_durations_seconds": model.get("allowed_durations_seconds"),
                "max_script_chars": model.get("max_script_chars"),
                "source_image_field": model.get("source_image_field"),
                "reference_field": model.get("reference_field"),
                "audio_field": model.get("audio_field"),
                "duration_field": model.get("duration_field"),
                "auth_scheme": model.get("auth_scheme"),
                "api_key_env_names": model.get("api_key_env_names"),
                "payload_defaults": model.get("payload_defaults"),
                "issues": issues,
            }
            if issues and model.get("enabled", True):
                errors.extend(f"{key}: {issue}" for issue in issues)
        if args.require_key:
            find_api_key(required=True, names=selected_key_names)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if errors:
            raise ScriptError("; ".join(errors))
        return 0
    except ScriptError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
