#!/usr/bin/env python3
"""Production contracts and durable job state for the talking-head workflow."""

from __future__ import annotations

import hashlib
import json
import os
import time
import fcntl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, TextIO

from _common import ScriptError, asset_value, is_url, load_json


CONTRACT_VERSION = "1.0"
LEDGER_VERSION = "1.0"
JOB_STATES = ("planned", "submitting", "submitted", "polling", "downloaded", "verified", "failed")
ALLOWED_TRANSITIONS = {
    "planned": {"submitting"},
    "submitting": {"submitted", "failed"},
    "submitted": {"polling", "downloaded", "failed"},
    "polling": {"downloaded", "failed"},
    "downloaded": {"verified", "failed"},
    "verified": {"verified"},
    "failed": {"submitting", "polling", "failed"},
}
SECRET_KEY_PARTS = ("api_key", "authorization", "bearer", "secret", "token")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def acquire_paid_submission_lock(project_dir: Path) -> TextIO:
    lock_path = project_dir / ".paid-submit.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise ScriptError(f"Another paid submission is already running for this project: {lock_path}") from exc
    handle.seek(0)
    handle.truncate()
    handle.write(json.dumps({"pid": os.getpid(), "locked_at": int(time.time())}) + "\n")
    handle.flush()
    os.fsync(handle.fileno())
    return handle


