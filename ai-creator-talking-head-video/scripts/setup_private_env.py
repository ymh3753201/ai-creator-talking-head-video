#!/usr/bin/env python3
"""Create a private runtime env file for ai-creator-talking-head-video."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path


DEFAULT_ENV_FILE = Path.home() / ".codex" / "ai-creator-talking-head-video.env"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--base-url", default="https://api.119337.xyz/v1")
    parser.add_argument("--model", default="grok-video-1.5")
    parser.add_argument("--key-stdin", action="store_true", help="Read the video API key from stdin for non-interactive setup without exposing it in shell history.")
    parser.add_argument("--fal-key-stdin", action="store_true", help="Read an optional FAL_KEY from the next stdin line without exposing it in shell history.")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser().resolve()
    if env_file.exists() and not args.force:
        print(f"ERROR: env file already exists: {env_file}")
        print("Re-run with --force if you want to replace it.")
        return 1

    if args.key_stdin:
        api_key = sys.stdin.readline().strip()
    else:
        api_key = getpass.getpass("Video API key: ").strip()
    if not api_key:
        print("ERROR: API key is empty")
        return 1

    env_file.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f"AI_CREATOR_TALKING_HEAD_VIDEO_API_KEY={api_key}\n"
        f"AI_CREATOR_TALKING_HEAD_VIDEO_BASE_URL={args.base_url.rstrip('/')}\n"
        f"AI_CREATOR_TALKING_HEAD_VIDEO_MODEL={args.model}\n"
    )
    fal_key = sys.stdin.readline().strip() if args.fal_key_stdin else ""
    if fal_key:
        content += f"FAL_KEY={fal_key}\n"
    old_umask = os.umask(0o077)
    try:
        env_file.write_text(content, encoding="utf-8")
        env_file.chmod(0o600)
    finally:
        os.umask(old_umask)

    print(f"Private video API env file written: {env_file}")
    print("Key saved locally only. Do not commit or package this file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
