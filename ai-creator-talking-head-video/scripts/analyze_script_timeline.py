#!/usr/bin/env python3
"""Estimate a talking-head script timeline and B-roll beats."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def estimate_seconds(text: str, language: str) -> float:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return 0.0
    if language.lower().startswith("en"):
        words = len(re.findall(r"[A-Za-z0-9']+", clean))
        return max(1.5, words / 2.4)
    cjk = len(re.findall(r"[\u4e00-\u9fff]", clean))
    other_words = len(re.findall(r"[A-Za-z0-9']+", clean))
    return max(1.5, cjk / 4.8 + other_words / 2.4)


def split_paragraphs(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\n\s*\n|(?<=[。！？!?])\s+", text) if part.strip()]
    return parts or [text.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script-file")
    parser.add_argument("--script-text")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--output")
    args = parser.parse_args()
    text = args.script_text or ""
    if args.script_file:
        text = Path(args.script_file).expanduser().read_text(encoding="utf-8")
    paragraphs = split_paragraphs(text)
    cursor = 0.0
    segments = []
    for index, paragraph in enumerate(paragraphs, start=1):
        seconds = round(estimate_seconds(paragraph, args.language), 1)
        segment = {
            "id": f"beat_{index:02d}",
            "start_second": round(cursor, 1),
            "end_second": round(cursor + seconds, 1),
            "estimated_duration_seconds": seconds,
            "spoken_text": paragraph,
            "broll_suggestion": "Use screenshot, keyword card, example visual, or screen recording that directly supports this spoken beat.",
            "subtitle_emphasis": paragraph[:24],
        }
        segments.append(segment)
        cursor += seconds
    result = {"language": args.language, "total_estimated_seconds": round(cursor, 1), "segments": segments}
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).expanduser().write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
