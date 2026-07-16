#!/usr/bin/env python3
"""Audit the public repository before publishing or packaging the Skill."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "ai-creator-talking-head-video"
SKILL_ROOT = REPO_ROOT / SKILL_NAME
IGNORED_PARTS = {".git", "dist", "projects", "outputs", ".pytest_cache"}
FORBIDDEN_PARTS = {"__pycache__", ".stitch_tmp"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".mp4", ".mov", ".webm", ".mkv", ".wav", ".mp3", ".log"}
TEXT_SUFFIXES = {".md", ".py", ".json", ".example", ".yml", ".yaml", ".gitignore"}
SECRET_PATTERNS = {
    "private API key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "literal bearer token": re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}\b"),
    "GitHub token": re.compile(r"\bgh[opusr]_[A-Za-z0-9_]{20,}\b"),
    "developer absolute path": re.compile(r"/(?:Users|Volumes)/[^\s`\"']+"),
    "non-empty private env assignment": re.compile(
        r"(?m)^(?:AI_CREATOR_TALKING_HEAD_VIDEO_API_KEY|AI_TALKING_HEAD_VIDEO_API_KEY|"
        r"YUNWU_API_KEY|XAI_API_KEY|FAL_KEY)=\S+"
    ),
}
REQUIRED_FILES = (
    "README.md",
    "LICENSE",
    ".gitignore",
    "CONTRIBUTING.md",
    "SECURITY.md",
    ".github/workflows/tests.yml",
    f"{SKILL_NAME}/SKILL.md",
    f"{SKILL_NAME}/LICENSE",
    f"{SKILL_NAME}/agents/openai.yaml",
    f"{SKILL_NAME}/assets/templates/env.example",
    f"{SKILL_NAME}/assets/templates/model-config.example.json",
    f"{SKILL_NAME}/evals/evals.json",
    f"{SKILL_NAME}/references/workflow.md",
    f"{SKILL_NAME}/scripts/prepare_project.py",
    f"{SKILL_NAME}/scripts/preflight_project.py",
    "tests/test_ai_creator_talking_head_video_skill.py",
    "tests/test_ai_creator_talking_head_workflow_engine.py",
    "tests/test_talking_head_open_source_release.py",
    "tools/package_skill.py",
)


def included_files(root: Path) -> list[Path]:
    result = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        result.append(path)
    return sorted(result)


def markdown_link_errors(path: Path, root: Path) -> list[str]:
    errors = []
    text = path.read_text(encoding="utf-8")
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        local_target = target.split("#", 1)[0]
        if not local_target:
            continue
        destination = (path.parent / local_target).resolve()
        try:
            destination.relative_to(root)
        except ValueError:
            errors.append(f"{path.relative_to(root)} link escapes repository: {target}")
            continue
        if not destination.exists():
            errors.append(f"{path.relative_to(root)} has broken link: {target}")
    return errors


def audit(root: Path) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    files = included_files(root)

    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            errors.append(f"Missing required release file: {relative}")

    for path in files:
        relative = path.relative_to(root)
        if any(part in FORBIDDEN_PARTS for part in relative.parts):
            errors.append(f"Runtime cache must not be published: {relative}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"Generated media/runtime file must not be published: {relative}")
        if path.name in {".env", ".env.local"} or (
            path.suffix == ".env" and path.name != "env.example"
        ):
            errors.append(f"Private env file must not be published: {relative}")
        if path.is_symlink():
            errors.append(f"Symlinks are not allowed in the release tree: {relative}")

        if path.suffix == ".py":
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(relative), feature_version=(3, 10))
            except SyntaxError as exc:
                errors.append(f"Python 3.10 syntax error in {relative}: {exc}")
        if path.suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                errors.append(f"Invalid JSON in {relative}: {exc}")
        if path.suffix == ".md":
            errors.extend(markdown_link_errors(path, root))

        if path.suffix.lower() in TEXT_SUFFIXES or path.name == ".gitignore":
            text = path.read_text(encoding="utf-8", errors="replace")
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(text):
                    errors.append(f"{label} found in {relative}")

    if (root / "LICENSE").read_bytes() != (root / SKILL_NAME / "LICENSE").read_bytes():
        errors.append("Repository and standalone Skill licenses differ")

    env_example = root / SKILL_NAME / "assets/templates/env.example"
    if env_example.exists():
        for line in env_example.read_text(encoding="utf-8").splitlines():
            if line.startswith(("AI_CREATOR_TALKING_HEAD_VIDEO_API_KEY=", "FAL_KEY=")) and line.split("=", 1)[1]:
                errors.append("env.example must not contain a video API key")

    config_path = root / SKILL_NAME / "assets/templates/model-config.example.json"
    readme_path = root / "README.md"
    if config_path.exists() and readme_path.exists():
        config_text = config_path.read_text(encoding="utf-8")
        readme = readme_path.read_text(encoding="utf-8")
        if "api.119337.xyz" in config_text and "third-party gateway" not in readme:
            errors.append("README must disclose that the bundled 119337 route is a third-party gateway")
        if "api.119337.xyz" in config_text:
            warnings.append("Bundled example includes a third-party gateway; users must review it before use")

    return {
        "ok": not errors,
        "root": str(root),
        "files_scanned": len(files),
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository root")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    report = audit(root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
