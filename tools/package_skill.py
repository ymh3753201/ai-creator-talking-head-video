#!/usr/bin/env python3
"""Build a deterministic and clean ai-creator-talking-head-video .skill archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True

from audit_release import SKILL_NAME, audit


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / SKILL_NAME
FORBIDDEN_PARTS = {"__pycache__", ".pytest_cache", "projects", "outputs", "clips", "requests", ".stitch_tmp", "evals"}
FORBIDDEN_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".env",
    ".mp4",
    ".mov",
    ".webm",
    ".mkv",
    ".wav",
    ".mp3",
    ".srt",
    ".vtt",
    ".log",
}
FIXED_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def package_files(skill_root: Path) -> list[Path]:
    files = []
    for path in skill_root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(skill_root)
        if any(part in FORBIDDEN_PARTS for part in relative.parts):
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name in {".DS_Store", ".env.local"}:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(skill_root).as_posix())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_archive(skill_root: Path, output: Path) -> list[str]:
    output.parent.mkdir(parents=True, exist_ok=True)
    names = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in package_files(skill_root):
            relative = path.relative_to(skill_root).as_posix()
            name = f"{SKILL_NAME}/{relative}"
            info = zipfile.ZipInfo(name, FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.stat().st_mode & 0o111 else 0o644) << 16
            archive.writestr(info, path.read_bytes())
            names.append(name)
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository root")
    parser.add_argument("--output", default=f"dist/{SKILL_NAME}.skill", help="Output .skill path")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    skill_root = root / SKILL_NAME
    output = Path(args.output).expanduser()
    if not output.is_absolute():
        output = (root / output).resolve()

    audit_report = audit(root)
    if not audit_report["ok"]:
        print(json.dumps({"ok": False, "audit": audit_report}, ensure_ascii=False, indent=2))
        return 1

    names = write_archive(skill_root, output)
    required = {
        f"{SKILL_NAME}/SKILL.md",
        f"{SKILL_NAME}/LICENSE",
        f"{SKILL_NAME}/agents/openai.yaml",
        f"{SKILL_NAME}/scripts/prepare_project.py",
        f"{SKILL_NAME}/scripts/workflow_engine.py",
    }
    missing = sorted(required.difference(names))
    if missing:
        output.unlink(missing_ok=True)
        print(json.dumps({"ok": False, "error": f"Archive missing required files: {missing}"}, ensure_ascii=False, indent=2))
        return 1

    report = {
        "ok": True,
        "output": str(output),
        "file_count": len(names),
        "size_bytes": output.stat().st_size,
        "sha256": sha256_file(output),
        "audit_warnings": audit_report["warnings"],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
