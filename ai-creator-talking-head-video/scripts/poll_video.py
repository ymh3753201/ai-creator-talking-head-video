#!/usr/bin/env python3
"""Poll a video request and download the finished MP4."""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from _common import ScriptError, download_file, find_api_key, get_model_config, http_json, join_url, load_config, load_json, model_api_key_names, verify_media_file, write_json
from _workflow import sha256_file, transition_job


RETRYABLE_POLL_ERRORS = (
    "network error calling",
    "failed to download",
    "polling timed out",
    "http 408 ",
    "http 425 ",
    "http 429 ",
    "http 500 ",
    "http 502 ",
    "http 503 ",
    "http 504 ",
)


def is_retryable_poll_error(message: str) -> bool:
    normalized = message.lower()
    return any(marker in normalized for marker in RETRYABLE_POLL_ERRORS)


def infer_output_path(request_record: dict, output: str | None) -> Path:
    if output:
        return Path(output).expanduser().resolve()
    request_file = Path(request_record.get("_request_file", "request.json")).resolve()
    shot_id = request_record.get("shot_id", "shot")
    project_dir = request_file.parents[1] if request_file.parent.name == "requests" else request_file.parent
    return project_dir / "clips" / f"{shot_id}.mp4"


def task_body(data: dict) -> dict:
    return data.get("data") if isinstance(data.get("data"), dict) else data


def task_status(data: dict) -> str:
    body = task_body(data)
    return str(body.get("status") or "").upper()


def task_result_url(data: dict) -> str:
    body = task_body(data)
    if body.get("result_url"):
        return str(body["result_url"])
    video = body.get("video") or data.get("video") or {}
    return str(video.get("url") or "")


def task_fail_reason(data: dict) -> str:
    body = task_body(data)
    return str(body.get("fail_reason") or body.get("error") or data.get("message") or data)


def response_value(response: dict, key: str) -> str:
    raw = response.get("raw_response")
    body = task_body(raw) if isinstance(raw, dict) else {}
    return str(response.get(key) or body.get(key) or "")


