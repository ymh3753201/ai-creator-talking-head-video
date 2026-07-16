#!/usr/bin/env python3
"""Deterministic execution-route rules for talking-head projects."""

from __future__ import annotations


POSTPRODUCTION_OUTPUTS = {
    "existing_video_enhancement",
    "existing_video_edit",
    "multi_platform_repackage",
    "broll_caption_packaging",
}
EXTERNAL_AUDIO_VALUES = {"external_audio", "provided_audio", "user_audio"}
EXISTING_VIDEO_TIMING_VALUES = {"existing_video", "existing_video_audio", "source_video"}
EXTERNAL_SUBTITLE_TIMING_VALUES = {"external_subtitle", "provided_subtitle", "user_subtitle"}


def determine_execution_route(
    content_mode: str,
    desired_output: str,
    speech_source: str,
    timing_authority: str,
    has_existing_video: bool,
) -> str:
    desired = str(desired_output or "").strip().lower()
    speech = str(speech_source or "").strip().lower()
    timing = str(timing_authority or "").strip().lower()
    if has_existing_video and (
        desired in POSTPRODUCTION_OUTPUTS
        or timing in EXISTING_VIDEO_TIMING_VALUES
        or content_mode == "hybrid_broll_edit"
    ):
        return "postproduction_only"
    if speech in EXTERNAL_AUDIO_VALUES or timing in EXTERNAL_AUDIO_VALUES:
        return "external_audio_generation"
    return "video_generation"


def infer_execution_route(plan: dict) -> str:
    explicit = str(plan.get("execution_route") or "").strip()
    if explicit:
        return explicit
    intake = plan.get("intake_route") or {}
    return determine_execution_route(
        content_mode=str(plan.get("content_mode") or ""),
        desired_output=str(intake.get("desired_output") or ""),
        speech_source=str(intake.get("speech_source") or ""),
        timing_authority=str(intake.get("timing_authority") or ""),
        has_existing_video=bool(plan.get("existing_video_file")),
    )


def uses_external_subtitle_timing(plan: dict) -> bool:
    timing = str((plan.get("intake_route") or {}).get("timing_authority") or "").strip().lower()
    return timing in EXTERNAL_SUBTITLE_TIMING_VALUES
