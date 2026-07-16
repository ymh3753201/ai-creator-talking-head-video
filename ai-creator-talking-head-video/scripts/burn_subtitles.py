#!/usr/bin/env python3
"""Burn SRT subtitles into a talking-head MP4 delivery copy."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from _common import ScriptError, load_json, media_summary, require_ffmpeg, write_json
from subtitle_policy import enabled_subtitle_contract_errors
from subtitle_profiles import build_ass_style
from subtitle_runtime import subtitle_runtime_errors

def escape_filter_path(path: Path) -> str:
    text = str(path)
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def build_command(video: Path, srt: Path, output: Path, style: str, original_size: str = "") -> list[str]:
    options = [f"subtitles='{escape_filter_path(srt)}'"]
    if original_size:
        options.append(f"original_size={original_size}")
    options.append(f"force_style='{style}'")
    subtitle_filter = ":".join(options)
    return [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i", str(video),
        "-vf", subtitle_filter,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(output),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--srt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        plan_path = Path(args.plan).expanduser().resolve()
        plan = load_json(plan_path)
        subtitle_plan = plan.get("subtitle_plan") or {}
        if not subtitle_plan.get("enabled"):
            raise ScriptError("Postproduction subtitles are disabled for this confirmed plan.")
        contract_errors = enabled_subtitle_contract_errors(subtitle_plan, prefix="Subtitle burn")
        if contract_errors:
            raise ScriptError(" ".join(contract_errors))
        runtime_errors = subtitle_runtime_errors(plan)
        if runtime_errors:
            raise ScriptError(" ".join(runtime_errors))
        require_ffmpeg()
        video = Path(args.video).expanduser().resolve()
        srt = Path(args.srt).expanduser().resolve()
        output = Path(args.output).expanduser().resolve()
        if not video.exists():
            raise ScriptError(f"Video not found: {video}")
        if not srt.exists():
            raise ScriptError(f"SRT not found: {srt}")
        output.parent.mkdir(parents=True, exist_ok=True)
        summary = media_summary(video)
        video_stream = summary.get("video") or {}
        width = int(video_stream.get("width") or 0)
        height = int(video_stream.get("height") or 0)
        original_size = f"{width}x{height}" if width > 0 and height > 0 else ""
        profile = subtitle_plan.get("profile") or {}
        if not profile.get("id"):
            raise ScriptError("Confirmed subtitle plan is missing its platform style profile.")
        style = build_ass_style(profile, width, height)
        cmd = build_command(video, srt, output, style, original_size)
        if args.dry_run:
            print(json.dumps({
                "ok": True,
                "dry_run": True,
                "command": cmd,
                "output": str(output),
                "profile_id": profile.get("id"),
                "provider_payload_used": False,
                "paid_api_call": False,
            }, ensure_ascii=False, indent=2))
            return 0
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise ScriptError(f"ffmpeg subtitle burn failed: {proc.stderr.strip()}")
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        audit = {
            "ok": True,
            "input_video": str(video),
            "input_video_sha256": digest(video),
            "subtitle": str(srt),
            "subtitle_sha256": digest(srt),
            "output": str(output),
            "output_sha256": digest(output),
            "profile_id": profile.get("id"),
            "ass_style": style,
            "provider_payload_used": False,
            "paid_api_call": False,
        }
        audit_path = Path(
            subtitle_plan.get("burn_audit_output") or output.parent / "subtitles" / "burn.audit.json"
        ).expanduser().resolve()
        write_json(audit_path, audit)
        print(json.dumps({**audit, "audit": str(audit_path)}, ensure_ascii=False, indent=2))
        return 0
    except (ScriptError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
