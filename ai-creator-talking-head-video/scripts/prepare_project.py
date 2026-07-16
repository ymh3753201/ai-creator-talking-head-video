#!/usr/bin/env python3
"""Prepare an AI creator talking-head video project folder and generation plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
import unicodedata
from pathlib import Path

from _common import (
    MINIMUM_MULTI_SEGMENT_SPOKEN_FILL_RATIO,
    ScriptError,
    canonical_duration_plan_payload,
    copy_or_record_asset,
    duration_plan_digest,
    get_model_config,
    is_semantically_complete_strong_boundary,
    is_url,
    load_config,
    media_summary,
    minimum_paid_segment_count,
    model_allowed_durations,
    plan_request_durations,
    quantize_request_duration,
    sanitize_name,
    semantic_boundary_issue,
    split_role_value,
    write_json,
)
from _routing import determine_execution_route
from subtitle_profiles import resolve_subtitle_profile


CONTENT_MODES = ("topic_planning", "viral_teardown", "script_rewrite", "avatar_talking_head", "hybrid_broll_edit", "longform_editing", "commerce_hybrid")
VIDEO_SOURCE_ROLES = {"video_source", "first_frame", "segment_source", "avatar_reference"}
REFERENCE_GUIDE_ROLES = {"scene_reference", "storyboard", "storyboard_sheet", "last_frame", "broll_reference", "cover"}


def platform_defaults(platform: str) -> tuple[str, str]:
    normalized = platform.strip().lower()
    if normalized in {"youtube", "youtube_horizontal", "bilibili", "b站", "longform"}:
        return "16:9", "1080p"
    return "9:16", "1080p"


def default_subtitle_strategy(platform: str, language: str, aspect_ratio: str) -> str:
    del platform, language, aspect_ratio
    return (
        "Provider output is always text-free. Final subtitles are default disabled and may be enabled only "
        "from user_plan_confirmation for local postproduction burn; they never enter the Provider payload."
    )


def read_script(args) -> dict:
    if args.script_file:
        path = Path(args.script_file).expanduser().resolve()
        if not path.exists():
            raise ScriptError(f"Script file not found: {path}")
        text = path.read_text(encoding="utf-8")
        return {"script_file": str(path), "script_text": args.script_text or text}
    return {"script_file": "", "script_text": args.script_text or ""}


def read_explicit_segments(path_value: str | None, requested_duration: int, model: dict) -> list[dict]:
    if not path_value:
        return []
    path = Path(path_value).expanduser().resolve()
    if not path.exists():
        raise ScriptError(f"Segments file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_segments = data.get("segments") if isinstance(data, dict) else data
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ScriptError("Segments file must contain a non-empty segments list")
    minimum = int(model.get("min_duration_seconds") or 1)
    maximum = int(model.get("max_duration_seconds") or requested_duration)
    allowed = model_allowed_durations(model)
    segments = []
    for index, item in enumerate(raw_segments, start=1):
        if not isinstance(item, dict):
            raise ScriptError(f"Explicit segment {index} must be an object")
        script_text = str(item.get("script") or item.get("script_segment") or "").strip()
        duration = int(item.get("duration_seconds") or 0)
        if not script_text:
            raise ScriptError(f"Explicit segment {index} has no script")
        if duration < minimum or duration > maximum:
            raise ScriptError(f"Explicit segment {index} duration {duration}s must be between {minimum}s and {maximum}s")
        if duration not in allowed:
            allowed_text = ", ".join(str(value) for value in allowed)
            raise ScriptError(
                f"Explicit segment {index} duration {duration}s is not allowed; "
                f"allowed durations are: {allowed_text}"
            )
        segments.append({"duration_seconds": duration, "script": script_text})
    minimum_count = minimum_paid_segment_count(requested_duration, model)
    if len(segments) != minimum_count:
        raise ScriptError(
            f"Explicit segment count {len(segments)} must equal the minimum paid segment count of "
            f"{minimum_count} for a {requested_duration}s delivery. Rebalance or professionally rewrite the "
            "script without changing the paid segment count."
        )
    expected_slots = plan_request_durations(requested_duration, model)
    actual_slots = [int(item["duration_seconds"]) for item in segments]
    if len(actual_slots) != len(expected_slots) or any(
        actual < minimum_slot for actual, minimum_slot in zip(actual_slots, expected_slots)
    ):
        raise ScriptError(
            f"Explicit segment durations {actual_slots} must meet the deterministic request slots "
            f"{expected_slots} for a {requested_duration}s delivery. A longer legal slot is allowed only when "
            "the measured segment speech needs it and the final delivery cap remains safe; never silently shorten "
            "the provider request window."
        )
    for index, segment in enumerate(segments[:-1], start=1):
        semantic_issue = semantic_boundary_issue(segment["script"])
        if boundary_type(segment["script"]) != "strong_sentence" or semantic_issue:
            raise ScriptError(
                f"Explicit segment {index} must end on a semantic complete strong sentence boundary. "
                "Do not mechanically replace a comma with a period; professionally rewrite the two adjacent "
                f"segments so both remain complete. Detected issue: {semantic_issue or 'weak boundary'}"
            )
    return segments


def read_source_fact_map(path_value: str | None) -> list[dict]:
    if not path_value:
        return []
    path = Path(path_value).expanduser().resolve()
    if not path.exists():
        raise ScriptError(f"Source fact map not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    facts = data.get("facts") if isinstance(data, dict) else data
    if not isinstance(facts, list):
        raise ScriptError("Source fact map must be a list or an object containing facts")
    required = ("fact_id", "source_locator", "must_preserve", "forbidden_inference", "verification_status")
    for index, item in enumerate(facts, start=1):
        if not isinstance(item, dict):
            raise ScriptError(f"Source fact {index} must be an object")
        missing = [field for field in required if not str(item.get(field) or "").strip()]
        if missing:
            raise ScriptError(f"Source fact {index} is missing: {', '.join(missing)}")
        status = str(item.get("verification_status") or "").strip()
        if status not in {"verified", "needs_user_confirmation", "missing_source"}:
            raise ScriptError(f"Source fact {index} has unsupported verification_status={status}")
    return facts


def collect_confirmed_assets(values: list[str], assets_dir: Path) -> list[dict]:
    assets = []
    for index, value in enumerate(values, start=1):
        role, raw = split_role_value(value, default_role=f"asset_{index:02d}")
        asset = copy_or_record_asset(raw, assets_dir / "confirmed", role, role=role)
        asset["id"] = f"confirmed_{index:02d}"
        assets.append(asset)
    return assets


def collect_references(values: list[str], assets_dir: Path) -> list[dict]:
    refs = []
    for index, value in enumerate(values, start=1):
        role, raw = split_role_value(value, default_role="reference")
        asset = copy_or_record_asset(raw, assets_dir / "references", role, role=role)
        asset["id"] = f"reference_{index:02d}"
        refs.append(asset)
    return refs


def collect_segment_sources(values: list[str], assets_dir: Path) -> list[dict]:
    assets = []
    seen_indices = set()
    for index, value in enumerate(values, start=1):
        label, raw = split_role_value(value, default_role=f"shot_{index:02d}")
        match = re.search(r"(\d+)", label)
        segment_index = int(match.group(1)) if match else index
        if segment_index in seen_indices:
            raise ScriptError(f"Duplicate segment source index {segment_index}: {label}")
        seen_indices.add(segment_index)
        asset = copy_or_record_asset(raw, assets_dir / "confirmed", f"segment_source_{segment_index:02d}", role="segment_source")
        asset["id"] = f"segment_source_{segment_index:02d}"
        asset["segment_index"] = segment_index
        asset["label"] = label
        assets.append(asset)
    return sorted(assets, key=lambda item: int(item.get("segment_index", 0)))


def collect_broll_plan(values: list[str], project_dir: Path) -> dict:
    entries = []
    files = []
    for index, value in enumerate(values, start=1):
        path = Path(value).expanduser()
        if path.exists():
            resolved = path.resolve()
            dest = project_dir / "references" / f"broll-plan-{index:02d}{resolved.suffix or '.txt'}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(resolved.read_text(encoding="utf-8"), encoding="utf-8")
            files.append(str(dest))
            try:
                entries.append(json.loads(resolved.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                entries.append({"text": resolved.read_text(encoding="utf-8")})
        else:
            entries.append({"text": value})
    return {"entries": entries, "files": files}


def model_warnings(model: dict, args, has_audio: bool, has_subtitle: bool, script_text: str) -> list[str]:
    warnings = []
    if args.lipsync_required and not bool(model.get("supports_lipsync")):
        warnings.append("lipsync_required=true but selected model supports_lipsync=false. Switch to a lip-sync/audio-input model before promising strict mouth sync.")
    if args.lipsync_required and has_audio and not bool(model.get("supports_audio_input")):
        warnings.append("lipsync_required=true and audio was provided, but selected model supports_audio_input=false. Audio can guide editing, but this model cannot strictly sync to it.")
    if has_audio and not bool(model.get("supports_audio_input")):
        warnings.append("Audio file recorded for hybrid/editing workflow, but it will not be sent to this model because supports_audio_input=false.")
    if has_subtitle:
        warnings.append(
            "Subtitle file is recorded only as offline transcript/planning material. "
            "It is never sent to the video Provider; it may be burned locally only by a user-confirmed postproduction subtitle plan."
        )
    max_script_chars = int(model.get("max_script_chars") or 0)
    if max_script_chars > 0 and script_text and len(script_text) > max_script_chars:
        warnings.append(f"full script_text length {len(script_text)} exceeds selected model max_script_chars={max_script_chars} for one request. Multi-segment projects are acceptable only when every shot prompt stays within this limit.")
    return warnings


def visual_generation_roles(assets: list[dict]) -> set[str]:
    return {str(asset.get("role", "")) for asset in assets}


def model_adapter_disclosure(model: dict) -> dict:
    return {
        "model_key": model.get("key"),
        "provider": model.get("provider"),
        "model": model.get("model"),
        "official_model": model.get("official_model", ""),
        "provider_route": model.get("provider_route", ""),
        "skill_adapter_status": model.get("skill_adapter_status", ""),
        "adapter_contract_version": model.get("adapter_contract_version", ""),
        "verification_level": model.get("verification_level", ""),
        "adapter_supported_inputs": model.get("adapter_supported_inputs", []),
        "adapter_unsupported_provider_features": model.get("adapter_unsupported_provider_features", []),
        "adapter_notes": model.get("adapter_notes", ""),
    }


def paid_generation_blocking_reasons(
    model: dict,
    args,
    avatar_plan: dict,
    confirmed_assets: list[dict],
    references: list[dict],
    warnings: list[str],
    script_pacing: dict | None = None,
    source_fact_map: list[dict] | None = None,
    business_context: dict | None = None,
    localization_contract: dict | None = None,
    execution_route: str = "video_generation",
    creative_choices: dict | None = None,
    duration_plan: dict | None = None,
) -> list[str]:
    reasons = []
    if not model.get("enabled", True):
        reasons.append(f"Selected model route {model.get('key') or model.get('model')} is disabled pending provider verification.")
    if model.get("skill_adapter_status") not in {
        "supported_runtime_verified",
        "supported_schema_verified",
    }:
        reasons.append(
            f"Selected model route has skill_adapter_status={model.get('skill_adapter_status') or 'missing'}; "
            "complete model-specific adapter mapping, validation, tests, and verification before paid generation."
        )
    roles = visual_generation_roles(confirmed_assets + references)
    has_visual_source = bool(roles.intersection({"video_source", "first_frame", "segment_source", "avatar_reference", "scene_reference", "cover", "storyboard", "storyboard_sheet", "broll_reference"}))
    has_avatar_or_final_source = bool(roles.intersection({"video_source", "first_frame", "segment_source", "avatar_reference"}))
    if model.get("requires_image") and not has_visual_source:
        reasons.append("Selected model requires an image, but no confirmed visual source/reference asset was recorded.")
    if avatar_plan.get("needs_generated_avatar_reference") and model.get("requires_image") and not has_avatar_or_final_source:
        reasons.append("No avatar reference or final video_source was provided; generate and confirm an original digital-human avatar or final source image before paid generation.")
    if any("lipsync_required=true" in warning for warning in warnings):
        reasons.append("Strict lip sync was requested but the selected model cannot satisfy it.")
    if any("shot prompt length" in warning and "exceeds selected model max_script_chars" in warning for warning in warnings):
        reasons.append("At least one segment prompt is longer than the selected model supports in one request.")
    for segment in (script_pacing or {}).get("segments") or []:
        status = segment.get("status")
        if status in {"missing_script", "too_long"}:
            reasons.append(
                f"{segment.get('id')} script_pacing={status}; revise or rebalance the script before paid generation "
                f"({segment.get('estimated_spoken_seconds')}s estimated for {segment.get('target_duration_seconds')}s target)."
            )
    if any("script boundary is" in warning for warning in warnings):
        reasons.append("At least one segment does not end on a clean sentence boundary; rebalance the script before paid generation to avoid chopped-speech stitching.")
    if any("single-image route cannot use storyboard_sheet as the only video source" in warning for warning in warnings):
        reasons.append("A storyboard sheet cannot be the only source image for a single-image image-to-video route.")
    if any("segment_source count" in warning and "does not match shot count" in warning for warning in warnings):
        reasons.append("Per-segment source frames must match the number of planned video segments.")
    if any("segment_source indices" in warning for warning in warnings):
        reasons.append("Per-segment source frame indices must cover every planned segment exactly once.")
    if args.require_source_fact_map and not source_fact_map:
        reasons.append("source_fact_map is required for this factual source-based project and cannot be empty.")
    for fact in source_fact_map or []:
        if fact.get("verification_status") != "verified":
            reasons.append(
                f"Source fact {fact.get('fact_id') or 'unknown'} is {fact.get('verification_status') or 'unverified'}; "
                "verify every factual claim before paid generation."
            )
    business = business_context or {}
    if str(business.get("scenario") or "").strip():
        for field in ("user_intent", "success_metric", "risk_boundary"):
            if not str(business.get(field) or "").strip():
                reasons.append(f"business_context.{field} is required before paid generation.")
    if execution_route == "postproduction_only":
        reasons.append("This is a postproduction_only existing-video project; do not call a paid video generation API.")
    if execution_route == "external_audio_generation" and (not model.get("supports_audio_input") or not model.get("audio_field")):
        reasons.append("External audio controls timing, but the selected model does not support an audio input payload.")
    if str(args.timing_authority or "").strip().lower() in {"external_subtitle", "provided_subtitle", "user_subtitle"}:
        reasons.append(
            "External subtitles cannot be the paid video model timing authority under the Provider no-text policy. "
            "Use them only as offline transcript/planning material, or provide approved external audio as timing authority."
        )
    localization = localization_contract or {}
    if localization.get("enabled") and localization.get("translation_review_status") != "verified":
        reasons.append(
            f"localization translation_review_status={localization.get('translation_review_status') or 'missing'}; "
            "confirm the localized script and glossary before paid generation."
        )
    choices = creative_choices or {}
    subtitle_choice = choices.get("subtitle") or {}
    if subtitle_choice.get("enabled") and (
        subtitle_choice.get("request_source") != "user_plan_confirmation"
        or subtitle_choice.get("confirmation_status") != "confirmed"
    ):
        reasons.append(
            "Enabled subtitles require request_source=user_plan_confirmation in the same Stage B1 plan confirmation."
        )
    if (choices.get("effects") or {}).get("choice") == "pending":
        reasons.append("The effects choice is pending; confirm effects enabled or disabled in the Stage B1 text proposal.")
    effects = choices.get("effects") or {}
    if effects.get("choice") == "enabled" and not effects.get("approved_effects"):
        reasons.append("Effects are enabled but no approved effects were recorded.")
    duration_contract = duration_plan or {}
    if duration_contract.get("confirmation_status") != "confirmed":
        reasons.append("The final duration is not user confirmed; confirm duration before paid generation.")
    if duration_contract.get("delivery_fit_status") == "revise":
        reasons.append(
            f"Estimated speech plus required natural pauses is {duration_contract.get('estimated_delivery_seconds')}s, "
            f"which exceeds the {duration_contract.get('delivery_max_seconds')}s delivery cap. Shorten the script "
            "or explicitly extend the confirmed delivery duration before paid generation."
        )
    return reasons


def source_assets_by_segment(segment_sources: list[dict]) -> dict[int, dict]:
    return {int(asset.get("segment_index")): asset for asset in segment_sources if asset.get("segment_index")}


def visual_asset_strategy(model: dict, references: list[dict], segment_sources: list[dict]) -> str:
    if segment_sources:
        return "per_segment_source_frames"
    if model.get("supports_reference_images") and references:
        return "multi_reference_storyboard" if any(asset.get("role") in {"storyboard", "storyboard_sheet"} for asset in references) else "source_plus_references"
    return "single_source_frame"


def asset_strategy_warnings(model: dict, confirmed_assets: list[dict], references: list[dict], segment_sources: list[dict], shot_count: int) -> list[str]:
    warnings = []
    roles = visual_generation_roles(confirmed_assets + references)
    if segment_sources and len(segment_sources) != shot_count:
        warnings.append(f"segment_source count {len(segment_sources)} does not match shot count {shot_count}. Provide one approved segment source/first-frame image per generated clip.")
    if segment_sources:
        actual_indices = sorted(int(asset.get("segment_index") or 0) for asset in segment_sources)
        expected_indices = list(range(1, shot_count + 1))
        if actual_indices != expected_indices:
            warnings.append(f"segment_source indices {actual_indices} do not match required shot indices {expected_indices}.")
    if not model.get("supports_reference_images"):
        if "storyboard_sheet" in roles and not roles.intersection(VIDEO_SOURCE_ROLES):
            warnings.append("single-image route cannot use storyboard_sheet as the only video source. Generate a final video_source/first_frame image or per-segment source frames instead.")
        ignored_guides = sorted(role for role in roles.intersection(REFERENCE_GUIDE_ROLES) if role not in {"cover"})
        if ignored_guides:
            warnings.append(f"selected model supports_reference_images=false; {', '.join(ignored_guides)} are planning/QA guides unless merged into video_source or segment_source images.")
    if model.get("supports_reference_images") and int(model.get("max_reference_images") or 0) and len([asset for asset in confirmed_assets + references if asset.get("role") in REFERENCE_GUIDE_ROLES.union(VIDEO_SOURCE_ROLES)]) > int(model.get("max_reference_images")) + 1:
        warnings.append(f"confirmed visual guide count may exceed max_reference_images={model.get('max_reference_images')}; mark extra images preview_only or merge them before dry-run.")
    return warnings


def estimate_spoken_seconds(text: str, language: str, minimum: float = 1.5) -> float:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return 0.0
    normalized_language = language.lower().replace("_", "-")
    if normalized_language.startswith("zh"):
        spoken_chars = len(re.findall(r"[\u3400-\u9fff]", clean))
        other_words = len(re.findall(r"[A-Za-z0-9']+", clean))
        return round(max(minimum, spoken_chars / 4.8 + other_words / 2.4), 1)
    if normalized_language.startswith("ja"):
        spoken_chars = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", clean))
        return round(max(minimum, spoken_chars / 4.5), 1)
    if normalized_language.startswith("ko"):
        spoken_chars = len(re.findall(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]", clean))
        return round(max(minimum, spoken_chars / 4.0), 1)
    if normalized_language.startswith("th"):
        spoken_chars = len(re.findall(r"[\u0e00-\u0e7f]", clean))
        return round(max(minimum, spoken_chars / 4.2), 1)
    words = len(re.findall(r"[^\W_]+(?:['’\-][^\W_]+)*", clean, re.UNICODE))
    if words > 1:
        return round(max(minimum, words / 2.4), 1)
    letter_count = sum(1 for character in clean if unicodedata.category(character).startswith("L"))
    return round(max(minimum, letter_count / 4.0), 1)


def split_spoken_units(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return []
    units = [item.strip() for item in re.findall(r"[^。！？!?；;，,、\n]+[。！？!?；;，,、]?", cleaned) if item.strip()]
    return units or [cleaned]


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


def is_stitch_safe_boundary(text: str, is_final: bool) -> bool:
    kind = boundary_type(text)
    if is_final:
        return kind in {"strong_sentence", "no_terminal_punctuation"}
    return kind == "strong_sentence"


def rebalance_weak_tail_units(chunks: list[list[str]]) -> list[list[str]]:
    for index in range(0, max(0, len(chunks) - 1)):
        while len(chunks[index]) > 1 and boundary_type(chunks[index][-1]) in {"weak_clause", "open_enumerator"}:
            chunks[index + 1].insert(0, chunks[index].pop())
    return chunks


def split_script_by_duration(script_text: str, segment_durations: list[int], language: str) -> list[str]:
    total = len(segment_durations)
    if total <= 1:
        return [script_text.strip()]
    cleaned = script_text.strip()
    if not cleaned:
        return ["" for _ in range(total)]

    units = split_spoken_units(cleaned)
    if len(units) < total:
        return [cleaned] + ["" for _ in range(total - 1)]

    unit_seconds = [estimate_spoken_seconds(unit, language, minimum=0.1) for unit in units]
    total_spoken = sum(unit_seconds)
    total_duration = max(sum(segment_durations), 1)
    targets = [max(0.1, total_spoken * duration / total_duration) for duration in segment_durations]
    chunks: list[list[str]] = [[] for _ in segment_durations]
    current_index = 0
    current_seconds = 0.0

    for unit_index, (unit, seconds) in enumerate(zip(units, unit_seconds)):
        remaining_units = len(units) - unit_index
        remaining_segments = total - current_index
        must_move = current_index < total - 1 and chunks[current_index] and remaining_units <= remaining_segments - 1
        if must_move:
            current_index += 1
            current_seconds = 0.0
        can_move = current_index < total - 1 and chunks[current_index] and remaining_units >= remaining_segments
        target = targets[current_index]
        if not must_move and can_move and current_seconds + seconds > target:
            before_delta = abs(current_seconds - target)
            after_delta = abs((current_seconds + seconds) - target)
            if before_delta <= after_delta:
                current_index += 1
                current_seconds = 0.0
        chunks[current_index].append(unit)
        current_seconds += seconds

    chunks = rebalance_weak_tail_units(chunks)
    result = ["".join(chunk).strip() for chunk in chunks]
    while len(result) < total:
        result.append("")
    return result[:total]


def adaptive_content_segments(script_text: str, model: dict, language: str) -> tuple[list[int], list[str]]:
    """Split only at existing semantic-complete strong sentence boundaries."""
    units = split_spoken_units(script_text)
    if not units:
        return [], []
    maximum = int(model.get("max_duration_seconds") or 15)
    safety_seconds = 0.8
    max_spoken = max(0.5, maximum - safety_seconds)
    for unit in units:
        estimated = estimate_spoken_seconds(unit, language, minimum=0.1)
        if estimated > max_spoken:
            raise ScriptError(
                "A spoken clause exceeds one model-safe segment and has no semantic complete strong sentence "
                "boundary. Professionally rewrite the approved script before planning paid requests; do not "
                "split characters or mechanically replace punctuation."
            )
    estimates = [estimate_spoken_seconds(unit, language, minimum=0.1) for unit in units]
    prefix = [0.0]
    for value in estimates:
        prefix.append(prefix[-1] + value)
    total_spoken = prefix[-1]
    start_count = max(1, math.ceil(total_spoken / max_spoken))

    chosen: list[tuple[int, int]] | None = None
    for count in range(start_count, len(units) + 1):
        target = total_spoken / count
        dp: list[list[tuple[float, list[tuple[int, int]]] | None]] = [
            [None for _ in range(len(units) + 1)] for _ in range(count + 1)
        ]
        dp[0][0] = (0.0, [])
        for groups in range(1, count + 1):
            for end in range(groups, len(units) + 1):
                best = None
                for start in range(groups - 1, end):
                    previous = dp[groups - 1][start]
                    if previous is None:
                        continue
                    spoken = prefix[end] - prefix[start]
                    if spoken > max_spoken + 1e-6:
                        continue
                    if groups < count:
                        candidate_text = "".join(units[start:end]).strip()
                        if not is_semantically_complete_strong_boundary(candidate_text):
                            continue
                    cost = previous[0] + (spoken - target) ** 2
                    candidate = (cost, previous[1] + [(start, end)])
                    if best is None or candidate[0] < best[0]:
                        best = candidate
                dp[groups][end] = best
        if dp[count][len(units)] is not None:
            chosen = dp[count][len(units)][1]
            break
    if chosen is None:
        raise ScriptError(
            "Cannot split the script at semantic complete strong sentence boundaries within model-safe speech "
            "capacity. Professionally rewrite the approved script before paid generation."
        )

    scripts = []
    durations = []
    for start, end in chosen:
        text = "".join(units[start:end]).strip()
        estimated = estimate_spoken_seconds(text, language)
        duration = quantize_request_duration(estimated + safety_seconds, model)
        scripts.append(text)
        durations.append(duration)
    return durations, scripts


def enforce_multi_segment_target_fill(duration: int, scripts: list[str], language: str) -> None:
    """Reject grossly underfilled multi-segment targets before image/video spend."""
    if len(scripts) <= 1 or not any(str(item).strip() for item in scripts) or duration <= 0:
        return
    estimated = round(sum(estimate_spoken_seconds(item, language, minimum=0.1) for item in scripts), 1)
    ratio = estimated / float(duration)
    if ratio + 1e-9 < MINIMUM_MULTI_SEGMENT_SPOKEN_FILL_RATIO:
        raise ScriptError(
            f"The optimized multi-segment script is estimated at {estimated}s ({ratio:.0%}) for a {duration}s target. "
            f"It must use at least {MINIMUM_MULTI_SEGMENT_SPOKEN_FILL_RATIO:.0%} of the requested delivery window "
            "before production. Perform a professional rewrite toward the normal 85%-95% planning window, or "
            "explicitly confirm a shorter delivery duration and recalculate the plan."
        )


def plan_content_segments(
    duration: int,
    model: dict,
    script_text: str,
    language: str,
    explicit_segments: list[dict] | None = None,
) -> tuple[list[int], list[str], bool]:
    """Create one deterministic segment plan for proposal and production stages."""
    if explicit_segments:
        expected_count = minimum_paid_segment_count(duration, model)
        if len(explicit_segments) != expected_count:
            raise ScriptError(
                f"Explicit segment count {len(explicit_segments)} must equal the minimum paid segment count "
                f"of {expected_count} for a {duration}s delivery."
            )
        expected_slots = plan_request_durations(duration, model)
        actual_slots = [int(item["duration_seconds"]) for item in explicit_segments]
        if len(actual_slots) != len(expected_slots) or any(
            actual < minimum_slot for actual, minimum_slot in zip(actual_slots, expected_slots)
        ):
            raise ScriptError(
                f"Explicit segment durations {actual_slots} must meet the deterministic request slots "
                f"{expected_slots} for a {duration}s delivery."
            )
        for index, item in enumerate(explicit_segments[:-1], start=1):
            script = str(item.get("script") or "")
            semantic_issue = semantic_boundary_issue(script)
            if boundary_type(script) != "strong_sentence" or semantic_issue:
                raise ScriptError(
                    f"Explicit segment {index} must end on a semantic complete strong sentence boundary. "
                    f"Detected issue: {semantic_issue or 'weak boundary'}"
                )
        durations = [int(item["duration_seconds"]) for item in explicit_segments]
        scripts = [str(item["script"]).strip() for item in explicit_segments]
        enforce_multi_segment_target_fill(duration, scripts, language)
        return durations, scripts, False

    minimum_slots = plan_request_durations(duration, model)
    script_segments = split_script_by_duration(script_text, minimum_slots, language)
    requires_pacing_refit = any(
        pacing_status(estimate_spoken_seconds(text, language), seconds) == "too_long"
        for text, seconds in zip(script_segments, minimum_slots)
    )
    requires_boundary_refit = bool(script_text.strip()) and any(
        not is_semantically_complete_strong_boundary(text)
        for text in script_segments[:-1]
    )
    requires_refit = requires_pacing_refit or requires_boundary_refit
    if not requires_refit:
        enforce_multi_segment_target_fill(duration, script_segments, language)
        return minimum_slots, script_segments, False

    fitted_durations, fitted_scripts = adaptive_content_segments(script_text, model, language)
    if len(fitted_durations) != len(minimum_slots):
        estimated = estimate_spoken_seconds(script_text, language)
        safe_capacity = round(sum(value * 0.95 for value in minimum_slots), 1)
        raise ScriptError(
            f"Script is estimated at {estimated}s but cannot form semantic complete strong sentence boundaries "
            f"within the minimum {len(minimum_slots)} paid segments for the {duration}s delivery cap "
            f"(safe speech capacity about {safe_capacity}s). Perform a professional rewrite and rebalance the script "
            "inside those segments, or explicitly extend the requested delivery duration before paid generation."
        )
    fitted_durations = [
        max(actual_slot, minimum_slot)
        for actual_slot, minimum_slot in zip(fitted_durations, minimum_slots)
    ]
    enforce_multi_segment_target_fill(duration, fitted_scripts, language)
    return fitted_durations, fitted_scripts, True


def build_plan_only_result(
    duration: int,
    model: dict,
    script_text: str,
    language: str,
    explicit_segments: list[dict] | None = None,
) -> dict:
    durations, scripts, automatically_fitted = plan_content_segments(
        duration,
        model,
        script_text,
        language,
        explicit_segments=explicit_segments,
    )
    planned_total = sum(durations)
    pacing_items = [
        build_script_pacing(text, seconds, language)
        for seconds, text in zip(durations, scripts)
    ]
    duration_metrics = build_duration_metrics(duration, durations, pacing_items)
    spoken_fill_ratio = round(float(duration_metrics["estimated_spoken_seconds"]) / duration, 3) if duration else 0.0
    digest_payload = canonical_duration_plan_payload(model, duration, durations, scripts)
    plan_digest = duration_plan_digest(model, duration, durations, scripts)
    return {
        "ok": True,
        "plan_only": True,
        "model_key": model.get("key"),
        "model_adapter": model_adapter_disclosure(model),
        "allowed_durations_seconds": model_allowed_durations(model),
        "delivery_max_seconds": duration,
        "minimum_paid_segment_count": minimum_paid_segment_count(duration, model),
        "segment_count": len(durations),
        "planned_request_durations_seconds": durations,
        "planned_request_total_seconds": planned_total,
        "duration_plan_digest": plan_digest,
        "duration_plan_digest_payload": digest_payload,
        "automatic_content_fit": automatically_fitted,
        "spoken_fill_ratio": spoken_fill_ratio,
        "target_spoken_fill_window": [0.85, 0.95],
        "minimum_multi_segment_spoken_fill_ratio": MINIMUM_MULTI_SEGMENT_SPOKEN_FILL_RATIO,
        "segments": [
            {
                "index": index,
                "request_duration_seconds": seconds,
                "estimated_spoken_seconds": estimate_spoken_seconds(text, language),
                "script": text,
            }
            for index, (seconds, text) in enumerate(zip(durations, scripts), start=1)
        ],
        "rule": "Use the fewest paid requests, only provider-supported duration slots, and a hard final delivery cap.",
        **duration_metrics,
    }


def build_script_boundary(segment_text: str, index: int, total: int) -> dict:
    kind = boundary_type(segment_text)
    is_final = index >= total
    semantic_issue = "" if is_final else semantic_boundary_issue(segment_text)
    clean = is_stitch_safe_boundary(segment_text, is_final) and not semantic_issue
    if clean:
        issue = ""
    elif kind in {"weak_clause", "open_enumerator"}:
        issue = "Segment ends on an unfinished clause/enumerator; rebalance script before stitching so the cut does not feel like speech was chopped."
    elif semantic_issue:
        issue = f"Segment ends with strong punctuation but is still a semantic fragment: {semantic_issue}. Professionally rewrite before paid generation."
    else:
        issue = "Segment does not end on a clear sentence boundary; add punctuation, transition, or rebalance before paid generation."
    return {
        "boundary_type": kind,
        "is_final_segment": is_final,
        "stitch_safe": clean,
        "semantic_boundary_issue": semantic_issue,
        "issue": issue,
    }


def pacing_status(estimated_seconds: float, target_seconds: int) -> str:
    if target_seconds <= 0:
        return "ok"
    if estimated_seconds <= 0:
        return "missing_script"
    ratio = estimated_seconds / target_seconds
    if target_seconds - estimated_seconds >= 1.5 and ratio < 0.9:
        return "short_but_usable"
    if ratio > 0.95:
        return "too_long"
    return "ok"


def build_script_pacing(segment_text: str, target_seconds: int, language: str) -> dict:
    estimated = estimate_spoken_seconds(segment_text, language)
    boundary_padding = round(min(0.4, max(0.3, target_seconds * 0.025)), 2) if target_seconds else 0.0
    return {
        "target_duration_seconds": target_seconds,
        "estimated_spoken_seconds": estimated,
        "spoken_fill_ratio": round(estimated / target_seconds, 2) if target_seconds else 0,
        "status": pacing_status(estimated, target_seconds),
        "target_rule": "Prefer a natural complete delivery with clean head/tail safety. A shorter complete segment is usable and its idle tail can be trimmed; only over-capacity or missing speech blocks generation.",
        "minimum_recommended_spoken_seconds": round(target_seconds * 0.9, 1),
        "maximum_recommended_spoken_seconds": round(target_seconds * 0.95, 1),
        "head_padding_seconds": boundary_padding,
        "tail_padding_seconds": boundary_padding,
    }


def build_duration_metrics(delivery_max: int, request_durations: list[int], pacing_items: list[dict]) -> dict:
    """Separate removable idle tail from provider-slot delivery overshoot."""
    planned_request_total = sum(int(value) for value in request_durations)
    estimated_spoken = round(
        sum(float(item.get("estimated_spoken_seconds") or 0) for item in pacing_items),
        2,
    )
    natural_pause = round(
        sum(
            float(item.get("head_padding_seconds") or 0)
            + float(item.get("tail_padding_seconds") or 0)
            for item in pacing_items
            if float(item.get("estimated_spoken_seconds") or 0) > 0
        ),
        2,
    )
    estimated_delivery = round(estimated_spoken + natural_pause, 2)
    return {
        "estimated_spoken_seconds": estimated_spoken,
        "estimated_natural_pause_seconds": natural_pause,
        "estimated_delivery_seconds": estimated_delivery,
        "planned_trim_seconds": round(max(0.0, planned_request_total - estimated_delivery), 2),
        "planned_delivery_overshoot_seconds": max(0, planned_request_total - int(delivery_max)),
        "delivery_margin_seconds": round(int(delivery_max) - estimated_delivery, 2),
        "delivery_fit_status": "ok" if estimated_delivery <= int(delivery_max) else "revise",
    }


def build_script_pacing_summary(shots: list[dict], target_duration: int, language: str, script_text: str) -> dict:
    estimated_total = round(sum(float((shot.get("script_pacing") or {}).get("estimated_spoken_seconds") or 0) for shot in shots), 1)
    statuses = [(shot.get("script_pacing") or {}).get("status", "missing_script") for shot in shots]
    blocking_statuses = {"missing_script", "too_long"}
    if any(status in blocking_statuses for status in statuses):
        status = "revise"
    else:
        status = "ok"
    return {
        "status": status,
        "language": language,
        "target_duration_seconds": target_duration,
        "estimated_total_spoken_seconds": estimated_total,
        "total_spoken_fill_ratio": round(estimated_total / target_duration, 2) if target_duration else 0,
        "source_script_estimated_seconds": estimate_spoken_seconds(script_text, language),
        "policy": "Automatically fit complete speech into model-safe segments. A single short complete segment may generate with tail room and be trimmed; multi-segment targets below 75% total spoken fill, missing speech, or over-capacity speech must be professionally rewritten or re-planned before submission.",
        "segments": [
            {
                "id": shot.get("id"),
                "target_duration_seconds": (shot.get("script_pacing") or {}).get("target_duration_seconds"),
                "estimated_spoken_seconds": (shot.get("script_pacing") or {}).get("estimated_spoken_seconds"),
                "spoken_fill_ratio": (shot.get("script_pacing") or {}).get("spoken_fill_ratio"),
                "status": (shot.get("script_pacing") or {}).get("status"),
            }
            for shot in shots
        ],
    }


def script_pacing_warnings(script_pacing: dict) -> list[str]:
    warnings = []
    for segment in script_pacing.get("segments") or []:
        status = segment.get("status")
        if status == "short_but_usable":
            warnings.append(
                f"{segment.get('id')} is shorter than its request slot: estimated {segment.get('estimated_spoken_seconds')}s for "
                f"{segment.get('target_duration_seconds')}s. Continue automatically and trim only verified idle tail after generation."
            )
        elif status == "too_long":
            warnings.append(
                f"{segment.get('id')} script pacing too long: estimated {segment.get('estimated_spoken_seconds')}s for "
                f"{segment.get('target_duration_seconds')}s. Split or shorten before paid generation to avoid rushed narration."
            )
        elif status == "missing_script":
            warnings.append(f"{segment.get('id')} has no script segment; confirm this is an intentional silent/B-roll segment before paid generation.")
    return warnings


def script_boundary_warnings(shots: list[dict]) -> list[str]:
    warnings = []
    for shot in shots:
        boundary = shot.get("script_boundary") or {}
        if boundary and not boundary.get("stitch_safe"):
            warnings.append(
                f"{shot.get('id')} script boundary is {boundary.get('boundary_type')}: "
                f"{boundary.get('issue')}"
            )
    return warnings


def segment_focus(index: int, total: int) -> str:
    if total <= 1:
        return "single continuous talking-head segment"
    if index == 1:
        return "opening hook, context, and first content beat"
    if index == total:
        return "final content beat, recap, and CTA"
    return f"main explanation beat {index - 1} with a smooth handoff from the previous segment"


def build_visual_bible(args, aspect_ratio: str, resolution: str, subtitle_strategy: str, effects_enabled: bool = False) -> dict:
    del subtitle_strategy
    subtitle_rule = (
        "Provider no-text policy: every Provider-generated frame must remain free of written text and captions. "
        "Any user-confirmed subtitles are added only after clean-output review by local postproduction."
    )
    return {
        "continuity_priority": "same_avatar_same_scene_same_style",
        "avatar_identity_rule": "Use the same confirmed avatar, video_source, or segment_source identity in every segment.",
        "scene_rule": "Keep the same studio/background/composition unless the user confirmed a planned scene change.",
        "camera_rule": "Maintain the same talking-head framing, lens feel, lighting, and delivery tempo.",
        "subtitle_rule": subtitle_rule,
        "broll_rule": (
            "Use only user-approved B-roll/effects."
            if effects_enabled
            else "Do not insert B-roll, title cards, cutaway images, overlays, or other visual effects. Preserve the complete model-generated video."
        ),
        "asset_reuse_rule": "Every segment must reuse the confirmed source/reference asset set; never silently swap avatar, outfit, scene, or camera style.",
        "business_scenario": args.business_scenario,
        "platform": args.platform,
        "content_mode": args.content_mode,
        "language": args.language,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
    }


def build_segment_prompt(base_prompt: str, script_text: str, script_segment: str, index: int, total: int, seconds: int, focus: str, visual_bible: dict, script_pacing: dict) -> str:
    base = (base_prompt or "").strip()
    script_source = (script_text or "").strip()
    if total > 1 and script_source and base == script_source:
        base = "Create the approved digital-human talking-head segment."
    if not base:
        base = "Create a digital-human talking-head video."

    clean_output_rule = (
        "Clean-frame contract: keep every frame free of any written or typographic element. No on-screen text: "
        "subtitles, captions, lower thirds, title cards, speech bubbles, labels, UI, letters, numbers, punctuation, "
        "logos or watermarks—in any language. Spoken dialogue must remain audio only; never visualize spoken words. "
        "Overrides conflicts."
    )
    visual_insert_rule = str((visual_bible or {}).get("broll_rule") or "").strip()
    if visual_insert_rule and any(marker in visual_insert_rule.lower() for marker in ("do not insert", "no b-roll", "preserve the complete")):
        visual_insert_rule = "No B-roll, cutaways, overlays or effects."
    minimum_spoken = script_pacing.get("minimum_recommended_spoken_seconds", "safe")
    maximum_spoken = script_pacing.get("maximum_recommended_spoken_seconds", seconds)
    estimated_spoken = script_pacing.get("estimated_spoken_seconds", "unknown")
    head_padding = script_pacing.get("head_padding_seconds", 0.4)
    speech_safety_rule = (
        f"Speech {minimum_spoken}-{maximum_spoken}s (est. {estimated_spoken}s); ~{head_padding}s "
        "neutral pause before and after speech; pronounce complete first/final words."
    )
    clean_boundary_rule = "No restart/fades/crossfades; clean boundaries."
    if total <= 1:
        parts = [base, clean_output_rule]
        if visual_insert_rule:
            parts.append(visual_insert_rule)
        if script_segment and script_segment != base:
            parts.append(f"Spoken script: {script_segment}")
        if script_segment:
            parts.append(speech_safety_rule)
            parts.append(clean_boundary_rule)
        return "\n\n".join(parts)

    continuity = (
        f"Segment {index}/{total}, {seconds}s, {focus}. Same avatar, outfit, scene, frame and light."
    )
    parts = [base, continuity, clean_output_rule]
    if visual_insert_rule:
        parts.append(visual_insert_rule)
    if script_segment:
        parts.append(f"Spoken script: {script_segment}")
        parts.append(speech_safety_rule)
    parts.append(clean_boundary_rule)
    return "\n\n".join(parts)


def shot_prompt_warnings(model: dict, shots: list[dict]) -> list[str]:
    max_script_chars = int(model.get("max_script_chars") or 0)
    if max_script_chars <= 0:
        return []
    warnings = []
    for shot in shots:
        prompt_len = len(shot.get("prompt") or "")
        if prompt_len > max_script_chars:
            warnings.append(f"{shot.get('id')} shot prompt length {prompt_len} exceeds selected model max_script_chars={max_script_chars}. Shorten or split that segment before paid generation.")
    return warnings


def build_shots(duration: int, model: dict, prompt: str, script_text: str, references: list[dict], confirmed_assets: list[dict], segment_sources: list[dict], visual_bible: dict, language: str, explicit_segments: list[dict] | None = None) -> list[dict]:
    segments, script_segments, automatically_fitted = plan_content_segments(
        duration,
        model,
        script_text,
        language,
        explicit_segments=explicit_segments,
    )
    segment_source_map = source_assets_by_segment(segment_sources)
    shots = []
    cursor = 0
    for index, seconds in enumerate(segments, start=1):
        shot_id = f"shot_{index:02d}"
        focus = segment_focus(index, len(segments))
        script_segment = script_segments[index - 1] if index - 1 < len(script_segments) else ""
        script_pacing = build_script_pacing(script_segment, seconds, language)
        script_boundary = build_script_boundary(script_segment, index, len(segments))
        shots.append({
            "id": shot_id,
            "segment_index": index,
            "segment_count": len(segments),
            "duration_seconds": seconds,
            "automatic_content_fit": automatically_fitted,
            "start_second": cursor,
            "end_second": cursor + seconds,
            "segment_focus": focus,
            "script_segment": script_segment,
            "script_pacing": script_pacing,
            "script_boundary": script_boundary,
            "continuity_contract": "same confirmed avatar/source assets, same scene style, same camera framing, same subtitle system, normalized stitch-ready output",
            "visual_bible": visual_bible,
            "segment_source_asset": segment_source_map.get(index),
            "source_frame_rule": "Use this shot's segment_source_asset as the video source image when present; otherwise reuse the shared confirmed video_source/first_frame/avatar source.",
            "prompt": build_segment_prompt(prompt, script_text, script_segment, index, len(segments), seconds, focus, visual_bible, script_pacing),
            "references": references,
            "confirmed_assets": confirmed_assets,
            "request_file": "",
            "clip_file": "",
        })
        cursor += seconds
    return shots


def build_longform_strategy(shots: list[dict], model: dict) -> dict:
    return {
        "requires_multi_segment": len(shots) > 1,
        "segment_count": len(shots),
        "max_model_duration_seconds": model.get("max_duration_seconds"),
        "segments": [
            {
                "id": shot.get("id"),
                "index": shot.get("segment_index"),
                "duration_seconds": shot.get("duration_seconds"),
                "start_second": shot.get("start_second"),
                "end_second": shot.get("end_second"),
                "focus": shot.get("segment_focus"),
                "script_segment": shot.get("script_segment"),
                "script_pacing": shot.get("script_pacing"),
                "script_boundary": shot.get("script_boundary"),
                "segment_source_asset": shot.get("segment_source_asset"),
            }
            for shot in shots
        ],
        "consistency_rule": "Use one visual_bible and the same confirmed asset set for all segments; only the content beat changes.",
        "stitching_required": len(shots) > 1,
    }


def default_auto_trim_tail_silence(
    content_mode: str,
    speech_source: str,
    timing_authority: str,
    has_audio: bool,
    has_subtitle: bool,
    has_existing_video: bool,
) -> bool:
    return bool(
        content_mode == "avatar_talking_head"
        and speech_source == "generated_dialogue"
        and timing_authority == "script_and_target_duration"
        and not has_audio
        and not has_subtitle
        and not has_existing_video
    )


def build_stitching_plan(
    project_dir: Path,
    shots: list[dict],
    aspect_ratio: str,
    resolution: str,
    auto_trim_tail_silence: bool,
) -> dict:
    height_by_label = {"480p": 480, "720p": 720, "1080p": 1080, "4k": 2160}
    short_edge = height_by_label.get(resolution.lower())
    if short_edge and aspect_ratio == "9:16":
        target_resolution = f"{short_edge}x{round(short_edge * 16 / 9)}"
    elif short_edge and aspect_ratio == "16:9":
        target_resolution = f"{round(short_edge * 16 / 9)}x{short_edge}"
    else:
        target_resolution = resolution if re.fullmatch(r"\d+x\d+", resolution.lower()) else ""
    return {
        "required": len(shots) > 1,
        "tool": "scripts/stitch_clips.py",
        "clip_order": [shot.get("clip_file") for shot in shots],
        "target_resolution": target_resolution,
        "declared_resolution": resolution,
        "target_fps": 30,
        "normalize_before_concat": True,
        "auto_trim_tail_silence": bool(auto_trim_tail_silence),
        "min_tail_silence_seconds": 1.0,
        "tail_padding_seconds": 0.25,
        "max_tail_trim_seconds": 2.5,
        "duration_tolerance_ratio": 0.05,
        "final_output": str(project_dir / "final.mp4"),
        "report_file": str(project_dir / "final.stitch-report.json"),
    }


def build_subtitle_plan(
    project_dir: Path,
    subtitle_asset: dict | None,
    subtitle_strategy: str,
    language: str,
    aspect_ratio: str,
    choice: str = "pending",
    request_source: str = "default",
    platform: str = "",
    whisper_model: str = "",
    whisper_executable: str = "",
) -> dict:
    del subtitle_strategy
    enabled = choice == "enabled"
    confirmed = enabled and request_source == "user_plan_confirmation"
    profile = resolve_subtitle_profile(platform, aspect_ratio) if enabled else None
    return {
        "enabled": enabled,
        "choice": "enabled" if enabled else "disabled",
        "confirmation_status": "confirmed" if confirmed else ("pending" if enabled else "default_disabled"),
        "request_source": request_source if enabled else "default",
        "background_policy": "transparent_outline_only" if enabled else "not_applicable",
        "default_policy": "default disabled; user-confirmed postproduction burn only",
        "requires_user_confirmation": bool(enabled and not confirmed),
        "source": ("provided_srt" if subtitle_asset else "local_whisper_cpp") if enabled else "none",
        "language": language,
        "aspect_ratio": aspect_ratio,
        "platform": platform,
        "strategy": "postproduction subtitles from final audio" if enabled else "no post-rendered subtitles",
        "provider_policy": "never_send",
        "render_policy": "postproduction_burn_only" if enabled else "none",
        "timing_source": ("provided_srt" if subtitle_asset else "local_whisper_cpp") if enabled else "none",
        "profile": profile,
        "safe_zone": ({
            key: profile.get(key)
            for key in ("margin_left_ratio", "margin_right_ratio", "margin_bottom_ratio", "max_lines")
        } if profile else None),
        "input_subtitle": subtitle_asset,
        "whisper_model": str(Path(whisper_model).expanduser().resolve()) if enabled and whisper_model else "",
        "whisper_executable": str(Path(whisper_executable).expanduser().resolve()) if enabled and whisper_executable else "",
        "clean_video_output": str(project_dir / "final.clean.mp4") if enabled else "",
        "clean_visual_review_output": str(project_dir / "visual-review.clean.json") if enabled else "",
        "srt_output": str(project_dir / "subtitles" / "final.srt") if enabled else "",
        "raw_asr_output": str(project_dir / "subtitles" / "final.raw-asr.srt") if enabled and not subtitle_asset else "",
        "subtitle_audit_output": str(project_dir / "subtitles" / "final.audit.json") if enabled else "",
        "burn_audit_output": str(project_dir / "subtitles" / "burn.audit.json") if enabled else "",
        "burned_video_output": str(project_dir / "final.captioned.mp4") if enabled else "",
        "caption_visual_review_output": str(project_dir / "visual-review.json") if enabled else "",
        "delivery_rule": (
            "Verify the clean MP4 first, then burn platform-safe subtitles locally and deliver the captioned MP4."
            if enabled
            else "Deliver the verified clean MP4 without generating or burning subtitles."
        ),
    }


def build_effects_plan(choice: str, approved_effects: list[str], broll_plan: dict) -> dict:
    effects = [str(item).strip() for item in approved_effects if str(item).strip()]
    has_broll = bool((broll_plan or {}).get("entries"))
    if has_broll:
        effects.append("approved_broll_plan")
    return {
        "choice": choice,
        "enabled": choice == "enabled",
        "confirmation_status": "confirmed" if choice in {"enabled", "disabled"} else "pending",
        "approved_effects": effects if choice == "enabled" else [],
        "visual_insert_policy": "approved_effects_only" if choice == "enabled" else "model_output_only",
        "broll_allowed": bool(choice == "enabled" and has_broll),
        "title_cards_allowed": bool(choice == "enabled" and any("title" in item.lower() or "标题" in item for item in effects)),
        "caption_mask_allowed": False,
        "rule": "When disabled, preserve the complete model-generated video without B-roll, title cards, cutaways, masks, or overlays.",
    }


def build_duration_plan(args, duration: int, model: dict, shots: list[dict], explicit_segments: list[dict]) -> dict:
    if args.duration is not None:
        source = "user_confirmed"
        confirmation_status = "confirmed"
    elif args.existing_video_file:
        source = "existing_video_timeline"
        confirmation_status = "confirmed"
    else:
        source = "model_default_unconfirmed"
        confirmation_status = "pending"
    maximum = int(model.get("max_duration_seconds") or duration)
    allowed_durations = model_allowed_durations(model)
    automatic_content_fit = any(bool(shot.get("automatic_content_fit")) for shot in shots)
    request_durations = [int(shot.get("duration_seconds") or 0) for shot in shots]
    exact_segment_scripts = [str(shot.get("script_segment") or "") for shot in shots]
    planned_duration = sum(request_durations)
    if automatic_content_fit:
        reason = "automatic_content_complete_model_safe_segments"
    elif explicit_segments:
        reason = "explicit_user_confirmed_segments"
    elif len(shots) == 1:
        reason = "single_segment_within_model_limit"
    else:
        reason = "confirmed_duration_exceeds_model_limit"
    estimated_script_seconds = round(sum(float((shot.get("script_pacing") or {}).get("estimated_spoken_seconds") or 0) for shot in shots), 2)
    spoken_fill_ratio = round(estimated_script_seconds / duration, 3) if duration else 0.0
    suggested_minimum_duration_seconds = max(1, int(estimated_script_seconds + 0.999))
    duration_metrics = build_duration_metrics(
        duration,
        request_durations,
        [shot.get("script_pacing") or {} for shot in shots],
    )
    segment_pacing_ok = all(
        (shot.get("script_pacing") or {}).get("status") in {"ok", "short_but_usable"}
        for shot in shots
    )
    digest_payload = canonical_duration_plan_payload(model, duration, request_durations, exact_segment_scripts)
    plan_digest = duration_plan_digest(model, duration, request_durations, exact_segment_scripts)
    return {
        "source": source,
        "confirmation_status": confirmation_status,
        "confirmed_duration_seconds": duration if confirmation_status == "confirmed" else None,
        "delivery_max_seconds": duration,
        "request_duration_seconds": request_durations,
        "planned_request_total_seconds": planned_duration,
        "duration_plan_digest": plan_digest,
        "duration_plan_digest_payload": digest_payload,
        "planned_duration_seconds": planned_duration,
        "model_max_segment_seconds": maximum,
        "allowed_request_durations_seconds": allowed_durations,
        "minimum_paid_segment_count": minimum_paid_segment_count(duration, model),
        "segment_count": len(shots),
        "segmentation_reason": reason,
        "estimated_script_seconds": estimated_script_seconds,
        "spoken_fill_ratio": spoken_fill_ratio,
        "target_spoken_fill_window": [0.85, 0.95],
        "minimum_multi_segment_spoken_fill_ratio": MINIMUM_MULTI_SEGMENT_SPOKEN_FILL_RATIO,
        "suggested_minimum_duration_seconds": suggested_minimum_duration_seconds,
        "script_fit_status": "ok" if segment_pacing_ok and duration_metrics["delivery_fit_status"] == "ok" else "revise",
        "automatic_content_fit": automatic_content_fit,
        "duration_tolerance": "hard_delivery_cap_with_local_tail_trim",
        "rule": "Use the fewest paid requests and only provider-supported duration slots. The user's duration is the final delivery maximum; trim verified idle tail locally, and shorten the script or extend the confirmed duration when speech cannot fit safely.",
        **duration_metrics,
    }


def build_image_consistency_plan(model: dict, strategy: str, confirmed_assets: list[dict], references: list[dict], segment_sources: list[dict]) -> dict:
    roles = [asset.get("role") for asset in confirmed_assets + references]
    return {
        "strategy": strategy,
        "model_mode": model.get("mode"),
        "source_image_becomes_first_frame": bool(model.get("source_image_becomes_first_frame", model.get("supports_image_to_video"))),
        "single_image_route_rule": "For image-to-video models like grok-imagine-video-1.5 / provider alias grok-video-1.5, the approved video_source/first_frame image is the real video input and becomes the first frame.",
        "storyboard_rule": "A multi-panel storyboard sheet is a planning/reference guide. Do not use it as the only source image for a single-image route.",
        "multi_reference_rule": "Only models configured with supports_reference_images=true may receive role, scene, last_frame, and storyboard references together.",
        "segment_source_rule": "For multi-segment videos, either reuse one approved shared source image for a continuous talking-head scene, or provide one approved segment_source image per segment when scene/pose changes are required.",
        "confirmed_visual_roles": roles,
        "segment_source_count": len(segment_sources),
        "segment_source_indices": sorted(int(asset.get("segment_index") or 0) for asset in segment_sources),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--project-root", default="projects")
    parser.add_argument("--content-mode", choices=CONTENT_MODES, required=True)
    parser.add_argument("--platform", default="douyin")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--source-language", default="")
    parser.add_argument("--target-language", default="")
    parser.add_argument("--target-locale", default="")
    parser.add_argument("--glossary-file")
    parser.add_argument("--translation-review-status", choices=("needs_user_confirmation", "verified"), default="needs_user_confirmation")
    parser.add_argument("--duration", type=int, default=None)
    parser.add_argument("--aspect-ratio")
    parser.add_argument("--resolution")
    parser.add_argument("--model-key")
    parser.add_argument("--config")
    parser.add_argument("--script-file")
    parser.add_argument("--script-text")
    parser.add_argument("--segments-file", help="Confirmed JSON segments with duration_seconds and complete script text for each generated clip.")
    parser.add_argument(
        "--duration-plan-only",
        action="store_true",
        help="Print the deterministic no-cost segment/duration proposal without creating a project or reading an API key.",
    )
    parser.add_argument("--avatar-reference")
    parser.add_argument("--video-source-image", help="Approved final source/first-frame image for single-image video routes.")
    parser.add_argument("--first-frame-image", help="Approved first-frame image. Shortcut for confirmed first_frame asset.")
    parser.add_argument("--last-frame-image", help="Approved last-frame target/reference image.")
    parser.add_argument("--storyboard-image", help="Approved storyboard or multi-panel storyboard image.")
    parser.add_argument("--segment-source-image", action="append", default=[], help="Approved per-segment source image as shot_01=path-or-url. Repeat once per segment when scenes/poses change.")
    parser.add_argument("--audio-file")
    parser.add_argument("--subtitle-file")
    parser.add_argument("--existing-video-file", help="Existing talking-head MP4 used as the timing authority for enhancement workflows.")
    parser.add_argument("--desired-output", default="new_avatar_video")
    parser.add_argument("--speech-source", default="generated_dialogue")
    parser.add_argument(
        "--speech-fidelity-mode",
        choices=("semantic_tolerance", "critical_facts_exact", "verbatim_required"),
        default="critical_facts_exact",
        help="Confirmed speech acceptance policy. Default preserves critical facts while allowing harmless non-semantic pronunciation variation.",
    )
    parser.add_argument("--timing-authority", default="script_and_target_duration")
    parser.add_argument("--source-fact-map", help="JSON list/object mapping factual script beats to source pages, FAQ ids, sections, or timestamps.")
    parser.add_argument("--require-source-fact-map", action="store_true", help="Block factual source-based projects until a non-empty verified source_fact_map is supplied.")
    parser.add_argument("--broll-plan", action="append", default=[])
    parser.add_argument("--subtitle-strategy", default="")
    parser.add_argument("--subtitle-choice", choices=("pending", "enabled", "disabled"), default="disabled", help="Default disabled. Use enabled only when the user explicitly requests subtitles during plan confirmation.")
    parser.add_argument("--subtitle-request-source", choices=("default", "user_plan_confirmation"), default="default", help="Required as user_plan_confirmation when --subtitle-choice enabled; this does not add a third confirmation.")
    parser.add_argument("--subtitle-whisper-model", default="", help="Local whisper.cpp model used only after clean-video review; never sent to the video provider.")
    parser.add_argument("--subtitle-whisper-cli", default="", help="Optional local whisper-cli path used only for postproduction transcription.")
    parser.add_argument("--effects-choice", choices=("pending", "enabled", "disabled"), default="pending", help="User-confirmed effects decision from the Stage B1 text proposal.")
    parser.add_argument("--effect", action="append", default=[], help="One explicitly approved visual effect. Repeat as needed when --effects-choice enabled.")
    parser.add_argument("--business-scenario", default="", help="Confirmed business scenario route, such as enterprise training, customer service FAQ, or multilingual localization.")
    parser.add_argument("--user-intent", default="", help="Confirmed viewer/business intent for the video.")
    parser.add_argument("--success-metric", default="", help="Scenario-specific acceptance or success metric.")
    parser.add_argument("--risk-boundary", default="", help="Compliance, claim, policy, privacy, or brand risk boundary.")
    parser.add_argument("--confirmed-asset", action="append", default=[], help="Confirmed asset as role=path-or-url. Repeat as needed.")
    parser.add_argument("--reference-image", action="append", default=[], help="Reference image as role=path-or-url. Repeat as needed.")
    parser.add_argument("--lipsync-required", action="store_true")
    parser.add_argument("--prompt", default="")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        model = get_model_config(config, args.model_key)
        default_aspect, default_resolution = platform_defaults(args.platform)
        if args.duration is not None:
            duration = args.duration
        elif args.existing_video_file:
            if is_url(args.existing_video_file):
                raise ScriptError("Existing-video postproduction requires a local video file so its timeline and digest can be verified.")
            source_media = media_summary(Path(args.existing_video_file).expanduser().resolve())
            duration = max(1, int(round(float(source_media.get("duration_seconds") or 0))))
        else:
            duration = int(model.get("default_duration_seconds", 15))
        script = read_script(args)
        explicit_segments = read_explicit_segments(args.segments_file, duration, model)
        if explicit_segments:
            combined_explicit_script = "".join(item["script"] for item in explicit_segments)
            approved_script = str(script.get("script_text") or "")
            if approved_script:
                normalize = lambda value: re.sub(r"\s+", "", value)
                if normalize(combined_explicit_script) != normalize(approved_script):
                    raise ScriptError(
                        "Explicit segments do not cover the complete approved script exactly. "
                        "Rebuild the segments from the approved script before paid generation."
                    )
            else:
                script["script_text"] = combined_explicit_script
        if args.duration_plan_only:
            print(
                json.dumps(
                    build_plan_only_result(
                        duration,
                        model,
                        script["script_text"],
                        args.language,
                        explicit_segments=explicit_segments,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        aspect_ratio = args.aspect_ratio or model.get("default_aspect_ratio") or default_aspect
        resolution = args.resolution or model.get("default_resolution") or default_resolution
        subtitle_strategy = default_subtitle_strategy(args.platform, args.language, aspect_ratio)

        project_name = sanitize_name(args.name)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        project_dir = Path(args.project_root).expanduser().resolve() / f"{stamp}-{project_name}"
        assets_dir = project_dir / "assets"
        for folder in (assets_dir, project_dir / "requests", project_dir / "clips", project_dir / "references"):
            folder.mkdir(parents=True, exist_ok=True)

        source_assets = []
        avatar_reference = None
        if args.avatar_reference:
            avatar_reference = copy_or_record_asset(args.avatar_reference, assets_dir, "avatar_reference", role="avatar_reference")
            avatar_reference["id"] = "avatar_reference"
            source_assets.append(avatar_reference)
        video_source_asset = None
        if args.video_source_image:
            video_source_asset = copy_or_record_asset(args.video_source_image, assets_dir, "video_source", role="video_source")
            video_source_asset["id"] = "video_source"
            source_assets.append(video_source_asset)
        first_frame_asset = None
        if args.first_frame_image:
            first_frame_asset = copy_or_record_asset(args.first_frame_image, assets_dir, "first_frame", role="first_frame")
            first_frame_asset["id"] = "first_frame"
            source_assets.append(first_frame_asset)
        last_frame_asset = None
        if args.last_frame_image:
            last_frame_asset = copy_or_record_asset(args.last_frame_image, assets_dir, "last_frame", role="last_frame")
            last_frame_asset["id"] = "last_frame"
            source_assets.append(last_frame_asset)
        storyboard_asset = None
        if args.storyboard_image:
            storyboard_asset = copy_or_record_asset(args.storyboard_image, assets_dir, "storyboard", role="storyboard")
            storyboard_asset["id"] = "storyboard"
            source_assets.append(storyboard_asset)
        audio_asset = None
        if args.audio_file:
            audio_asset = copy_or_record_asset(args.audio_file, assets_dir, "audio", role="audio")
            audio_asset["id"] = "audio"
            source_assets.append(audio_asset)
        subtitle_asset = None
        if args.subtitle_file:
            subtitle_asset = copy_or_record_asset(args.subtitle_file, assets_dir, "subtitle", role="subtitle")
            subtitle_asset["id"] = "subtitle"
            source_assets.append(subtitle_asset)
        existing_video_asset = None
        if args.existing_video_file:
            existing_video_asset = copy_or_record_asset(args.existing_video_file, assets_dir, "existing_video", role="existing_video")
            existing_video_asset["id"] = "existing_video"
            source_assets.append(existing_video_asset)
        glossary_asset = None
        if args.glossary_file:
            glossary_asset = copy_or_record_asset(args.glossary_file, project_dir / "references", "localization_glossary", role="localization_glossary")
            glossary_asset["id"] = "localization_glossary"
            source_assets.append(glossary_asset)
        references = collect_references(args.reference_image, assets_dir)
        if last_frame_asset:
            references.append({**last_frame_asset, "id": "reference_last_frame"})
        if storyboard_asset:
            references.append({**storyboard_asset, "id": "reference_storyboard"})
        segment_sources = collect_segment_sources(args.segment_source_image, assets_dir)
        confirmed_assets = collect_confirmed_assets(args.confirmed_asset, assets_dir)
        if video_source_asset:
            confirmed_assets.append(video_source_asset)
        if first_frame_asset:
            confirmed_assets.append(first_frame_asset)
        if avatar_reference:
            confirmed_assets.append(avatar_reference)
        confirmed_assets.extend(segment_sources)
        if audio_asset:
            confirmed_assets.append(audio_asset)
        if subtitle_asset:
            confirmed_assets.append(subtitle_asset)
        if existing_video_asset:
            confirmed_assets.append(existing_video_asset)

        source_fact_map = read_source_fact_map(args.source_fact_map)
        broll_plan = collect_broll_plan(args.broll_plan, project_dir)
        subtitle_plan = build_subtitle_plan(
            project_dir,
            subtitle_asset,
            subtitle_strategy,
            args.language,
            aspect_ratio,
            choice=args.subtitle_choice,
            request_source=args.subtitle_request_source,
            platform=args.platform,
            whisper_model=args.subtitle_whisper_model,
            whisper_executable=args.subtitle_whisper_cli,
        )
        effects_plan = build_effects_plan(args.effects_choice, args.effect, broll_plan)
        has_final_avatar_source = bool(avatar_reference or video_source_asset or first_frame_asset)
        avatar_plan = {
            "has_avatar_reference": bool(avatar_reference),
            "avatar_reference": avatar_reference,
            "has_final_video_source": bool(video_source_asset or first_frame_asset),
            "needs_generated_avatar_reference": not has_final_avatar_source,
            "message": "" if has_final_avatar_source else "需要生成原创数字人形象参考图，并让用户确认后再进入视频生成。",
        }
        has_audio = bool(audio_asset)
        has_subtitle = bool(subtitle_asset)
        tts_required = False if (has_audio or has_subtitle) else bool(model.get("supports_script_to_speech") and script.get("script_text"))
        warnings = model_warnings(model, args, has_audio, has_subtitle, script["script_text"])
        prompt = args.prompt or script.get("script_text") or f"{args.content_mode} talking-head video for {args.platform}"
        visual_bible = build_visual_bible(args, aspect_ratio, resolution, subtitle_strategy, effects_enabled=effects_plan["enabled"])
        shots = build_shots(duration, model, prompt, script["script_text"], references, confirmed_assets, segment_sources, visual_bible, args.language, explicit_segments=explicit_segments)
        script_pacing = build_script_pacing_summary(shots, duration, args.language, script["script_text"])
        duration_plan = build_duration_plan(args, duration, model, shots, explicit_segments)
        warnings.extend(script_pacing_warnings(script_pacing))
        warnings.extend(script_boundary_warnings(shots))
        warnings.extend(shot_prompt_warnings(model, shots))
        strategy = visual_asset_strategy(model, references, segment_sources)
        warnings.extend(asset_strategy_warnings(model, confirmed_assets, references, segment_sources, len(shots)))
        business_context = {
            "scenario": args.business_scenario,
            "user_intent": args.user_intent,
            "success_metric": args.success_metric,
            "risk_boundary": args.risk_boundary,
        }
        execution_route = determine_execution_route(
            content_mode=args.content_mode,
            desired_output=args.desired_output,
            speech_source=args.speech_source,
            timing_authority=args.timing_authority,
            has_existing_video=bool(existing_video_asset),
        )
        localization_enabled = bool(
            args.source_language
            or args.target_language
            or args.target_locale
            or "localization" in args.business_scenario.lower()
            or "multilingual" in args.business_scenario.lower()
            or "多语言" in args.business_scenario
        )
        localization_contract = {
            "enabled": localization_enabled,
            "source_language": args.source_language or args.language,
            "target_language": args.target_language or args.language,
            "target_locale": args.target_locale or args.target_language or args.language,
            "glossary_file": glossary_asset,
            "translation_review_status": args.translation_review_status if localization_enabled else "not_required",
            "localized_script_sha256": hashlib.sha256(script["script_text"].encode("utf-8")).hexdigest() if localization_enabled else "",
            "glossary_sha256": hashlib.sha256(Path(glossary_asset["value"]).read_bytes()).hexdigest() if localization_enabled and glossary_asset else "",
            "one_project_per_locale": True,
            "version_id": f"{args.target_language or args.language}-{args.target_locale or args.target_language or args.language}" if localization_enabled else "",
            "rule": "Create one independently confirmed project and delivery manifest per target language/locale.",
        }
        blocking_reasons = paid_generation_blocking_reasons(
            model,
            args,
            avatar_plan,
            confirmed_assets,
            references,
            warnings,
            script_pacing,
            source_fact_map=source_fact_map,
            business_context=business_context,
            localization_contract=localization_contract,
            execution_route=execution_route,
            creative_choices={"subtitle": subtitle_plan, "effects": effects_plan},
            duration_plan=duration_plan,
        )
        postproduction_operations = ["preserve approved source speech and timing"]
        if effects_plan["enabled"]:
            postproduction_operations.append("apply only explicitly approved effects and B-roll")
        postproduction_plan = {
            "enabled": execution_route == "postproduction_only",
            "source_video": existing_video_asset,
            "timing_authority": args.timing_authority,
            "preserve_source_speech": execution_route == "postproduction_only",
            "broll_plan": broll_plan,
            "subtitle_plan": subtitle_plan,
            "effects_plan": effects_plan,
            "required_operations": postproduction_operations if execution_route == "postproduction_only" else [],
            "candidate_output": str(project_dir / "final.postproduced.mp4"),
            "edit_manifest": str(project_dir / "postproduction-manifest.json"),
            "technical_review": str(project_dir / "final-review.json"),
            "visual_review": str(project_dir / "visual-review.json"),
            "paid_video_generation_requests": 0 if execution_route == "postproduction_only" else len(shots),
        }

        requests_dir = project_dir / "requests"
        clips_dir = project_dir / "clips"
        for shot in shots:
            shot["request_file"] = str(requests_dir / f"{shot['id']}_request.json")
            shot["clip_file"] = str(clips_dir / f"{shot['id']}.mp4")

        manifest = {
            "project_name": project_name,
            "created_at": stamp,
            "project_dir": str(project_dir),
            "skill": "ai-creator-talking-head-video",
            "model_key": model["key"],
            "model": model.get("model"),
            "model_adapter": model_adapter_disclosure(model),
            "model_capabilities": {
                "skill_adapter_status": model.get("skill_adapter_status", ""),
                "adapter_supported_inputs": model.get("adapter_supported_inputs", []),
                "adapter_unsupported_provider_features": model.get("adapter_unsupported_provider_features", []),
                "supports_image_to_video": bool(model.get("supports_image_to_video")),
                "supports_reference_images": bool(model.get("supports_reference_images")),
                "max_reference_images": model.get("max_reference_images"),
                "supports_audio_input": bool(model.get("supports_audio_input")),
                "supports_lipsync": bool(model.get("supports_lipsync")),
                "supports_script_to_speech": bool(model.get("supports_script_to_speech")),
                "lipsync_mode": model.get("lipsync_mode", ""),
                "external_audio_lipsync": bool(model.get("external_audio_lipsync")),
                "supports_avatar_reference": bool(model.get("supports_avatar_reference")),
                "supports_text_to_video": bool(model.get("supports_text_to_video")),
                "source_image_becomes_first_frame": bool(model.get("source_image_becomes_first_frame", model.get("supports_image_to_video"))),
                "supports_reference_to_video": bool(model.get("supports_reference_to_video", model.get("supports_reference_images"))),
                "max_duration_seconds": model.get("max_duration_seconds"),
                "allowed_durations_seconds": model_allowed_durations(model),
                "max_script_chars": model.get("max_script_chars"),
            },
            "content_mode": args.content_mode,
            "business_scenario": args.business_scenario,
            "business_context": business_context,
            "localization_contract": localization_contract,
            "platform": args.platform,
            "language": args.language,
            "total_duration_seconds": duration,
            "delivery_duration_seconds": duration_plan["delivery_max_seconds"],
            "duration_plan": duration_plan,
            "duration_plan_digest": duration_plan["duration_plan_digest"],
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "avatar_reference": avatar_reference,
            "video_source_image": video_source_asset,
            "first_frame_image": first_frame_asset,
            "last_frame_image": last_frame_asset,
            "storyboard_image": storyboard_asset,
            "avatar_plan": avatar_plan,
            "script_file": script["script_file"],
            "script_text": script["script_text"],
            "script_segmentation": {
                "source": "explicit_segments_file" if explicit_segments else "automatic_sentence_boundaries",
                "segments_file": str(Path(args.segments_file).expanduser().resolve()) if args.segments_file else "",
                "segment_count": len(shots),
                "unsafe_character_fallback_allowed": False,
            },
            "audio_file": audio_asset,
            "subtitle_file": subtitle_asset,
            "existing_video_file": existing_video_asset,
            "execution_route": execution_route,
            "intake_route": {
                "desired_output": args.desired_output,
                "speech_source": args.speech_source,
                "timing_authority": args.timing_authority,
            },
            "speech_fidelity_mode": args.speech_fidelity_mode,
            "source_fact_map": source_fact_map,
            "source_fact_map_required": bool(args.require_source_fact_map or args.source_fact_map),
            "broll_plan": broll_plan,
            "effects_plan": effects_plan,
            "creative_choices": {
                "confirmation_mode": "single_production_package",
                "subtitle": subtitle_plan,
                "effects": effects_plan,
                "duration": duration_plan,
            },
            "subtitle_strategy": subtitle_strategy,
            "subtitle_plan": subtitle_plan,
            "postproduction_plan": postproduction_plan,
            "script_pacing": script_pacing,
            "visual_bible": visual_bible,
            "visual_asset_strategy": strategy,
            "image_consistency_plan": build_image_consistency_plan(model, strategy, confirmed_assets, references, segment_sources),
            "longform_generation_strategy": build_longform_strategy(shots, model),
            "stitching_plan": build_stitching_plan(
                project_dir,
                shots,
                aspect_ratio,
                resolution,
                auto_trim_tail_silence=default_auto_trim_tail_silence(
                    content_mode=args.content_mode,
                    speech_source=args.speech_source,
                    timing_authority=args.timing_authority,
                    has_audio=bool(audio_asset),
                    has_subtitle=bool(subtitle_asset),
                    has_existing_video=bool(existing_video_asset),
                ),
            ),
            "confirmed_assets": confirmed_assets,
            "references": references,
            "segment_sources": segment_sources,
            "source_assets": source_assets,
            "generation_requirements": {
                "lipsync_required": bool(args.lipsync_required),
                "tts_required": bool(tts_required),
                "strict_lipsync_supported": bool(args.lipsync_required and model.get("supports_lipsync") and (model.get("supports_audio_input") or model.get("supports_script_to_speech"))),
            },
            "asset_contract": {
                "confirmed_asset_roles": [asset.get("role") for asset in confirmed_assets],
                "has_existing_audio": has_audio,
                "has_existing_subtitle": has_subtitle,
                "subtitle_strategy": subtitle_strategy,
                "subtitle_plan": subtitle_plan,
                "effects_plan": effects_plan,
                "broll_plan": broll_plan,
                "multi_segment_consistency": "All shots reuse one visual_bible and the same confirmed source/reference assets.",
                "visual_asset_strategy": strategy,
                "segment_source_count": len(segment_sources),
            },
            "warnings": warnings,
            "blocking_reasons": blocking_reasons,
            "ready_for_paid_generation": not blocking_reasons,
            "shots": shots,
        }
        write_json(project_dir / "manifest.json", manifest)
        write_json(project_dir / "generation-plan.json", manifest)
        print(json.dumps({"ok": True, "project_dir": str(project_dir), "plan": str(project_dir / "generation-plan.json"), "warnings": warnings}, ensure_ascii=False, indent=2))
        return 0
    except (ScriptError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