def release_paid_submission_lock(handle: TextIO | None) -> None:
    if handle is None or handle.closed:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def fingerprint_asset(asset: dict) -> dict:
    value = asset_value(asset)
    result = {
        "id": str(asset.get("id") or ""),
        "role": str(asset.get("role") or ""),
        "kind": str(asset.get("kind") or ("url" if is_url(value) else "file")),
    }
    if not value:
        result.update({"status": "missing_value", "sha256": ""})
        return result
    if value.startswith("data:"):
        result.update({"status": "data_uri", "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(), "size_bytes": len(value.encode("utf-8"))})
        return result
    if is_url(value):
        digest = hashlib.sha256()
        size = 0
        request = urllib.request.Request(value, headers={"User-Agent": "ai-creator-talking-head-video-skill/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    digest.update(block)
                    size += len(block)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            result.update({
                "status": "remote_unavailable",
                "sha256": "",
                "url_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                "error": str(exc),
            })
            return result
        result.update({
            "status": "remote_content",
            "sha256": digest.hexdigest(),
            "size_bytes": size,
            "url_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        })
        return result
    path = Path(value).expanduser().resolve()
    if not path.exists() or not path.is_file():
        result.update({"status": "missing_file", "sha256": "", "path": str(path)})
        return result
    result.update({
        "status": "local",
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "path": str(path),
    })
    return result


def redact_model_snapshot(model: dict) -> dict:
    snapshot = {}
    for key, value in model.items():
        normalized = str(key).lower()
        if any(part in normalized for part in SECRET_KEY_PARTS) and key != "api_key_env_names":
            continue
        snapshot[key] = value
    return snapshot


def collect_asset_fingerprints(plan: dict) -> list[dict]:
    candidates = []
    for field in ("confirmed_assets", "references"):
        candidates.extend(item for item in (plan.get(field) or []) if isinstance(item, dict))
    for field in ("avatar_reference", "audio_file", "subtitle_file"):
        item = plan.get(field)
        if isinstance(item, dict):
            candidates.append(item)
    seen = set()
    fingerprints = []
    for item in candidates:
        marker = (str(item.get("id") or ""), str(item.get("role") or ""), asset_value(item))
        if marker in seen:
            continue
        seen.add(marker)
        fingerprints.append(fingerprint_asset(item))
    return sorted(fingerprints, key=lambda item: (item.get("role", ""), item.get("id", ""), item.get("path", "")))


def summarize_request(record: dict) -> dict:
    return {
        "shot_id": str(record.get("shot_id") or ""),
        "model_key": str(record.get("model_key") or ""),
        "payload_digest": canonical_digest(record.get("payload") or {}),
        "asset_trace_digest": canonical_digest(record.get("asset_trace") or {}),
        "dry_run": bool(record.get("dry_run")),
    }


def build_contract(plan: dict, model: dict, request_records: list[dict]) -> dict:
    model_snapshot = redact_model_snapshot(model)
    duration_plan_digest = str(
        plan.get("duration_plan_digest")
        or (plan.get("duration_plan") or {}).get("duration_plan_digest")
        or ""
    )
    components = {
        "version": CONTRACT_VERSION,
        "plan_digest": canonical_digest(plan),
        "duration_plan_digest": duration_plan_digest,
        "model_snapshot": model_snapshot,
        "model_digest": canonical_digest(model_snapshot),
        "asset_fingerprints": collect_asset_fingerprints(plan),
        "dry_run_requests": sorted((summarize_request(item) for item in request_records), key=lambda item: item["shot_id"]),
    }
    return {
        **components,
        "contract_digest": canonical_digest(components),
        "created_at": int(time.time()),
    }


def verify_contract(contract: dict, plan: dict, model: dict, request_records: list[dict]) -> list[str]:
    current = build_contract(plan, model, request_records)
    errors = []
    for field, label in (
        ("plan_digest", "plan digest"),
        ("duration_plan_digest", "duration plan digest"),
        ("model_digest", "model digest"),
        ("asset_fingerprints", "asset fingerprints"),
        ("dry_run_requests", "dry-run requests"),
        ("contract_digest", "contract digest"),
    ):
        if contract.get(field) != current.get(field):
            errors.append(f"Production contract {label} no longer matches the approved project state.")
    return errors


def jobs_path(project_dir: Path) -> Path:
    return project_dir / "jobs.json"


def load_or_create_jobs(
    project_dir: Path,
    plan: dict,
    contract_digest: str,
    max_paid_submissions: int,
) -> dict:
    path = jobs_path(project_dir)
    if max_paid_submissions <= 0:
        raise ScriptError("max_paid_submissions must be greater than zero")
    base_paid_requests = len(plan.get("shots") or [])
    if max_paid_submissions != base_paid_requests:
        raise ScriptError(
            f"max_paid_submissions must equal the {base_paid_requests} base paid request(s); "
            "the normal workflow has no paid repair reserve"
        )
    if path.exists():
        ledger = load_json(path)
        if ledger.get("contract_digest") != contract_digest:
            raise ScriptError("Existing jobs.json belongs to a different production contract; create a new confirmation and job ledger.")
        if int(ledger.get("max_paid_submissions") or 0) != int(max_paid_submissions):
            raise ScriptError("Paid submission budget does not match the existing jobs.json ledger.")
        return ledger

    jobs = {}
    for shot in plan.get("shots") or []:
        shot_id = str(shot.get("id") or "")
        if not shot_id:
            raise ScriptError("Every planned shot needs an id before creating jobs.json")
        jobs[shot_id] = {
            "shot_id": shot_id,
            "state": "planned",
            "idempotency_key": canonical_digest({"contract_digest": contract_digest, "shot_id": shot_id}),
            "submission_attempts": 0,
            "repair_submission_attempts": 0,
            "attempt_history": [],
            "request_id": "",
            "request_file": "",
            "poll_file": "",
            "clip_file": str(shot.get("clip_file") or ""),
            "last_error": "",
            "updated_at": int(time.time()),
        }
    ledger = {
        "version": LEDGER_VERSION,
        "contract_digest": contract_digest,
        "max_paid_submissions": int(max_paid_submissions),
        "paid_submission_attempts": 0,
        "jobs": jobs,
        "updated_at": int(time.time()),
    }
    atomic_write_json(path, ledger)
    return ledger


def save_jobs(project_dir: Path, ledger: dict) -> None:
    ledger["updated_at"] = int(time.time())
    atomic_write_json(jobs_path(project_dir), ledger)


def transition_job(project_dir: Path, ledger: dict, shot_id: str, new_state: str, **updates: Any) -> dict:
    if new_state not in JOB_STATES:
        raise ScriptError(f"Unknown job state: {new_state}")
    job = (ledger.get("jobs") or {}).get(shot_id)
    if not job:
        raise ScriptError(f"Job not found: {shot_id}")
    current = str(job.get("state") or "planned")
    if new_state != current and new_state not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ScriptError(f"Illegal job transition for {shot_id}: {current} -> {new_state}")
    job.update(updates)
    job["state"] = new_state
    job["updated_at"] = int(time.time())
    save_jobs(project_dir, ledger)
    return job


def record_submission_attempt(project_dir: Path, ledger: dict, shot_id: str, reason: str = "initial") -> int:
    job = (ledger.get("jobs") or {}).get(shot_id)
    if not job:
        raise ScriptError(f"Job not found: {shot_id}")
    if job.get("state") != "submitting":
        raise ScriptError(f"Submission attempt can only be recorded from submitting state: {shot_id}")
    if reason != "initial":
        raise ScriptError(
            f"Only the initial paid submission is allowed for {shot_id}; paid retry/regeneration is disabled"
        )
    if int(job.get("submission_attempts") or 0) > 0:
        raise ScriptError(
            f"Refusing a second paid submission for {shot_id}; reuse the existing request id for polling/download recovery"
        )
    attempts = int(ledger.get("paid_submission_attempts") or 0)
    maximum = int(ledger.get("max_paid_submissions") or 0)
    if attempts >= maximum:
        raise ScriptError(f"Paid submission budget exhausted: {attempts}/{maximum}")
    attempts += 1
    ledger["paid_submission_attempts"] = attempts
    job["submission_attempts"] = int(job.get("submission_attempts") or 0) + 1
    job["last_submission_reason"] = reason
    job["updated_at"] = int(time.time())
    save_jobs(project_dir, ledger)
    return attempts
