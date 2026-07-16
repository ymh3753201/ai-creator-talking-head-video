#!/usr/bin/env python3
"""Preflight the free local runtime used for optional postproduction subtitles."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from subtitle_policy import enabled_subtitle_contract_errors


WHISPER_MODEL_ENV = "AI_CREATOR_TALKING_HEAD_VIDEO_WHISPER_MODEL"
WHISPER_CLI_ENV = "AI_CREATOR_TALKING_HEAD_VIDEO_WHISPER_CLI"
DEFAULT_MODEL_CANDIDATES = (
    Path.home() / ".codex" / "models" / "whisper" / "ggml-small.bin",
    Path.home() / ".cache" / "whisper.cpp" / "ggml-small.bin",
)


def _asset_path(asset: object) -> Path | None:
    if isinstance(asset, dict):
        value = asset.get("value") or asset.get("path")
    else:
        value = asset
    if not str(value or "").strip():
        return None
    return Path(str(value)).expanduser().resolve()


def whisper_executable(subtitle_plan: dict) -> Path | None:
    configured = subtitle_plan.get("whisper_executable") or os.getenv(WHISPER_CLI_ENV)
    if configured:
        path = Path(str(configured)).expanduser().resolve()
        return path if path.is_file() else None
    discovered = shutil.which("whisper-cli") or shutil.which("main")
    return Path(discovered).resolve() if discovered else None


def whisper_model(subtitle_plan: dict) -> Path | None:
    configured = subtitle_plan.get("whisper_model") or os.getenv(WHISPER_MODEL_ENV) or os.getenv("WHISPER_CPP_MODEL")
    candidates = [Path(str(configured)).expanduser().resolve()] if configured else list(DEFAULT_MODEL_CANDIDATES)
    return next((path for path in candidates if path.is_file() and path.stat().st_size > 0), None)


def ffmpeg_has_subtitles_filter() -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.returncode == 0 and any(
        line.strip().startswith("T.C subtitles") or " subtitles " in line
        for line in proc.stdout.splitlines()
    )


def subtitle_runtime_errors(plan: dict) -> list[str]:
    subtitle_plan = plan.get("subtitle_plan") or {}
    if not subtitle_plan.get("enabled"):
        return []
    errors = enabled_subtitle_contract_errors(subtitle_plan)
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        errors.append("FFmpeg and ffprobe are required for local subtitle postproduction.")
    elif not ffmpeg_has_subtitles_filter():
        errors.append("The installed FFmpeg does not expose the subtitles/libass filter required for local burn-in.")

    timing_source = str(subtitle_plan.get("timing_source") or "local_whisper_cpp")
    if timing_source == "provided_srt":
        supplied = _asset_path(subtitle_plan.get("input_subtitle"))
        if not supplied or not supplied.is_file():
            errors.append("Provided SRT timing was selected, but input_subtitle is missing or unreadable.")
    elif timing_source == "local_whisper_cpp":
        if not whisper_executable(subtitle_plan):
            errors.append(
                "whisper-cli is required for local subtitle transcription. Set "
                f"{WHISPER_CLI_ENV} or install whisper.cpp."
            )
        if not whisper_model(subtitle_plan):
            errors.append(
                "Whisper model is required for local subtitle transcription. Set "
                f"{WHISPER_MODEL_ENV} or place ggml-small.bin in ~/.codex/models/whisper/."
            )
    else:
        errors.append(f"Unsupported subtitle timing_source={timing_source!r}.")
    return errors


def resolved_subtitle_runtime(plan: dict) -> dict:
    subtitle_plan = plan.get("subtitle_plan") or {}
    timing_source = str(subtitle_plan.get("timing_source") or "local_whisper_cpp")
    supplied = _asset_path(subtitle_plan.get("input_subtitle"))
    executable = whisper_executable(subtitle_plan)
    model = whisper_model(subtitle_plan)
    return {
        "timing_source": timing_source,
        "input_subtitle": str(supplied) if supplied else "",
        "whisper_executable": str(executable) if executable else "",
        "whisper_model": str(model) if model else "",
        "ffmpeg": shutil.which("ffmpeg") or "",
        "ffprobe": shutil.which("ffprobe") or "",
    }