def bind_poll_record(data: dict, shot_id: str, request_id: str, contract_digest: str) -> dict:
    result = dict(data)
    result["shot_id"] = shot_id
    result["request_id"] = request_id
    result["contract_digest"] = contract_digest
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-file", required=True)
    parser.add_argument("--config")
    parser.add_argument("--model-key")
    parser.add_argument("--output")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mock-video")
    parser.add_argument("--require-audio", action="store_true")
    args = parser.parse_args()

    project_dir = None
    ledger = None
    shot_id = ""
    try:
        request_file = Path(args.request_file).expanduser().resolve()
        request_record = load_json(request_file)
        request_record["_request_file"] = str(request_file)
        project_dir = request_file.parents[1] if request_file.parent.name == "requests" else request_file.parent
        shot_id = str(request_record.get("shot_id") or "")
        jobs_file = project_dir / "jobs.json"
        contract_file = project_dir / "production-contract.json"
        if jobs_file.exists():
            ledger = load_json(jobs_file)
            if not shot_id or shot_id not in (ledger.get("jobs") or {}):
                raise ScriptError(f"Request file does not map to a jobs.json shot: {shot_id or request_file.name}")
            contract = load_json(contract_file)
            if request_record.get("contract_digest") != contract.get("contract_digest") or ledger.get("contract_digest") != contract.get("contract_digest"):
                raise ScriptError("Request, job ledger, and production contract digests do not match")
        response = request_record.get("response") or {}
        request_id = response.get("request_id")
        if not request_id:
            raise ScriptError(f"No request_id in {request_file}")
        output_path = infer_output_path(request_record, args.output)
        result_file = request_file.with_name(request_file.stem.replace("_request", "_poll") + ".json")
        contract_digest = str(request_record.get("contract_digest") or "")

        if args.mock_video:
            if ledger:
                transition_job(project_dir, ledger, shot_id, "polling")
            src = Path(args.mock_video).expanduser().resolve()
            if not src.exists():
                raise ScriptError(f"Mock video not found: {src}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, output_path)
            media = verify_media_file(output_path, require_audio=args.require_audio)
            output_digest = sha256_file(output_path)
            result = bind_poll_record(
                {"status": "done", "mock": True, "video": {"url": str(src), "local_path": str(output_path)}, "media": media, "output_sha256": output_digest},
                shot_id,
                request_id,
                contract_digest,
            )
            write_json(result_file, result)
            if ledger:
                transition_job(project_dir, ledger, shot_id, "downloaded", poll_file=str(result_file), clip_file=str(output_path))
                transition_job(project_dir, ledger, shot_id, "verified", poll_file=str(result_file), clip_file=str(output_path), clip_sha256=output_digest, last_error="")
            print(json.dumps({"ok": True, "output": str(output_path), "output_sha256": output_digest, "result_file": str(result_file), "mock": True, "media": media}, ensure_ascii=False, indent=2))
            return 0

        if args.dry_run:
            result = bind_poll_record(
                {"status": "dry_run", "output_path": str(output_path)},
                shot_id,
                request_id,
                contract_digest,
            )
            write_json(result_file, result)
            print(json.dumps({"ok": True, "dry_run": True, "result_file": str(result_file)}, ensure_ascii=False, indent=2))
            return 0

        model_snapshot = project_dir / "model-snapshot.json"
        if model_snapshot.exists():
            model = load_json(model_snapshot)
            if args.model_key and args.model_key != model.get("key"):
                raise ScriptError("Polling model override does not match the confirmed model snapshot")
            if args.config:
                raise ScriptError("Polling config override is not allowed when a confirmed model snapshot exists")
        else:
            config = load_config(args.config)
            model = get_model_config(config, args.model_key or request_record.get("model_key"))
        if ledger:
            transition_job(project_dir, ledger, shot_id, "polling")
        api_key = find_api_key(required=True, names=model_api_key_names(model))
        poll_path = model.get("poll_path_template", "/video/generations/{request_id}").format(request_id=request_id)
        poll_url = response_value(response, "status_url") or join_url(model["base_url"], poll_path)
        response_url = response_value(response, "response_url")
        if not response_url and model.get("result_path_template"):
            response_url = join_url(model["base_url"], model["result_path_template"].format(request_id=request_id))
        auth_scheme = model.get("auth_scheme") or "Bearer"

        deadline = time.time() + args.timeout
        last_data = {}
        while time.time() < deadline:
            data = http_json("GET", poll_url, api_key, timeout=60, auth_scheme=auth_scheme)
            last_data = data
            status = task_status(data)
            if status in {"SUCCESS", "DONE", "COMPLETED"}:
                result_data = data
                if response_url:
                    result_data = http_json("GET", response_url, api_key, timeout=60, auth_scheme=auth_scheme)
                url = task_result_url(result_data)
                if not url:
                    raise ScriptError(f"Success response missing video URL: {result_data}")
                download_file(url, output_path)
                media = verify_media_file(output_path, require_audio=args.require_audio)
                output_digest = sha256_file(output_path)
                result_data["video"] = {"url": url, "local_path": str(output_path)}
                result_data["media"] = media
                result_data["output_sha256"] = output_digest
                result_data = bind_poll_record(result_data, shot_id, request_id, contract_digest)
                write_json(result_file, result_data)
                if ledger:
                    transition_job(project_dir, ledger, shot_id, "downloaded", poll_file=str(result_file), clip_file=str(output_path))
                    transition_job(project_dir, ledger, shot_id, "verified", poll_file=str(result_file), clip_file=str(output_path), clip_sha256=output_digest, last_error="")
                print(json.dumps({"ok": True, "output": str(output_path), "output_sha256": output_digest, "result_file": str(result_file), "media": media}, ensure_ascii=False, indent=2))
                return 0
            if status in {"FAILURE", "FAILED", "EXPIRED", "CANCELED", "CANCELLED"}:
                write_json(result_file, bind_poll_record(data, shot_id, request_id, contract_digest))
                raise ScriptError(f"Generation {status}: {task_fail_reason(data)}")
            time.sleep(args.interval)
        write_json(
            result_file,
            bind_poll_record(last_data or {"status": "timeout"}, shot_id, request_id, contract_digest),
        )
        raise ScriptError(f"Polling timed out after {args.timeout}s for request {request_id}")
    except ScriptError as exc:
        if project_dir is not None and ledger is not None and shot_id:
            try:
                state = "polling" if is_retryable_poll_error(str(exc)) else "failed"
                transition_job(project_dir, ledger, shot_id, state, last_error=str(exc))
            except ScriptError:
                pass
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
