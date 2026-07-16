#!/usr/bin/env python3
"""Resolve platform-safe postproduction subtitle styles."""

from __future__ import annotations

import json
from pathlib import Path

from _common import ScriptError


DEFAULT_PROFILE_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "templates"
    / "subtitle-style-profiles.example.json"
)

LIBASS_SRT_PLAY_RES_X = 384
LIBASS_SRT_PLAY_RES_Y = 288


def load_profile_config(config_path: Path | None = None) -> dict:
    path = Path(config_path or DEFAULT_PROFILE_PATH).expanduser().resolve()
    if not path.exists():
        raise ScriptError(f"Subtitle style profile config not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScriptError(f"Invalid subtitle style profile JSON: {exc}") from exc
    if not isinstance(data.get("profiles"), dict) or not data["profiles"]:
        raise ScriptError("Subtitle style profile config requires a non-empty profiles object")
    return data


def profile_id_for(platform: str, aspect_ratio: str, config: dict) -> str:
    normalized = str(platform or "").strip().lower()
    aliases = config.get("platform_aliases") or {}
    profile_id = str(aliases.get(normalized) or "")
    profiles = config.get("profiles") or {}
    if profile_id and profile_id in profiles:
        candidate = profiles[profile_id]
        if not aspect_ratio or candidate.get("aspect_ratio") == aspect_ratio:
            return profile_id
    return "generic_vertical" if aspect_ratio == "9:16" else "generic_horizontal"


def resolve_subtitle_profile(
    platform: str,
    aspect_ratio: str,
    config_path: Path | None = None,
) -> dict:
    config = load_profile_config(config_path)
    profile_id = profile_id_for(platform, aspect_ratio, config)
    profile = dict((config.get("profiles") or {}).get(profile_id) or {})
    profile["id"] = profile_id
    profile["font_candidates"] = list(config.get("default_fonts") or [])
    profile["config_path"] = str(Path(config_path or DEFAULT_PROFILE_PATH).expanduser().resolve())
    return profile


def build_ass_style(profile: dict, width: int, height: int, font_name: str | None = None) -> str:
    if width <= 0 or height <= 0:
        raise ScriptError("Subtitle style requires a positive video width and height")
    short_edge = min(width, height)
    target_font_px = max(18, round(short_edge * float(profile.get("font_short_edge_ratio") or 0.05)))
    target_outline_px = max(1, round(short_edge * float(profile.get("outline_short_edge_ratio") or 0.0025)))
    target_margin_l_px = max(0, round(width * float(profile.get("margin_left_ratio") or 0.08)))
    target_margin_r_px = max(0, round(width * float(profile.get("margin_right_ratio") or 0.08)))
    target_margin_v_px = max(0, round(height * float(profile.get("margin_bottom_ratio") or 0.09)))

    # FFmpeg's subtitles filter parses SRT through libass in a 384x288 script
    # coordinate space. Supplying output pixels directly makes 720p text and
    # margins roughly 2.5x too large. Convert the platform profile's target
    # output pixels into that script space before writing force_style.
    font_size = max(7, round(target_font_px * LIBASS_SRT_PLAY_RES_Y / height))
    outline = max(1, round(target_outline_px * LIBASS_SRT_PLAY_RES_Y / height))
    margin_l = max(0, round(target_margin_l_px * LIBASS_SRT_PLAY_RES_X / width))
    margin_r = max(0, round(target_margin_r_px * LIBASS_SRT_PLAY_RES_X / width))
    margin_v = max(0, round(target_margin_v_px * LIBASS_SRT_PLAY_RES_Y / height))
    selected_font = font_name or next(iter(profile.get("font_candidates") or []), "Arial")
    return ",".join((
        f"FontName={selected_font}",
        f"FontSize={font_size}",
        f"PrimaryColour={profile.get('primary_color') or '&H00FFFFFF'}",
        f"OutlineColour={profile.get('outline_color') or '&H80000000'}",
        "BackColour=&HFF000000",
        "BorderStyle=1",
        f"Outline={outline}",
        "Shadow=0",
        f"Alignment={int(profile.get('alignment') or 2)}",
        f"MarginL={margin_l}",
        f"MarginR={margin_r}",
        f"MarginV={margin_v}",
    ))
