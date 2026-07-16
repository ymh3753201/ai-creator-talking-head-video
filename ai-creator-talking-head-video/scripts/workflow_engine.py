#!/usr/bin/env python3
"""Operate one talking-head video project through its guarded workflow."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from _common import ScriptError, load_json
from _routing import infer_execution_route


SCRIPT_DIR = Path(__file__).resolve().parent
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


def run_worker(args: list[str]) -> tuple[int, dict]:
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else {"ok": False, "error": result.stderr.strip()}
    except json.JSONDecodeError:
        data = {"ok": False, "error": result.stderr.strip() or result.stdout.strip()}
    return result.returncode, data


def is_pollable_job(job: dict) -> bool:
    state = str(job.get("state") or "")
    if state in {"submitted", "polling"}:
        return bool(job.get("request_id"))
    if state != "failed" or not job.get("request_id"):
        return False
    error = str(job.get("last_error") or "").lower()
    return any(marker in error for marker in RETRYABLE_POLL_ERRORS)


def jobs_requiring_user_action(ledger: dict, confirmation: dict | None = None) -> list[dict]:
    del confirmation
    actions = []
    for shot_id, job in (ledger.get("jobs") or {}).items():
        state = str(job.get("state") or "")
        if state == "submitting":
            actions.append({"shot_id": shot_id, "reason": "blocked_ambiguous_submission_without_safe_idempotency_recovery"})
        elif state == "failed" and job.get("request_id") and not is_pollable_job(job):
            actions.append({"shot_id": shot_id, "reason": "terminal_provider_failure_no_paid_retry"})
        elif state == "failed" and not job.get("request_id") and int(job.get("submission_attempts") or 0) > 0:
            actions.append({"shot_id": shot_id, "reason": "blocked_ambiguous_paid_attempt_without_request_id"})
    return actions


def project_stage(project_dir: Path) -> dict:
    delivery_path = project_dir / "delivery-manifest.json"
    review_path = project_dir / "final-review.json"
    finalize_path = project_dir / "finalize-report.json"
    jobs_path = project_dir / "jobs.json"
    confirmation_path = project_dir / "video-confirmation.json"
    preflight_path = project_dir / "preflight-report.json"
    plan_path = project_dir / "generation-plan.json"
    confirmation = load_json(confirmation_path) if confirmation_path.exists() else {}
    if delivery_path.exists() and load_json(delivery_path).get("status") == "pass":
        stage = "delivered"
    elif finalize_path.exists() and load_json(finalize_path).get("status") == "blocked":
        stage = "blocked"
    elif review_path.exists():
        stage = "reviewed"
    elif jobs_path.exists():
        jobs = load_json(jobs_path)
        states = [item.get("state") for item in (jobs.get("jobs") or {}).values()]
        if jobs_requiring_user_action(jobs, confirmation):
            stage = "blocked_unsafe_to_continue"
        else:
            stage = "ready_to_finalize" if states and all(state == "verified" for state in states) else "generating"
    elif confirmation_path.exists():
        stage = "confirmed"
    elif preflight_path.exists() and load_json(preflight_path).get("ok"):
        preflight = load_json(preflight_path)
        stage = "postproduction_ready" if preflight.get("execution_route") == "postproduction_only" else "preflight_passed"
    elif plan_path.exists():
        stage = "prepared"
    else:
        stage = "uninitialized"
    return {
        "ok": True,
        "project_dir": str(project_dir),
        "stage": stage,
        "files": {
            "plan": str(plan_path) if plan_path.exists() else "",
            "preflight": str(preflight_path) if preflight_path.exists() else "",
            "confirmation": str(confirmation_path) if confirmation_path.exists() else "",
            "jobs": str(jobs_path) if jobs_path.exists() else "",
            "review": str(review_path) if review_path.exists() else "",
            "finalize": str(finalize_path) if finalize_path.exists() else "",
            "delivery": str(delivery_path) if delivery_path.exists() else "",
        },
    }


def poll_submitted(project_dir: Path, args) -> tuple[int, dict]:
    ledger = load_json(project_dir / "jobs.json")
    results = []
    failed = False
    for shot_id, job in (ledger.get("jobs") or {}).items():
        if not is_pollable_job(job):
            continue
        request_file = job.get("request_file") or project_dir / "requests" / f"{shot_id}_request.json"
        command = [sys.executable, str(SCRIPT_DIR / "poll_video.py"), "--request-file", str(request_file), "--timeout", str(args.timeout), "--interval", str(args.interval)]
        if args.require_audio:
            command.append("--require-audio")
        code, data = run_worker(command)
        results.append({"shot_id": shot_id, "code": code, "result": data})
        failed = failed or code != 0
    return (1 if failed else 0), {"ok": not failed, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--config")
    confirm = subparsers.add_parser("confirm")
    confirm.add_argument("--approved-by", required=True)
    confirm.add_argument("--confirmation-intent")
    confirm.add_argument("--confirmed-asset-digest", action="append", default=[])
    confirm.add_argument("--confirmed-duration-plan-digest")
    confirm.add_argument("--max-paid-submissions", type=int)
    confirm.add_argument("--per-shot-repair-limit", type=int, default=0)
    submit = subparsers.add_parser("submit")
    submit.add_argument("--confirmation-file")
    submit.add_argument("--max-paid-submissions", type=int, required=True)
    submit.add_argument("--shot-id")
    submit.add_argument("--retry-failed-shot", help="Disabled legacy option; no second paid POST is allowed.")
    submit.add_argument("--regenerate-shot", help="Disabled legacy option; no second paid POST is allowed.")
    poll = subparsers.add_parser("poll")
    poll.add_argument("--timeout", type=int, default=900)
    poll.add_argument("--interval", type=int, default=5)
    poll.add_argument("--require-audio", action="store_true")
    resume = subparsers.add_parser("resume")
    resume.add_argument("--confirmation-file")
    resume.add_argument("--max-paid-submissions", type=int, required=True)
    resume.add_argument("--timeout", type=int, default=900)
    resume.add_argument("--interval", type=int, default=5)
    resume.add_argument("--require-audio", action="store_true")
    subparsers.add_parser("finalize")
    subparsers.add_parser("status")
    args = parser.parse_args()
    project_dir = Path(args.project_dir).expanduser().resolve()
    plan = project_dir / "generation-plan.json"
    try:
        if args.command == "status":
            data = project_stage(project_dir)
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        if args.command == "preflight":
            command = [sys.executable, str(SCRIPT_DIR / "preflight_project.py"), "--plan", str(plan)]
            if args.config:
                command.extend(["--config", args.config])
            code, data = run_worker(command)
        elif args.command == "confirm":
            preflight_report = project_dir / "preflight-report.json"
            if preflight_report.exists() and load_json(preflight_report).get("execution_route") == "postproduction_only":
                raise ScriptError("postproduction_only projects do not use paid video-generation confirmation or submit")
            command = [sys.executable, str(SCRIPT_DIR / "create_confirmation.py"), "--contract", str(project_dir / "production-contract.json"), "--approved-by", args.approved_by]
            if args.confirmation_intent:
                command.extend(["--confirmation-intent", args.confirmation_intent])
            for digest in args.confirmed_asset_digest:
                command.extend(["--confirmed-asset-digest", digest])
            if args.confirmed_duration_plan_digest:
                command.extend(["--confirmed-duration-plan-digest", args.confirmed_duration_plan_digest])
            if args.max_paid_submissions is not None:
                command.extend(["--max-paid-submissions", str(args.max_paid_submissions)])
            command.extend(["--per-shot-repair-limit", str(args.per_shot_repair_limit)])
            code, data = run_worker(command)
        elif args.command in {"submit", "resume"}:
            if args.command == "submit" and (args.retry_failed_shot or args.regenerate_shot):
                raise ScriptError(
                    "Paid retry and regeneration flags are disabled. "
                    "Use the existing request id for polling/download recovery."
                )
            confirmation = Path(args.confirmation_file).expanduser().resolve() if args.confirmation_file else project_dir / "video-confirmation.json"
            command = [
                sys.executable,
                str(SCRIPT_DIR / "generate_video.py"),
                "--plan", str(plan),
                "--confirmation-file", str(confirmation),
                "--max-paid-submissions", str(args.max_paid_submissions),
            ]
            if args.command == "submit" and args.shot_id:
                command.extend(["--shot-id", args.shot_id])
            code, data = run_worker(command)
            if code == 0 and args.command == "resume":
                submission_result = data
                poll_code, poll_result = poll_submitted(project_dir, args)
                confirmation_data = load_json(confirmation)
                actions = jobs_requiring_user_action(load_json(project_dir / "jobs.json"), confirmation_data)
                code = 1 if actions or poll_code != 0 else 0
                data = {
                    "ok": code == 0,
                    "submission": submission_result,
                    "polling": poll_result,
                    "automatic_repairs": [],
                    "blocked": bool(actions),
                    "blocking_conditions": actions,
                }
        elif args.command == "poll":
            code, data = poll_submitted(project_dir, args)
        elif args.command == "finalize":
            finalizer = "finalize_postproduction.py" if infer_execution_route(load_json(plan)) == "postproduction_only" else "finalize_project.py"
            code, data = run_worker([sys.executable, str(SCRIPT_DIR / finalizer), "--project-dir", str(project_dir)])
        else:
            raise ScriptError(f"Unsupported workflow command: {args.command}")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return code
    except ScriptError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
