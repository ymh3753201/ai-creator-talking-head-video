#!/usr/bin/env python3
"""Workflow-engine tests for ai-creator-talking-head-video."""

from __future__ import annotations

import json
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


sys.dont_write_bytecode = True


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "ai-creator-talking-head-video"
SCRIPTS = ROOT / "ai-creator-talking-head-video" / "scripts"
CONFIG = SKILL / "assets" / "templates" / "model-config.example.json"
sys.path.insert(0, str(SCRIPTS))

from _workflow import (  # noqa: E402
    ScriptError,
    acquire_paid_submission_lock,
    build_contract,
    canonical_digest,
    fingerprint_asset,
    load_or_create_jobs,
    record_submission_attempt,
    release_paid_submission_lock,
    transition_job,
    verify_contract,
)
from _common import http_json  # noqa: E402


def base_plan(asset: Path) -> dict:
    return {
        "duration_plan_digest": "a" * 64,
        "duration_plan": {
            "duration_plan_digest": "a" * 64,
            "delivery_max_seconds": 15,
        },
        "model_key": "grok_talking_head_basic",
        "content_mode": "avatar_talking_head",
        "platform": "douyin",
        "language": "zh",
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "total_duration_seconds": 15,
        "confirmed_assets": [
            {"id": "avatar", "kind": "file", "role": "avatar_reference", "value": str(asset)}
        ],
        "references": [],
        "shots": [
            {
                "id": "shot_01",
                "segment_index": 1,
                "duration_seconds": 15,
                "script_segment": "这是一段长度足够并且可以完成测试的数字人口播脚本内容。",
            }
        ],
    }


def base_model() -> dict:
    return {
        "key": "grok_talking_head_basic",
        "provider": "test-provider",
        "base_url": "https://example.invalid/v1",
        "generation_path": "/video/generations",
        "poll_path_template": "/video/generations/{request_id}",
        "model": "test-model",
        "enabled": True,
        "supports_image_to_video": True,
        "supports_reference_images": False,
        "max_reference_images": 1,
        "max_duration_seconds": 15,
        "min_duration_seconds": 4,
        "supported_aspect_ratios": ["9:16", "16:9"],
        "supported_resolutions": ["480p", "720p"],
        "api_key_env_names": ["TEST_KEY"],
    }


def base_request() -> list[dict]:
    return [
        {
            "shot_id": "shot_01",
            "model_key": "grok_talking_head_basic",
            "payload": {"prompt": "test", "seconds": 15, "resolution": "720p"},
            "asset_trace": {"source_asset_id": "avatar"},
            "dry_run": True,
        }
    ]


def run_command(args: list[str], expect_success: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("AI_CREATOR_TALKING_HEAD_VIDEO") or key in {"YUNWU_API_KEY", "XAI_API_KEY", "FAL_KEY"}:
            env.pop(key, None)
    env["AI_CREATOR_TALKING_HEAD_VIDEO_ENV_FILE"] = str(ROOT / ".nonexistent-workflow-test-env")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(args, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if expect_success and result.returncode != 0:
        raise AssertionError(f"Command failed: {args}\n{result.stdout}\n{result.stderr}")
    if not expect_success and result.returncode == 0:
        raise AssertionError(f"Command unexpectedly passed: {args}\n{result.stdout}\n{result.stderr}")
    return result


READY_SEGMENT_1 = "开场先说明这条消息真正重要的地方不是标题而是它会不会改变普通人的工作方式我们先检查来源再判断使用场景最后给出可以马上执行的行动建议。"
READY_SEGMENT_2 = "第二段继续说明判断标准先确认产品入口和真实效果再记录时间成本失败原因以及团队反馈这样就能避免只看热度并把每次测试变成可复用的检查流程。"


class WorkflowContractTests(unittest.TestCase):
    def test_remote_asset_fingerprint_hashes_content_not_only_the_url(self):
        class FakeResponse:
            def __init__(self, content: bytes):
                self.content = content
                self.offset = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, size=-1):
                if self.offset >= len(self.content):
                    return b""
                end = len(self.content) if size < 0 else min(len(self.content), self.offset + size)
                block = self.content[self.offset:end]
                self.offset = end
                return block

        with patch("urllib.request.urlopen", return_value=FakeResponse(b"version-one")):
            first = fingerprint_asset({"id": "remote", "role": "video_source", "value": "https://cdn.example.com/avatar.png"})
        with patch("urllib.request.urlopen", return_value=FakeResponse(b"version-two")):
            second = fingerprint_asset({"id": "remote", "role": "video_source", "value": "https://cdn.example.com/avatar.png"})

        self.assertEqual(first["status"], "remote_content")
        self.assertNotEqual(first["sha256"], second["sha256"])

    def test_canonical_digest_ignores_mapping_order(self):
        self.assertEqual(canonical_digest({"a": 1, "b": 2}), canonical_digest({"b": 2, "a": 1}))

    def test_contract_changes_when_local_asset_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset = Path(tmp) / "avatar.png"
            asset.write_bytes(b"version-one")
            plan = base_plan(asset)
            first = build_contract(plan, base_model(), base_request())
            asset.write_bytes(b"version-two")
            second = build_contract(plan, base_model(), base_request())
            self.assertNotEqual(first["contract_digest"], second["contract_digest"])
            errors = verify_contract(first, plan, base_model(), base_request())
            self.assertTrue(any("contract digest" in error for error in errors))

    def test_contract_changes_when_plan_model_or_dry_run_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset = Path(tmp) / "avatar.png"
            asset.write_bytes(b"stable")
            plan = base_plan(asset)
            model = base_model()
            requests = base_request()
            contract = build_contract(plan, model, requests)

            changed_plan = json.loads(json.dumps(plan))
            changed_plan["resolution"] = "1080p"
            self.assertTrue(verify_contract(contract, changed_plan, model, requests))

            changed_model = dict(model)
            changed_model["model"] = "other-model"
            self.assertTrue(verify_contract(contract, plan, changed_model, requests))

            changed_requests = json.loads(json.dumps(requests))
            changed_requests[0]["payload"]["seconds"] = 10
            self.assertTrue(verify_contract(contract, plan, model, changed_requests))


class WorkflowLedgerTests(unittest.TestCase):
    def test_http_json_redacts_api_key_from_success_and_payment_error_responses(self):
        credential = "unit-test-secret-value-123456"

        class FakeResponse:
            def __init__(self, payload: bytes):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self.payload

        success = FakeResponse(json.dumps({"echo": credential}).encode("utf-8"))
        with patch("urllib.request.urlopen", return_value=success) as mocked_success:
            data = http_json(
                "GET",
                "https://example.invalid/success",
                credential,
                extra_headers={"Idempotency-Key": "stable-request-key"},
            )
        self.assertEqual(data["echo"], "***")
        self.assertEqual(mocked_success.call_args.args[0].get_header("Idempotency-key"), "stable-request-key")

        error = urllib.error.HTTPError(
            "https://example.invalid/payment",
            402,
            "Payment Required",
            {},
            io.BytesIO(f"insufficient balance; authorization={credential}".encode("utf-8")),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(ScriptError, "HTTP 402") as raised:
                http_json("POST", "https://example.invalid/payment", credential, {"prompt": "test"})
        self.assertNotIn(credential, str(raised.exception))
        self.assertIn("authorization=***", str(raised.exception))

        with patch("urllib.request.urlopen") as mocked:
            with self.assertRaisesRegex(ScriptError, "HTTPS"):
                http_json("GET", "http://api.example.com/private", credential)
        mocked.assert_not_called()

    def test_paid_submission_lock_blocks_a_second_local_submitter(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            first = acquire_paid_submission_lock(project)
            try:
                with self.assertRaisesRegex(ScriptError, "already running"):
                    acquire_paid_submission_lock(project)
            finally:
                release_paid_submission_lock(first)
            second = acquire_paid_submission_lock(project)
            release_paid_submission_lock(second)

    def test_ledger_enforces_transitions_and_zero_repair_paid_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            asset = project / "avatar.png"
            asset.write_bytes(b"avatar")
            plan = base_plan(asset)
            contract = build_contract(plan, base_model(), base_request())
            ledger = load_or_create_jobs(project, plan, contract["contract_digest"], max_paid_submissions=1)
            self.assertEqual(ledger["jobs"]["shot_01"]["state"], "planned")

            with self.assertRaises(ScriptError):
                transition_job(project, ledger, "shot_01", "downloaded")

            transition_job(project, ledger, "shot_01", "submitting")
            record_submission_attempt(project, ledger, "shot_01")
            self.assertEqual(ledger["paid_submission_attempts"], 1)
            self.assertTrue((project / "jobs.json").exists())

            with self.assertRaisesRegex(ScriptError, "second paid submission|initial paid submission"):
                record_submission_attempt(project, ledger, "shot_01", reason="quality_regeneration")

    def test_ledger_rejects_paid_cap_above_base_shot_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            asset = project / "avatar.png"
            asset.write_bytes(b"avatar")
            plan = base_plan(asset)
            contract = build_contract(plan, base_model(), base_request())

            with self.assertRaisesRegex(ScriptError, "must equal.*base paid request"):
                load_or_create_jobs(project, plan, contract["contract_digest"], max_paid_submissions=2)

    def test_ledger_refuses_contract_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            asset = project / "avatar.png"
            asset.write_bytes(b"avatar")
            plan = base_plan(asset)
            load_or_create_jobs(project, plan, "digest-one", max_paid_submissions=1)
            with self.assertRaises(ScriptError):
                load_or_create_jobs(project, plan, "digest-two", max_paid_submissions=1)

    def test_retryable_poll_failure_can_return_to_polling_without_new_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            asset = project / "avatar.png"
            asset.write_bytes(b"avatar")
            plan = base_plan(asset)
            contract = build_contract(plan, base_model(), base_request())
            ledger = load_or_create_jobs(project, plan, contract["contract_digest"], max_paid_submissions=1)
            transition_job(project, ledger, "shot_01", "submitting")
            record_submission_attempt(project, ledger, "shot_01")
            transition_job(project, ledger, "shot_01", "submitted", request_id="existing-request")
            transition_job(project, ledger, "shot_01", "polling")
            transition_job(project, ledger, "shot_01", "failed", last_error="Network error calling status endpoint")

            transition_job(project, ledger, "shot_01", "polling")

            self.assertEqual(ledger["jobs"]["shot_01"]["state"], "polling")
            self.assertEqual(ledger["paid_submission_attempts"], 1)

    def test_workflow_only_retries_transient_failed_poll_jobs(self):
        from workflow_engine import is_pollable_job

        self.assertTrue(is_pollable_job({"state": "submitted", "request_id": "request-1"}))
        self.assertTrue(is_pollable_job({
            "state": "failed",
            "request_id": "request-1",
            "last_error": "Network error calling status endpoint",
        }))
        self.assertTrue(is_pollable_job({
            "state": "failed",
            "request_id": "request-1",
            "last_error": "Polling timed out after 900s",
        }))
        self.assertFalse(is_pollable_job({
            "state": "failed",
            "request_id": "request-1",
            "last_error": "Generation FAILED: policy rejected",
        }))
        self.assertFalse(is_pollable_job({"state": "failed", "request_id": ""}))


class WorkflowPreflightTests(unittest.TestCase):
    def prepare(self, root: Path, *extra: str) -> Path:
        avatar = root / "avatar.png"
        avatar.write_bytes(b"avatar-image")
        command = [
            "python3", str(SCRIPTS / "prepare_project.py"),
            "--name", "workflow-preflight",
            "--project-root", str(root / "projects"),
            "--content-mode", "avatar_talking_head",
            "--platform", "douyin",
            "--duration", "15",
            "--avatar-reference", str(avatar),
            "--script-text", READY_SEGMENT_1,
            "--subtitle-choice", "disabled",
            "--effects-choice", "disabled",
            *extra,
        ]
        result = run_command(command)
        return Path(json.loads(result.stdout)["plan"])

    def test_preflight_blocks_unsupported_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = self.prepare(Path(tmp), "--resolution", "1080p")
            result = run_command([
                "python3", str(SCRIPTS / "preflight_project.py"),
                "--plan", str(plan_path),
                "--config", str(CONFIG),
            ], expect_success=False)
            data = json.loads(result.stdout)
            self.assertFalse(data["ok"])
            self.assertTrue(any("supported_resolutions" in error for error in data["errors"]))

    def test_creative_choices_default_pending_and_block_paid_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"avatar-image")
            result = run_command([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "creative-pending",
                "--project-root", str(root / "projects"),
                "--content-mode", "avatar_talking_head",
                "--duration", "15",
                "--avatar-reference", str(avatar),
                "--script-text", READY_SEGMENT_1,
            ])
            plan_path = Path(json.loads(result.stdout)["plan"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))

            self.assertEqual(plan["creative_choices"]["subtitle"]["choice"], "disabled")
            self.assertEqual(plan["creative_choices"]["effects"]["choice"], "pending")
            self.assertFalse(plan["ready_for_paid_generation"])
            self.assertFalse(any("subtitle choice" in item for item in plan["blocking_reasons"]))
            self.assertTrue(any("effects choice" in item for item in plan["blocking_reasons"]))

    def test_confirmed_disabled_creative_choices_forbid_broll(self):
        from validate_project import validate_plan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            broll = root / "broll.json"
            broll.write_text(json.dumps([{"time": "0-3s", "visual": "cutaway"}]), encoding="utf-8")
            plan_path = self.prepare(
                root,
                "--subtitle-choice", "disabled",
                "--effects-choice", "disabled",
                "--broll-plan", str(broll),
            )
            plan = json.loads(plan_path.read_text(encoding="utf-8"))

            self.assertFalse(plan["subtitle_plan"]["enabled"])
            self.assertFalse(plan["effects_plan"]["enabled"])
            errors, _warnings = validate_plan(plan)
            self.assertTrue(any("B-roll" in item and "disabled" in item for item in errors), errors)

    def test_duration_plan_records_user_confirmed_single_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = self.prepare(
                Path(tmp),
                "--subtitle-choice", "disabled",
                "--effects-choice", "disabled",
            )
            plan = json.loads(plan_path.read_text(encoding="utf-8"))

            self.assertEqual(plan["duration_plan"]["source"], "user_confirmed")
            self.assertEqual(plan["duration_plan"]["confirmed_duration_seconds"], 15)
            self.assertEqual(plan["duration_plan"]["segment_count"], 1)
            self.assertEqual(plan["duration_plan"]["segmentation_reason"], "single_segment_within_model_limit")
            self.assertGreater(plan["duration_plan"]["estimated_script_seconds"], 0)
            self.assertGreater(plan["duration_plan"]["suggested_minimum_duration_seconds"], 0)
            self.assertEqual(plan["duration_plan"]["script_fit_status"], "ok")
            self.assertEqual(len(plan["shots"]), 1)

    def test_duration_omission_marks_model_default_as_unconfirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"avatar-image")
            result = run_command([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "duration-pending",
                "--project-root", str(root / "projects"),
                "--content-mode", "avatar_talking_head",
                "--avatar-reference", str(avatar),
                "--script-text", READY_SEGMENT_1,
                "--subtitle-choice", "disabled",
                "--effects-choice", "disabled",
            ])
            plan = json.loads(Path(json.loads(result.stdout)["plan"]).read_text(encoding="utf-8"))

            self.assertEqual(plan["duration_plan"]["source"], "model_default_unconfirmed")
            self.assertEqual(plan["duration_plan"]["confirmation_status"], "pending")
            self.assertFalse(plan["ready_for_paid_generation"])
            self.assertTrue(any("duration" in item.lower() and "confirmed" in item.lower() for item in plan["blocking_reasons"]))

    def test_explicit_segments_are_preserved_and_preflight_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"avatar-image")
            segments = root / "segments.json"
            segments.write_text(json.dumps({
                "segments": [
                    {"duration_seconds": 15, "script": READY_SEGMENT_1},
                    {"duration_seconds": 15, "script": READY_SEGMENT_2},
                ]
            }, ensure_ascii=False), encoding="utf-8")
            result = run_command([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "explicit-segments",
                "--project-root", str(root / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--duration", "30",
                "--avatar-reference", str(avatar),
                "--segments-file", str(segments),
                "--subtitle-choice", "disabled",
                "--effects-choice", "disabled",
            ])
            plan_path = Path(json.loads(result.stdout)["plan"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual([shot["script_segment"] for shot in plan["shots"]], [READY_SEGMENT_1, READY_SEGMENT_2])
            self.assertEqual(plan["script_segmentation"]["source"], "explicit_segments_file")
            preflight = run_command([
                "python3", str(SCRIPTS / "preflight_project.py"),
                "--plan", str(plan_path),
                "--config", str(CONFIG),
            ])
            report = json.loads(preflight.stdout)
            self.assertTrue(report["ok"])
            self.assertEqual(report["expected_paid_requests"], 2)
            self.assertIn("bind", report["next_action"].lower())
            self.assertNotIn("show the dry-run contract", report["next_action"].lower())
            self.assertTrue(Path(report["contract_file"]).exists())
            dry_record = json.loads((plan_path.parent / "requests" / "dry-run" / "shot_01.json").read_text(encoding="utf-8"))
            self.assertEqual(dry_record["asset_trace"]["source_asset_id"], "avatar_reference")

    def test_stitch_dry_run_refuses_missing_planned_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            clips = project / "clips"
            clips.mkdir()
            (clips / "shot_01.mp4").write_bytes(b"placeholder")
            plan = {
                "shots": [
                    {"id": "shot_01", "clip_file": str(clips / "shot_01.mp4")},
                    {"id": "shot_02", "clip_file": str(clips / "shot_02.mp4")},
                ],
                "stitching_plan": {"target_resolution": "720x1280", "target_fps": 30},
            }
            (project / "generation-plan.json").write_text(json.dumps(plan), encoding="utf-8")
            result = run_command([
                "python3", str(SCRIPTS / "stitch_clips.py"),
                "--project-dir", str(project),
                "--dry-run",
            ], expect_success=False)
            self.assertIn("missing expected clip", result.stdout)

    def test_prepare_records_existing_media_route_and_source_fact_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            existing_video = root / "existing.mp4"
            source_map = root / "source-facts.json"
            avatar.write_bytes(b"avatar")
            existing_video.write_bytes(b"existing-video-placeholder")
            source_map.write_text(json.dumps({"facts": [{
                "fact_id": "FAQ-01",
                "source_locator": "FAQ-01",
                "must_preserve": "七天内提交申请",
                "forbidden_inference": "不得承诺自动退款",
                "verification_status": "verified",
            }]}, ensure_ascii=False), encoding="utf-8")
            result = run_command([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "existing-media-route",
                "--project-root", str(root / "projects"),
                "--content-mode", "hybrid_broll_edit",
                "--duration", "15",
                "--avatar-reference", str(avatar),
                "--script-text", READY_SEGMENT_1,
                "--existing-video-file", str(existing_video),
                "--desired-output", "existing_video_enhancement",
                "--speech-source", "existing_video_audio",
                "--timing-authority", "existing_video",
                "--source-fact-map", str(source_map),
            ])
            plan = json.loads(Path(json.loads(result.stdout)["plan"]).read_text(encoding="utf-8"))
            self.assertEqual(plan["intake_route"]["desired_output"], "existing_video_enhancement")
            self.assertEqual(plan["intake_route"]["timing_authority"], "existing_video")
            self.assertEqual(plan["existing_video_file"]["role"], "existing_video")
            self.assertEqual(plan["source_fact_map"][0]["fact_id"], "FAQ-01")

    def test_preflight_blocks_unverified_business_source_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_map = root / "source-facts.json"
            source_map.write_text(json.dumps({"facts": [{
                "fact_id": "FAQ-01",
                "source_locator": "FAQ-01",
                "must_preserve": "七天内提交申请",
                "forbidden_inference": "不得承诺自动退款",
                "verification_status": "missing_source",
            }]}, ensure_ascii=False), encoding="utf-8")
            plan_path = self.prepare(
                root,
                "--source-fact-map", str(source_map),
                "--business-scenario", "customer service FAQ",
                "--user-intent", "explain after-sales process",
                "--success-metric", "fewer repeated support questions",
                "--risk-boundary", "do not invent policy terms",
            )
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertFalse(plan["ready_for_paid_generation"])
            self.assertTrue(any("FAQ-01" in item for item in plan["blocking_reasons"]))

            result = run_command([
                "python3", str(SCRIPTS / "preflight_project.py"),
                "--plan", str(plan_path),
                "--config", str(CONFIG),
            ], expect_success=False)

            errors = json.loads(result.stdout)["errors"]
            self.assertTrue(any("missing_source" in item and "FAQ-01" in item for item in errors), errors)

    def test_factual_business_project_requires_a_nonempty_source_fact_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = self.prepare(
                root,
                "--business-scenario", "customer service FAQ",
                "--user-intent", "explain after-sales process",
                "--success-metric", "fewer repeated questions",
                "--risk-boundary", "do not invent policy terms",
                "--require-source-fact-map",
            )
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertTrue(plan["source_fact_map_required"])
            self.assertFalse(plan["ready_for_paid_generation"])
            self.assertTrue(any("source_fact_map" in item for item in plan["blocking_reasons"]))

    def test_existing_video_enhancement_never_enters_paid_video_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "existing.mp4"
            existing.write_bytes(b"existing-video-placeholder")
            plan_path = self.prepare(
                root,
                "--content-mode", "hybrid_broll_edit",
                "--existing-video-file", str(existing),
                "--desired-output", "existing_video_enhancement",
                "--speech-source", "existing_video_audio",
                "--timing-authority", "existing_video",
            )
            prepared_plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(prepared_plan["execution_route"], "postproduction_only")
            self.assertTrue(prepared_plan["postproduction_plan"]["enabled"])
            self.assertEqual(prepared_plan["postproduction_plan"]["paid_video_generation_requests"], 0)
            self.assertTrue(prepared_plan["postproduction_plan"]["candidate_output"].endswith("final.postproduced.mp4"))

            result = run_command([
                "python3", str(SCRIPTS / "preflight_project.py"),
                "--plan", str(plan_path),
                "--config", str(CONFIG),
            ])

            data = json.loads(result.stdout)
            self.assertTrue(data["ok"])
            self.assertEqual(data["expected_paid_requests"], 0)
            self.assertFalse(data["paid_generation_allowed"])
            self.assertEqual(data["contract_file"], "")
            self.assertIn("editing", data["next_action"].lower())
            status = run_command([
                "python3", str(SCRIPTS / "workflow_engine.py"),
                "--project-dir", str(plan_path.parent),
                "status",
            ])
            self.assertEqual(json.loads(status.stdout)["stage"], "postproduction_ready")
            confirmation = run_command([
                "python3", str(SCRIPTS / "workflow_engine.py"),
                "--project-dir", str(plan_path.parent),
                "confirm", "--approved-by", "should-not-confirm",
            ], expect_success=False)
            self.assertIn("do not use paid", confirmation.stdout)

    def test_external_audio_timing_blocks_model_without_audio_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "voice.wav"
            audio.write_bytes(b"audio-placeholder")
            plan_path = self.prepare(
                root,
                "--audio-file", str(audio),
                "--speech-source", "external_audio",
                "--timing-authority", "external_audio",
            )

            result = run_command([
                "python3", str(SCRIPTS / "preflight_project.py"),
                "--plan", str(plan_path),
                "--config", str(CONFIG),
            ], expect_success=False)

            errors = json.loads(result.stdout)["errors"]
            self.assertTrue(any("supports_audio_input" in item for item in errors), errors)

    def test_external_subtitle_timing_blocks_model_without_subtitle_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subtitle = root / "provided.srt"
            subtitle.write_text("1\n00:00:00,000 --> 00:00:02,000\n测试字幕\n", encoding="utf-8")
            plan_path = self.prepare(
                root,
                "--subtitle-file", str(subtitle),
                "--timing-authority", "external_subtitle",
            )

            result = run_command([
                "python3", str(SCRIPTS / "preflight_project.py"),
                "--plan", str(plan_path),
                "--config", str(CONFIG),
            ], expect_success=False)

            errors = json.loads(result.stdout)["errors"]
            self.assertTrue(any("Provider no-text policy" in item for item in errors), errors)

    def test_localization_contract_is_scoped_to_one_confirmed_locale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glossary = root / "glossary.json"
            glossary.write_text(json.dumps({"AI": "人工智能"}, ensure_ascii=False), encoding="utf-8")
            plan_path = self.prepare(
                root,
                "--source-language", "zh-CN",
                "--target-language", "zh-TW",
                "--target-locale", "zh-TW",
                "--glossary-file", str(glossary),
                "--translation-review-status", "verified",
                "--business-scenario", "multilingual localization",
                "--user-intent", "localize training content",
                "--success-metric", "one approved localized version",
                "--risk-boundary", "preserve approved terminology",
            )

            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            contract = plan["localization_contract"]
            self.assertTrue(contract["enabled"])
            self.assertEqual(contract["source_language"], "zh-CN")
            self.assertEqual(contract["target_language"], "zh-TW")
            self.assertEqual(contract["target_locale"], "zh-TW")
            self.assertEqual(contract["translation_review_status"], "verified")
            self.assertTrue(contract["localized_script_sha256"])
            self.assertTrue(contract["glossary_sha256"])
            self.assertTrue(contract["one_project_per_locale"])
            self.assertTrue(contract["glossary_file"]["value"])

    def test_non_latin_script_pacing_does_not_fall_back_to_the_minimum(self):
        from prepare_project import estimate_spoken_seconds

        samples = {
            "ja": "今日は新しい人工知能ツールを安全に評価する方法を説明します。まず情報源を確認し、次に費用とリスクを比較します。",
            "ko": "오늘은 새로운 인공지능 도구를 안전하게 평가하는 방법을 설명합니다 먼저 출처를 확인하고 비용과 위험을 비교합니다",
            "ar": "سنشرح اليوم طريقة تقييم أدوات الذكاء الاصطناعي الجديدة بأمان ثم نراجع المصدر والتكلفة والمخاطر قبل اتخاذ القرار",
            "th": "วันนี้เราจะอธิบายวิธีประเมินเครื่องมือปัญญาประดิษฐ์ใหม่อย่างปลอดภัยโดยตรวจสอบแหล่งที่มาต้นทุนและความเสี่ยง",
            "ru": "Сегодня мы объясним как безопасно оценивать новые инструменты искусственного интеллекта и проверять источники стоимость и риски",
        }
        for language, script in samples.items():
            with self.subTest(language=language):
                self.assertGreater(estimate_spoken_seconds(script, language), 4.0)

    def test_existing_video_route_uses_actual_media_duration_when_not_supplied(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                "-t", "6.2", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(source),
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            result = run_command([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "existing-duration",
                "--project-root", str(root / "projects"),
                "--content-mode", "hybrid_broll_edit",
                "--existing-video-file", str(source),
                "--desired-output", "existing_video_enhancement",
                "--speech-source", "existing_video_audio",
                "--timing-authority", "existing_video",
                "--subtitle-strategy", "no subtitles",
            ])
            plan = json.loads(Path(json.loads(result.stdout)["plan"]).read_text(encoding="utf-8"))
            self.assertEqual(plan["total_duration_seconds"], 6)

    def test_subtitle_plan_is_fixed_disabled_for_every_ratio(self):
        from prepare_project import build_subtitle_plan

        portrait = build_subtitle_plan(Path("/tmp/portrait"), None, "bottom captions", "zh", "9:16")
        landscape = build_subtitle_plan(Path("/tmp/landscape"), None, "lower third", "en", "16:9")

        for plan in (portrait, landscape):
            self.assertFalse(plan["enabled"])
            self.assertEqual(plan["choice"], "disabled")
            self.assertIsNone(plan["safe_zone"])

    def test_unconfirmed_localization_translation_blocks_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = self.prepare(
                root,
                "--source-language", "zh-CN",
                "--target-language", "zh-TW",
                "--target-locale", "zh-TW",
                "--translation-review-status", "needs_user_confirmation",
                "--business-scenario", "multilingual localization",
                "--user-intent", "localize training content",
                "--success-metric", "one approved localized version",
                "--risk-boundary", "preserve approved terminology",
            )

            result = run_command([
                "python3", str(SCRIPTS / "preflight_project.py"),
                "--plan", str(plan_path),
                "--config", str(CONFIG),
            ], expect_success=False)

            errors = json.loads(result.stdout)["errors"]
            self.assertTrue(any("translation_review_status" in item for item in errors), errors)

    def test_localization_language_mismatch_blocks_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = self.prepare(
                root,
                "--language", "zh",
                "--source-language", "zh-CN",
                "--target-language", "en",
                "--target-locale", "en-US",
                "--translation-review-status", "verified",
            )

            result = run_command([
                "python3", str(SCRIPTS / "preflight_project.py"),
                "--plan", str(plan_path),
                "--config", str(CONFIG),
            ], expect_success=False)

            self.assertTrue(any("plan language" in item for item in json.loads(result.stdout)["errors"]))


class WorkflowPostproductionTests(unittest.TestCase):
    def test_review_actions_never_recommend_a_second_paid_generation(self):
        from review_render import choose_action

        cases = {
            "script boundary is not stitch safe": "rebalance_script_or_block_source_boundary",
            "tail silence detected and script pacing is short": "trim_verified_idle_tail_or_block_source",
            "freeze detected in final output": "cut_locally_or_block_frozen_segment",
        }
        for issue, expected in cases.items():
            with self.subTest(issue=issue):
                action = choose_action([issue])
                self.assertEqual(action, expected)
                self.assertNotIn("regenerat", action.lower())

    def build_complete_speech_review(self, root: Path, status: str = "pass") -> dict:
        overview = root / "overview.jpg"
        boundary_before = root / "boundary-before.jpg"
        boundary_after = root / "boundary-after.jpg"
        transcript = root / "transcript.txt"
        for path in (overview, boundary_before, boundary_after):
            path.write_bytes(path.name.encode("utf-8"))
        transcript.write_text("完整口播识别记录", encoding="utf-8")
        return {
            "status": status,
            "identity_consistent": True,
            "outfit_consistent": True,
            "scene_consistent": True,
            "framing_consistent": True,
            "lip_sync_acceptable": True,
            "mouth_visible": True,
            "no_unapproved_visual_insert": True,
            "no_generated_text": True,
            "spoken_content_complete": True,
            "reviewed_frames": [str(overview)],
            "reviewed_boundary_frames": [str(boundary_before), str(boundary_after)],
            "speech_evidence": {
                "status": status,
                "method": "two_asr_runs_plus_complete_listen_review",
                "transcript": str(transcript),
                "segments_reviewed": ["shot_01", "shot_02"],
                "pronunciation_acceptable": True,
                "voice_consistent": True,
                "volume_consistent": True,
                "unresolved_discrepancies": [],
                "speech_fidelity_mode": "critical_facts_exact",
                "critical_terms_preserved": True,
                "core_facts_preserved": True,
                "meaning_preserved": True,
                "intelligibility_acceptable": True,
                "asr_consensus": "uncertain",
                "minor_discrepancies": [],
                "material_discrepancies": [],
            },
        }

    def test_postproduction_rejects_unapproved_broll_and_caption_masks(self):
        from finalize_postproduction import validate_postproduction_operations

        plan = {
            "effects_plan": {"enabled": False},
            "subtitle_plan": {"enabled": True, "background_policy": "none"},
        }
        manifest = {
            "all_operations_user_approved": False,
            "caption_mask_applied": True,
            "operations": [
                {"type": "broll", "status": "applied"},
                {"type": "caption_mask", "status": "applied"},
            ],
        }

        errors = validate_postproduction_operations(plan, manifest)

        self.assertTrue(any("user approved" in item for item in errors), errors)
        self.assertTrue(any("caption mask" in item for item in errors), errors)
        self.assertTrue(any("effects are disabled" in item for item in errors), errors)

    def test_one_shot_without_subtitles_or_effects_uses_original_clip(self):
        from finalize_project import should_use_original_single_clip

        plan = {
            "subtitle_plan": {"enabled": False},
            "effects_plan": {"enabled": False},
            "stitching_plan": {"required": False, "auto_trim_tail_silence": False},
        }

        self.assertTrue(should_use_original_single_clip(plan, [Path("/tmp/shot_01.mp4")]))
        self.assertFalse(should_use_original_single_clip(plan, [Path("/tmp/shot_01.mp4"), Path("/tmp/shot_02.mp4")]))
        self.assertFalse(should_use_original_single_clip({**plan, "subtitle_plan": {"enabled": True}}, [Path("/tmp/shot_01.mp4")]))

    def test_visual_review_requires_no_unapproved_visuals_and_no_generated_text(self):
        from finalize_project import visual_review_errors

        review = {
            "status": "pass",
            "identity_consistent": True,
            "outfit_consistent": True,
            "scene_consistent": True,
            "framing_consistent": True,
            "lip_sync_acceptable": True,
            "mouth_visible": True,
            "subtitle_safe": True,
            "subtitle_readable": True,
            "subtitle_matches_speech": True,
            "spoken_content_complete": True,
        }

        errors = visual_review_errors(review, subtitles_enabled=True)

        self.assertTrue(any("no_unapproved_visual_insert" in item for item in errors), errors)
        self.assertTrue(any("no_generated_text" in item for item in errors), errors)
        self.assertTrue(any("subtitle_background_absent" in item for item in errors), errors)

    def test_no_subtitle_review_does_not_require_subtitle_background_field(self):
        from finalize_project import visual_review_errors

        review = {
            "status": "pass",
            "identity_consistent": True,
            "outfit_consistent": True,
            "scene_consistent": True,
            "framing_consistent": True,
            "lip_sync_acceptable": True,
            "mouth_visible": True,
            "spoken_content_complete": True,
            "no_unapproved_visual_insert": True,
            "no_generated_text": True,
        }

        errors = visual_review_errors(review, subtitles_enabled=False)

        self.assertFalse(any("subtitle_background_absent" in item for item in errors), errors)
        self.assertFalse(any("subtitle_safe" in item for item in errors), errors)

    def test_minor_nonsemantic_pronunciation_difference_is_pass_with_notes(self):
        from finalize_project import visual_review_errors

        with tempfile.TemporaryDirectory() as tmp:
            review = self.build_complete_speech_review(Path(tmp), status="pass_with_notes")
            review["speech_evidence"]["minor_discrepancies"] = [{
                "segment": "shot_02",
                "expected": "更值得关注的是 Ultra",
                "observed": "开头过渡短语吐字含混，但 Ultra 清楚",
                "severity": "minor",
                "category": "noncritical_transition_pronunciation",
                "affects_core_fact": False,
                "affects_meaning": False,
            }]

            errors = visual_review_errors(
                review,
                expected_boundaries=1,
                expected_segments=2,
                subtitles_enabled=False,
            )

            self.assertEqual(errors, [])

    def test_verbatim_mode_blocks_even_minor_pronunciation_difference(self):
        from finalize_project import visual_review_errors

        with tempfile.TemporaryDirectory() as tmp:
            review = self.build_complete_speech_review(Path(tmp), status="pass_with_notes")
            review["speech_evidence"]["speech_fidelity_mode"] = "verbatim_required"
            review["speech_evidence"]["minor_discrepancies"] = [{
                "segment": "shot_01",
                "expected": "逐字一致",
                "observed": "轻微改写",
                "severity": "minor",
                "category": "wording_difference",
                "affects_core_fact": False,
                "affects_meaning": False,
            }]

            errors = visual_review_errors(review, expected_segments=2, subtitles_enabled=False)

            self.assertTrue(any("verbatim_required" in item for item in errors), errors)

    def test_material_or_core_fact_speech_difference_still_blocks_delivery(self):
        from finalize_project import visual_review_errors

        with tempfile.TemporaryDirectory() as tmp:
            review = self.build_complete_speech_review(Path(tmp), status="pass")
            review["speech_evidence"]["material_discrepancies"] = [{
                "segment": "shot_02",
                "expected": "价格 199 元",
                "observed": "价格 299 元",
                "severity": "material",
                "category": "critical_number_changed",
                "affects_core_fact": True,
                "affects_meaning": True,
            }]

            errors = visual_review_errors(review, expected_segments=2, subtitles_enabled=False)

            self.assertTrue(any("material speech discrepancies" in item for item in errors), errors)

    def test_single_and_multi_segment_prompts_require_clean_model_output(self):
        from prepare_project import build_segment_prompt

        visual_bible = {"broll_rule": "Do not insert B-roll or cutaway images."}
        pacing = {
            "minimum_recommended_spoken_seconds": 13.5,
            "estimated_spoken_seconds": 14.0,
        }
        single = build_segment_prompt(
            "请自然口播这段内容。", "请自然口播这段内容。", "请自然口播这段内容。",
            1, 1, 15, "complete message", visual_bible, pacing,
        )
        multi = build_segment_prompt(
            "请自然口播完整内容。", "完整内容", READY_SEGMENT_1,
            1, 2, 15, "opening", visual_bible, pacing,
        )

        for prompt in (single, multi):
            self.assertIn("No on-screen text", prompt)
            self.assertIn("subtitles", prompt)
            self.assertIn("logos", prompt)
            self.assertIn("watermarks", prompt)
            self.assertIn("No B-roll", prompt)

    def test_confirmed_subtitle_render_is_detached_from_provider_plan(self):
        from prepare_project import build_subtitle_plan

        plan = build_subtitle_plan(
            Path("/tmp/subtitle-clean"),
            None,
            "white captions with outline",
            "zh",
            "9:16",
            choice="enabled",
            request_source="user_plan_confirmation",
            platform="douyin",
        )

        self.assertTrue(plan["enabled"])
        self.assertEqual(plan["background_policy"], "transparent_outline_only")
        self.assertEqual(plan["provider_policy"], "never_send")
        self.assertEqual(plan["render_policy"], "postproduction_burn_only")

    def test_auto_tail_trim_default_respects_external_timing_assets(self):
        from prepare_project import default_auto_trim_tail_silence

        self.assertTrue(default_auto_trim_tail_silence(
            content_mode="avatar_talking_head",
            speech_source="generated_dialogue",
            timing_authority="script_and_target_duration",
            has_audio=False,
            has_subtitle=False,
            has_existing_video=False,
        ))
        self.assertFalse(default_auto_trim_tail_silence(
            content_mode="avatar_talking_head",
            speech_source="generated_dialogue",
            timing_authority="external_subtitle",
            has_audio=False,
            has_subtitle=True,
            has_existing_video=False,
        ))

    def test_stitch_plan_disables_auto_tail_trim_for_external_audio_route(self):
        from prepare_project import build_stitching_plan

        plan = build_stitching_plan(
            Path("/tmp/project"),
            [{"clip_file": "/tmp/project/clips/shot_01.mp4"}],
            "16:9",
            "720p",
            auto_trim_tail_silence=False,
        )

        self.assertFalse(plan["auto_trim_tail_silence"])

    def test_punctuation_free_chinese_subtitles_are_chunked_for_readability(self):
        from generate_subtitles import split_caption_units

        text = "开场先说明今天的问题不是工具少而是视频主题没有帮观众快速判断价值我们会用一个标准同时看来源场景成本变化和风险边界"
        captions = split_caption_units(text, max_chars=14)

        self.assertGreaterEqual(len(captions), 4)
        self.assertTrue(all(len(re.sub(r"\s+", "", item)) <= 14 for item in captions))
        self.assertEqual("".join(captions), text)

    def test_chinese_caption_chunks_preserve_common_semantic_phrases(self):
        from generate_subtitles import split_caption_units

        text = "开场先说明今天的问题不是工具少而是视频主题没有帮观众快速判断价值我们会用一个标准同时看来源场景成本变化和风险边界帮助观众继续看并明确下一步行动路径最后形成可复用检查清单。"
        captions = split_caption_units(text, max_chars=22)

        for phrase in ("没有帮", "来源", "检查清单"):
            self.assertTrue(any(phrase in caption for caption in captions), (phrase, captions))

    def test_tail_trim_keeps_a_short_natural_pause(self):
        from stitch_clips import choose_tail_trim

        decision = choose_tail_trim(
            duration=15.042,
            silences=[{"start": 13.346, "end": 15.019, "duration": 1.673}],
            min_tail_silence=1.0,
            tail_padding=0.25,
            max_trim_seconds=2.5,
        )

        self.assertTrue(decision["applied"])
        self.assertAlmostEqual(decision["trim_end_seconds"], 13.596, places=3)
        self.assertAlmostEqual(decision["trimmed_seconds"], 1.446, places=3)

    def test_segment_pacing_reserves_head_and_tail_speech_safety(self):
        from prepare_project import build_script_pacing, build_segment_prompt, pacing_status

        self.assertEqual(pacing_status(15.8, 15), "too_long")
        self.assertEqual(pacing_status(13.0, 15), "short_but_usable")
        pacing = build_script_pacing("测试脚本", 15, "zh")
        self.assertEqual(pacing["maximum_recommended_spoken_seconds"], 14.2)
        self.assertGreaterEqual(pacing["head_padding_seconds"], 0.3)
        self.assertGreaterEqual(pacing["tail_padding_seconds"], 0.3)
        self.assertIn("shorter complete segment is usable", pacing["target_rule"])
        single_prompt = build_segment_prompt(
            "Create a talking-head video.",
            "测试脚本",
            "测试脚本",
            1,
            1,
            15,
            "single segment",
            {"broll_rule": ""},
            pacing,
        )
        self.assertIn("neutral pause before and after speech", single_prompt)
        self.assertIn("complete first/final words", single_prompt)

    def test_15_second_chinese_segment_prompt_fits_configured_character_limit(self):
        from prepare_project import build_script_pacing, build_segment_prompt

        segment = (
            "AI圈大新闻：OpenAI在7月9日发布GPT-5.6，推出Sol、Terra、Luna三档。"
            "Sol负责复杂任务，Terra平衡能力与成本，Luna主打速度与价格。"
        )
        prompt = build_segment_prompt(
            "Female AI blogger speaks Mandarin to camera. Stable identity, blue blazer, bright studio. "
            "Small gestures, clear mouth. No text, cuts, logos, music, overlays or B-roll.",
            segment,
            segment,
            1,
            2,
            15,
            "opening hook",
            {"broll_rule": "Do not insert B-roll, title cards, cutaway images, overlays, or other visual effects. Preserve the complete model-generated video."},
            build_script_pacing(segment, 15, "zh"),
        )

        self.assertLessEqual(len(prompt), 900)

    def test_stitch_preserves_incoming_clip_onset_without_per_clip_fade(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")

        def mean_volume(path: Path, start: float, duration: float = 0.03) -> float:
            result = subprocess.run([
                "ffmpeg", "-hide_banner", "-ss", f"{start:.6f}", "-t", f"{duration:.3f}",
                "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-",
            ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(result.returncode, 0, result.stderr)
            match = re.search(r"mean_volume:\s*([-\d.]+) dB", result.stderr)
            self.assertIsNotNone(match, result.stderr)
            return float(match.group(1))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            clips = project / "clips"
            clips.mkdir()
            first = clips / "shot_01.mp4"
            second = clips / "shot_02.mp4"
            final = project / "final.mp4"

            sources = [
                (first, "anullsrc=r=48000:cl=stereo"),
                (second, "sine=frequency=440:sample_rate=48000:duration=1"),
            ]
            for path, audio_source in sources:
                result = subprocess.run([
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", "color=c=blue:s=160x284:r=24:d=1",
                    "-f", "lavfi", "-i", audio_source,
                    "-t", "1", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ar", "48000", "-ac", "2", str(path),
                ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(result.returncode, 0, result.stderr)

            stitched = run_command([
                "python3", str(SCRIPTS / "stitch_clips.py"),
                "--project-dir", str(project),
                "--clips", str(first), str(second),
                "--output", str(final),
                "--target-resolution", "160x284",
                "--target-fps", "24",
                "--preset", "ultrafast",
                "--require-audio",
            ])
            report = json.loads(stitched.stdout)
            boundary = float(report["normalized_media"][0]["duration_seconds"])
            source_head = mean_volume(second, 0.0)
            final_head = mean_volume(final, boundary)

            self.assertLessEqual(source_head - final_head, 1.5, (source_head, final_head, report))
            self.assertEqual(report["audio_boundary_policy"]["strategy"], "pcm_intermediates_single_final_aac_encode")
            self.assertFalse(report["audio_boundary_policy"]["per_clip_fades_applied"])

            from review_render import boundary_head_audio_reviews
            onset_reviews = boundary_head_audio_reviews(
                final,
                [first, second],
                [boundary],
                window=0.1,
                active_threshold_db=-40.0,
                max_attenuation_db=3.0,
            )
            self.assertEqual(len(onset_reviews), 1)
            self.assertTrue(onset_reviews[0]["source_head_active"])
            self.assertTrue(onset_reviews[0]["incoming_onset_preserved"], onset_reviews)

    def test_quiet_guard_at_exact_boundary_is_not_reported_as_cut_off_speech(self):
        from review_render import classify_boundary_activity

        context = {"mean_volume_db": -15.3, "max_volume_db": -2.9}
        guard = {"mean_volume_db": -64.6, "max_volume_db": -51.1}

        self.assertFalse(classify_boundary_activity(context, guard, active_threshold_db=-40.0))

    def test_loud_guard_at_exact_boundary_is_reported_as_cut_off_risk(self):
        from review_render import classify_boundary_activity

        context = {"mean_volume_db": -15.3, "max_volume_db": -2.9}
        guard = {"mean_volume_db": -18.0, "max_volume_db": -3.0}

        self.assertTrue(classify_boundary_activity(context, guard, active_threshold_db=-40.0))

    def test_duration_tolerance_scales_for_longform_post_editing(self):
        from review_render import effective_duration_tolerance, stitch_boundary_seconds

        self.assertEqual(effective_duration_tolerance(15, 1.0, 0.05), 1.0)
        self.assertEqual(effective_duration_tolerance(45, 1.0, 0.05), 2.25)
        report = {"data": {"normalized_media": [
            {"duration_seconds": 15.0},
            {"duration_seconds": 13.6},
            {"duration_seconds": 15.0},
        ]}}
        self.assertEqual(stitch_boundary_seconds(report, {}), [15.0, 28.6])

    def test_visual_delivery_review_requires_readability_and_spoken_completeness(self):
        from finalize_project import visual_review_errors

        review = {
            "status": "pass",
            "identity_consistent": True,
            "outfit_consistent": True,
            "scene_consistent": True,
            "framing_consistent": True,
            "lip_sync_acceptable": True,
            "mouth_visible": True,
            "subtitle_safe": True,
            "reviewed_frames": ["frame.jpg"],
        }

        errors = visual_review_errors(review)

        self.assertTrue(any("subtitle_readable" in item for item in errors))
        self.assertTrue(any("spoken_content_complete" in item for item in errors))

    def test_multi_segment_visual_review_requires_existing_boundary_and_speech_evidence(self):
        from finalize_project import visual_review_errors

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overview = root / "overview.jpg"
            boundary_before = root / "boundary-before.jpg"
            transcript = root / "transcript.txt"
            overview.write_bytes(b"overview")
            boundary_before.write_bytes(b"before")
            transcript.write_text("complete transcript", encoding="utf-8")
            review = {
                "status": "pass",
                "identity_consistent": True,
                "outfit_consistent": True,
                "scene_consistent": True,
                "framing_consistent": True,
                "lip_sync_acceptable": True,
                "mouth_visible": True,
                "subtitle_safe": True,
                "subtitle_readable": True,
                "subtitle_matches_speech": True,
                "subtitle_background_absent": True,
                "no_unapproved_visual_insert": True,
                "no_generated_text": True,
                "spoken_content_complete": True,
                "reviewed_frames": [str(overview)],
                "reviewed_boundary_frames": [str(boundary_before)],
                "speech_evidence": {
                    "status": "pass",
                    "method": "human_review",
                    "transcript": str(transcript),
                    "segments_reviewed": ["shot_01", "shot_02"],
                    "pronunciation_acceptable": True,
                    "voice_consistent": True,
                    "volume_consistent": True,
                    "unresolved_discrepancies": [],
                },
            }

            errors = visual_review_errors(review, expected_boundaries=1, expected_segments=2)

            self.assertTrue(any("boundary frame" in item for item in errors), errors)


class WorkflowConfirmationTests(unittest.TestCase):
    def image_digest_args(self, contract_path: Path) -> list[str]:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        digests = [
            item["sha256"] for item in contract["asset_fingerprints"]
            if item.get("role") in {"avatar_reference", "video_source", "first_frame", "segment_source"}
        ]
        self.assertTrue(digests)
        return [
            "--confirmation-intent", "confirm_images_and_start",
            *[value for digest in digests for value in ("--confirmed-asset-digest", digest)],
        ]

    def image_confirmation_args(self, contract_path: Path) -> list[str]:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        duration_plan_digest = str(contract.get("duration_plan_digest") or "")
        self.assertRegex(duration_plan_digest, r"^[0-9a-f]{64}$")
        return [
            *self.image_digest_args(contract_path),
            "--confirmed-duration-plan-digest", duration_plan_digest,
        ]

    def prepare_and_preflight(self, root: Path) -> tuple[Path, Path]:
        avatar = root / "avatar.png"
        avatar.write_bytes(b"confirmed-avatar")
        prepared = run_command([
            "python3", str(SCRIPTS / "prepare_project.py"),
            "--name", "contract-confirmation",
            "--project-root", str(root / "projects"),
            "--content-mode", "avatar_talking_head",
            "--platform", "douyin",
            "--duration", "15",
            "--avatar-reference", str(avatar),
            "--script-text", READY_SEGMENT_1,
            "--subtitle-choice", "disabled",
            "--effects-choice", "disabled",
        ])
        plan_path = Path(json.loads(prepared.stdout)["plan"])
        preflight = run_command([
            "python3", str(SCRIPTS / "preflight_project.py"),
            "--plan", str(plan_path),
            "--config", str(CONFIG),
        ])
        contract_path = Path(json.loads(preflight.stdout)["contract_file"])
        return plan_path, contract_path

    def test_workflow_confirm_requires_second_confirmation_and_exact_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, contract_path = self.prepare_and_preflight(root)
            plan_only = run_command([
                "python3", str(SCRIPTS / "workflow_engine.py"),
                "--project-dir", str(plan_path.parent),
                "confirm", "--approved-by", "plan-only-user",
            ], expect_success=False)
            self.assertIn("confirm_images_and_start", plan_only.stdout)

            confirmed = run_command([
                "python3", str(SCRIPTS / "workflow_engine.py"),
                "--project-dir", str(plan_path.parent),
                "confirm", "--approved-by", "image-confirmed-user",
                *self.image_confirmation_args(contract_path),
            ])
            data = json.loads(confirmed.stdout)
            self.assertTrue(data["ok"])
            self.assertEqual(data["confirmation_stage"], "production_authorized")
            self.assertTrue(Path(data["confirmation_file"]).exists())

    def test_confirmation_requires_exact_first_stage_duration_plan_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, contract_path = self.prepare_and_preflight(root)

            missing = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_digest_args(contract_path),
            ], expect_success=False)
            self.assertIn("duration plan digest", missing.stdout.lower())

            mismatch = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_digest_args(contract_path),
                "--confirmed-duration-plan-digest", "f" * 64,
            ], expect_success=False)
            self.assertIn("does not match", mismatch.stdout.lower())
            self.assertIn("duration plan digest", mismatch.stdout.lower())

    def test_confirmation_binds_contract_and_plan_tampering_fails_before_key_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, contract_path = self.prepare_and_preflight(root)
            confirmation_result = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_confirmation_args(contract_path),
            ])
            confirmation = Path(json.loads(confirmation_result.stdout)["confirmation_file"])
            confirmation_data = json.loads(confirmation.read_text(encoding="utf-8"))
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            self.assertEqual(confirmation_data["contract_digest"], contract["contract_digest"])
            self.assertEqual(confirmation_data["max_paid_submissions"], 1)
            self.assertTrue(confirmation_data["single_production_package_confirmed"])
            self.assertTrue(confirmation_data["two_confirmation_package_confirmed"])
            self.assertEqual(confirmation_data["confirmation_stage"], "production_authorized")
            self.assertEqual(confirmation_data["image_confirmation_intent"], "confirm_images_and_start")
            self.assertEqual(
                confirmation_data["confirmed_duration_plan_digest"],
                contract["duration_plan_digest"],
            )
            self.assertEqual(
                confirmation_data["approval_scope"],
                "plan_then_exact_images_then_base_paid_requests_and_no_cost_postprocess",
            )
            policy = confirmation_data["autonomous_execution"]
            self.assertTrue(policy["enabled"])
            self.assertTrue(policy["no_additional_confirmation_for_approved_actions"])
            self.assertTrue(policy["allow_no_cost_repairs"])
            self.assertFalse(policy["allow_quality_regeneration_within_paid_cap"])
            self.assertFalse(policy["allow_terminal_provider_retry_within_paid_cap"])
            self.assertFalse(policy["allow_ambiguous_submission_retry"])
            self.assertEqual(policy["base_paid_request_count"], 1)
            self.assertEqual(policy["repair_reserve_paid_submissions"], 0)
            self.assertEqual(policy["per_shot_repair_limit"], 0)

            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["script_text"] += "确认后被修改"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            rejected = run_command([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", str(plan_path),
                "--config", str(CONFIG),
                "--confirmation-file", str(confirmation),
                "--max-paid-submissions", "1",
            ], expect_success=False)
            self.assertIn("contract", rejected.stdout.lower())

    def test_confirmation_rejects_paid_cap_above_base_request_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, contract_path = self.prepare_and_preflight(root)

            rejected = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_confirmation_args(contract_path),
                "--max-paid-submissions", "2",
            ], expect_success=False)

            self.assertIn("must equal", rejected.stdout.lower())
            self.assertIn("base paid request", rejected.stdout.lower())

    def test_confirmation_rejects_explicit_zero_paid_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, contract_path = self.prepare_and_preflight(root)

            rejected = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_confirmation_args(contract_path),
                "--max-paid-submissions", "0",
            ], expect_success=False)

            self.assertIn("must be greater than zero", rejected.stdout.lower())

    def test_confirmation_rejects_nonzero_per_shot_repair_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, contract_path = self.prepare_and_preflight(root)

            rejected = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_confirmation_args(contract_path),
                "--per-shot-repair-limit", "1",
            ], expect_success=False)

            self.assertIn("must be 0", rejected.stdout)
            self.assertIn("paid regeneration", rejected.stdout.lower())

    def test_preflight_is_read_only_idempotent_after_paid_submission_and_rejects_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, contract_path = self.prepare_and_preflight(root)
            confirmation_result = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_confirmation_args(contract_path),
            ])
            self.assertTrue(Path(json.loads(confirmation_result.stdout)["confirmation_file"]).exists())
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            ledger = load_or_create_jobs(plan_path.parent, plan, contract["contract_digest"], max_paid_submissions=1)
            transition_job(plan_path.parent, ledger, "shot_01", "submitting")
            record_submission_attempt(plan_path.parent, ledger, "shot_01")

            protected_paths = [
                contract_path,
                plan_path.parent / "model-snapshot.json",
                plan_path.parent / "requests" / "dry-run" / "shot_01.json",
            ]
            before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in protected_paths}

            same = run_command([
                "python3", str(SCRIPTS / "preflight_project.py"),
                "--plan", str(plan_path),
                "--config", str(CONFIG),
            ])
            self.assertTrue(json.loads(same.stdout)["ok"])
            self.assertTrue(json.loads(same.stdout).get("contract_reused"))
            for path in protected_paths:
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before[path])

            changed_plan = json.loads(plan_path.read_text(encoding="utf-8"))
            changed_plan["project_name"] += "-drifted-after-paid-submit"
            plan_path.write_text(json.dumps(changed_plan), encoding="utf-8")
            drift = run_command([
                "python3", str(SCRIPTS / "preflight_project.py"),
                "--plan", str(plan_path),
                "--config", str(CONFIG),
            ], expect_success=False)
            self.assertIn("immutable", drift.stdout.lower())
            self.assertIn("paid", drift.stdout.lower())
            for path in protected_paths:
                if path == plan_path:
                    continue
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before[path])

    def test_preflight_cannot_replace_contract_after_unpaid_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, contract_path = self.prepare_and_preflight(root)
            confirmation_result = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_confirmation_args(contract_path),
            ])
            confirmation_path = Path(json.loads(confirmation_result.stdout)["confirmation_file"])
            before_contract = contract_path.read_bytes()
            before_confirmation = confirmation_path.read_bytes()
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["project_name"] += "-changed-before-payment"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            rejected = run_command([
                "python3", str(SCRIPTS / "preflight_project.py"),
                "--plan", str(plan_path),
                "--config", str(CONFIG),
            ], expect_success=False)

            self.assertIn("confirmation", rejected.stdout.lower())
            self.assertIn("cannot overwrite", rejected.stdout.lower())
            self.assertEqual(contract_path.read_bytes(), before_contract)
            self.assertEqual(confirmation_path.read_bytes(), before_confirmation)

    def test_confirmation_is_idempotent_but_cannot_be_overwritten_after_paid_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, contract_path = self.prepare_and_preflight(root)
            command = [
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_confirmation_args(contract_path),
            ]
            first = run_command(command)
            confirmation_path = Path(json.loads(first.stdout)["confirmation_file"])
            first_bytes = confirmation_path.read_bytes()
            first_mtime = confirmation_path.stat().st_mtime_ns
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            ledger = load_or_create_jobs(plan_path.parent, plan, contract["contract_digest"], max_paid_submissions=1)
            transition_job(plan_path.parent, ledger, "shot_01", "submitting")
            record_submission_attempt(plan_path.parent, ledger, "shot_01")

            second = run_command(command)
            self.assertTrue(json.loads(second.stdout).get("idempotent"))
            self.assertEqual(confirmation_path.read_bytes(), first_bytes)
            self.assertEqual(confirmation_path.stat().st_mtime_ns, first_mtime)

            changed = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "different-user",
                *self.image_confirmation_args(contract_path),
            ], expect_success=False)
            self.assertIn("cannot overwrite", changed.stdout.lower())
            self.assertIn("paid", changed.stdout.lower())
            self.assertEqual(confirmation_path.read_bytes(), first_bytes)

    def test_submit_rejects_a_paid_cap_higher_than_the_confirmed_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, contract_path = self.prepare_and_preflight(root)
            confirmation_result = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_confirmation_args(contract_path),
            ])
            confirmation = Path(json.loads(confirmation_result.stdout)["confirmation_file"])

            rejected = run_command([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", str(plan_path),
                "--confirmation-file", str(confirmation),
                "--max-paid-submissions", "2",
            ], expect_success=False)

            self.assertIn("confirmed paid submission cap", rejected.stdout.lower())
            self.assertNotIn("Missing API key", rejected.stdout)
            self.assertNotIn("Missing API key", rejected.stdout)

    def test_submit_rejects_confirmation_duration_plan_digest_tampering_before_key_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, contract_path = self.prepare_and_preflight(root)
            confirmation_result = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_confirmation_args(contract_path),
            ])
            confirmation_path = Path(json.loads(confirmation_result.stdout)["confirmation_file"])
            confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
            confirmation["confirmed_duration_plan_digest"] = "e" * 64
            confirmation_path.write_text(json.dumps(confirmation), encoding="utf-8")

            rejected = run_command([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", str(plan_path),
                "--confirmation-file", str(confirmation_path),
                "--max-paid-submissions", "1",
            ], expect_success=False)

            self.assertIn("duration plan digest", rejected.stdout.lower())
            self.assertNotIn("missing api key", rejected.stdout.lower())

    def test_submit_rejects_an_explicit_zero_paid_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, contract_path = self.prepare_and_preflight(root)
            confirmation_result = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_confirmation_args(contract_path),
            ])
            confirmation = Path(json.loads(confirmation_result.stdout)["confirmation_file"])

            rejected = run_command([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", str(plan_path),
                "--confirmation-file", str(confirmation),
                "--max-paid-submissions", "0",
            ], expect_success=False)

            self.assertIn("must be greater than zero", rejected.stdout.lower())
            self.assertNotIn("Missing API key", rejected.stdout)

    def test_confirmation_rejects_asset_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, contract_path = self.prepare_and_preflight(root)
            confirmation_result = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_confirmation_args(contract_path),
            ])
            confirmation = Path(json.loads(confirmation_result.stdout)["confirmation_file"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            Path(plan["confirmed_assets"][0]["value"]).write_bytes(b"changed-after-confirmation")
            rejected = run_command([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", str(plan_path),
                "--config", str(CONFIG),
                "--confirmation-file", str(confirmation),
                "--max-paid-submissions", "1",
            ], expect_success=False)
            self.assertIn("contract", rejected.stdout.lower())
            self.assertNotIn("Missing API key", rejected.stdout)

    def test_paid_submit_uses_confirmed_custom_model_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"custom-model-avatar")
            config = json.loads(CONFIG.read_text(encoding="utf-8"))
            custom_key = "custom_snapshot_route"
            config["models"][custom_key] = json.loads(json.dumps(config["models"]["grok_talking_head_basic"]))
            config["models"][custom_key]["provider"] = "custom-snapshot-provider"
            config_path = root / "custom-config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            prepared = run_command([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "custom-model-snapshot",
                "--project-root", str(root / "projects"),
                "--content-mode", "avatar_talking_head",
                "--duration", "15",
                "--avatar-reference", str(avatar),
                "--script-text", READY_SEGMENT_1,
                "--config", str(config_path),
                "--model-key", custom_key,
                "--subtitle-choice", "disabled",
                "--effects-choice", "disabled",
            ])
            plan_path = Path(json.loads(prepared.stdout)["plan"])
            preflight = run_command([
                "python3", str(SCRIPTS / "preflight_project.py"),
                "--plan", str(plan_path),
                "--config", str(config_path),
            ])
            contract_path = Path(json.loads(preflight.stdout)["contract_file"])
            confirmed = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "custom-model-test",
                *self.image_confirmation_args(contract_path),
            ])
            confirmation = Path(json.loads(confirmed.stdout)["confirmation_file"])

            result = run_command([
                "python3", str(SCRIPTS / "workflow_engine.py"),
                "--project-dir", str(plan_path.parent),
                "submit", "--confirmation-file", str(confirmation),
                "--max-paid-submissions", "1",
            ], expect_success=False)

            self.assertIn("Missing API key", result.stdout)
            self.assertNotIn("Unknown model key", result.stdout)

    def test_resume_selection_skips_ambiguous_or_completed_jobs(self):
        from generate_video import selected_shots_for_submission

        plan = {"shots": [{"id": "shot_01"}, {"id": "shot_02"}, {"id": "shot_03"}]}
        ledger = {
            "jobs": {
                "shot_01": {"state": "submitted"},
                "shot_02": {"state": "failed"},
                "shot_03": {"state": "verified"},
            }
        }
        selected, skipped = selected_shots_for_submission(plan, ledger, None)
        self.assertEqual([shot["id"] for shot in selected], ["shot_02"])
        self.assertEqual({item["shot_id"] for item in skipped}, {"shot_01", "shot_03"})

    def test_resume_never_resubmits_a_previous_paid_attempt_even_with_legacy_retry_selector(self):
        from generate_video import selected_shots_for_submission

        plan = {"shots": [{"id": "shot_01"}, {"id": "shot_02"}]}
        ledger = {
            "jobs": {
                "shot_01": {
                    "state": "failed",
                    "request_id": "existing-request",
                    "last_error": "Network error calling status endpoint",
                },
                "shot_02": {
                    "state": "failed",
                    "request_id": "",
                    "submission_attempts": 1,
                    "last_error": "Network error during submission",
                },
            }
        }

        selected, skipped = selected_shots_for_submission(plan, ledger, None)

        self.assertEqual(selected, [])
        self.assertEqual(skipped, [
            {
                "shot_id": "shot_01",
                "state": "failed",
                "reason": "existing_request_id_requires_poll_or_user_decision",
            },
            {
                "shot_id": "shot_02",
                "state": "failed",
                "reason": "second_paid_submission_disabled",
            },
        ])

        selected, skipped = selected_shots_for_submission(
            plan,
            ledger,
            "shot_02",
            retry_failed_shot="shot_02",
        )
        self.assertEqual(selected, [])
        self.assertEqual(skipped, [{
            "shot_id": "shot_02",
            "state": "failed",
            "reason": "second_paid_submission_disabled",
        }])

    def test_verified_shot_cannot_be_regenerated_even_with_legacy_selector(self):
        from generate_video import selected_shots_for_submission

        plan = {"shots": [{"id": "shot_01"}, {"id": "shot_02"}]}
        ledger = {
            "jobs": {
                "shot_01": {"state": "verified", "submission_attempts": 1},
                "shot_02": {"state": "verified", "submission_attempts": 1},
            }
        }

        selected, skipped = selected_shots_for_submission(
            plan,
            ledger,
            "shot_02",
            regenerate_shot="shot_02",
        )

        self.assertEqual(selected, [])
        self.assertEqual(skipped, [{
            "shot_id": "shot_02",
            "state": "verified",
            "reason": "second_paid_submission_disabled",
        }])

    def test_paid_retry_and_regeneration_flags_fail_before_key_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, contract_path = self.prepare_and_preflight(root)
            confirmation_result = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_confirmation_args(contract_path),
            ])
            confirmation = Path(json.loads(confirmation_result.stdout)["confirmation_file"])

            for option in ("--retry-failed-shot", "--regenerate-shot"):
                with self.subTest(option=option):
                    rejected = run_command([
                        "python3", str(SCRIPTS / "generate_video.py"),
                        "--plan", str(plan_path),
                        "--confirmation-file", str(confirmation),
                        "--max-paid-submissions", "1",
                        option, "shot_01",
                    ], expect_success=False)
                    self.assertIn("paid retry and regeneration flags are disabled", rejected.stdout.lower())
                    self.assertNotIn("missing api key", rejected.stdout.lower())

    def test_submission_budget_is_checked_before_processing_any_selected_shot(self):
        from generate_video import ensure_submission_budget

        ledger = {
            "paid_submission_attempts": 1,
            "max_paid_submissions": 2,
        }
        with self.assertRaisesRegex(ScriptError, "remaining 1"):
            ensure_submission_budget(ledger, [{"id": "shot_01"}, {"id": "shot_02"}])

    def test_resume_reports_paid_jobs_that_require_user_action(self):
        from workflow_engine import jobs_requiring_user_action

        ledger = {
            "jobs": {
                "shot_01": {"state": "failed", "request_id": "", "submission_attempts": 1},
                "shot_02": {"state": "failed", "request_id": "terminal-request", "last_error": "Generation FAILED"},
                "shot_03": {"state": "verified", "request_id": "done"},
            }
        }

        actions = jobs_requiring_user_action(ledger)

        self.assertEqual([item["shot_id"] for item in actions], ["shot_01", "shot_02"])

    def test_terminal_failure_is_blocked_without_automatic_paid_repair(self):
        from workflow_engine import jobs_requiring_user_action

        ledger = {
            "paid_submission_attempts": 2,
            "max_paid_submissions": 3,
            "jobs": {
                "shot_01": {"state": "failed", "request_id": "terminal-request", "last_error": "Generation FAILED"},
                "shot_02": {"state": "verified", "request_id": "done"},
            },
        }
        confirmation = {
            "autonomous_execution": {
                "enabled": True,
                "allow_terminal_provider_retry_within_paid_cap": True,
                "allow_ambiguous_submission_retry": False,
            }
        }

        self.assertEqual(
            jobs_requiring_user_action(ledger, confirmation),
            [{"shot_id": "shot_01", "reason": "terminal_provider_failure_no_paid_retry"}],
        )

    def test_terminal_job_resume_skips_submission_before_key_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, contract_path = self.prepare_and_preflight(root)
            confirmation_result = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_confirmation_args(contract_path),
            ])
            confirmation = Path(json.loads(confirmation_result.stdout)["confirmation_file"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            ledger = load_or_create_jobs(plan_path.parent, plan, contract["contract_digest"], max_paid_submissions=1)
            transition_job(plan_path.parent, ledger, "shot_01", "submitting")
            record_submission_attempt(plan_path.parent, ledger, "shot_01")
            transition_job(plan_path.parent, ledger, "shot_01", "submitted", request_id="terminal-request")
            transition_job(
                plan_path.parent,
                ledger,
                "shot_01",
                "failed",
                request_id="terminal-request",
                last_error="Generation FAILED: provider terminal failure",
            )

            result = run_command([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", str(plan_path),
                "--confirmation-file", str(confirmation),
                "--max-paid-submissions", "1",
            ])

            data = json.loads(result.stdout)
            self.assertTrue(data["ok"])
            self.assertEqual(data["results"], [])
            self.assertEqual(data["skipped"][0]["shot_id"], "shot_01")
            self.assertNotIn("missing api key", result.stdout.lower())

    def test_mock_submit_terminal_failure_then_resume_never_posts_twice(self):
        import generate_video
        import poll_video
        import workflow_engine

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, contract_path = self.prepare_and_preflight(root)
            confirmation_result = run_command([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", str(contract_path),
                "--approved-by", "workflow-test-user",
                *self.image_confirmation_args(contract_path),
            ])
            confirmation_path = Path(json.loads(confirmation_result.stdout)["confirmation_file"])
            post_call_count = 0

            def fake_http(method, *_args, **_kwargs):
                nonlocal post_call_count
                if method == "POST":
                    post_call_count += 1
                    return {"id": "request-shot-01"}
                return {
                    "id": "request-shot-01",
                    "status": "FAILED",
                    "fail_reason": "terminal provider failure",
                }

            submit_stdout = io.StringIO()
            with (
                patch.object(sys, "argv", [
                    "generate_video.py",
                    "--plan", str(plan_path),
                    "--confirmation-file", str(confirmation_path),
                    "--max-paid-submissions", "1",
                ]),
                patch("generate_video.find_api_key", return_value="mock-key"),
                patch("generate_video.http_json", side_effect=fake_http),
                patch("sys.stdout", submit_stdout),
            ):
                self.assertEqual(generate_video.main(), 0)
            request_path = Path(json.loads(submit_stdout.getvalue())["results"][0]["request_file"])
            self.assertEqual(post_call_count, 1)

            with (
                patch.object(sys, "argv", ["poll_video.py", "--request-file", str(request_path), "--timeout", "1", "--interval", "0"]),
                patch("poll_video.find_api_key", return_value="mock-key"),
                patch("poll_video.http_json", side_effect=fake_http),
                patch("sys.stdout", io.StringIO()),
            ):
                self.assertEqual(poll_video.main(), 1)

            def in_process_worker(command):
                self.assertEqual(Path(command[1]).name, "generate_video.py")
                output = io.StringIO()
                with (
                    patch.object(sys, "argv", ["generate_video.py", *command[2:]]),
                    patch("generate_video.find_api_key", return_value="mock-key"),
                    patch("generate_video.http_json", side_effect=fake_http),
                    patch("sys.stdout", output),
                ):
                    code = generate_video.main()
                return code, json.loads(output.getvalue())

            resume_stdout = io.StringIO()
            with (
                patch.object(sys, "argv", [
                    "workflow_engine.py",
                    "--project-dir", str(plan_path.parent),
                    "resume",
                    "--confirmation-file", str(confirmation_path),
                    "--max-paid-submissions", "1",
                    "--timeout", "1",
                    "--interval", "0",
                ]),
                patch("workflow_engine.run_worker", side_effect=in_process_worker),
                patch("sys.stdout", resume_stdout),
            ):
                self.assertEqual(workflow_engine.main(), 1)

            resume_result = json.loads(resume_stdout.getvalue())
            self.assertTrue(resume_result["blocked"])
            self.assertEqual(post_call_count, 1)
            jobs = json.loads((plan_path.parent / "jobs.json").read_text(encoding="utf-8"))
            self.assertEqual(jobs["paid_submission_attempts"], 1)
            self.assertEqual(jobs["jobs"]["shot_01"]["submission_attempts"], 1)

    def test_legacy_confirmation_cannot_reenable_automatic_paid_repair(self):
        from workflow_engine import jobs_requiring_user_action

        ledger = {
            "paid_submission_attempts": 2,
            "max_paid_submissions": 4,
            "jobs": {
                "shot_01": {
                    "state": "failed",
                    "request_id": "terminal-request",
                    "last_error": "Generation FAILED",
                    "repair_submission_attempts": 1,
                },
            },
        }
        confirmation = {
            "autonomous_execution": {
                "enabled": True,
                "allow_terminal_provider_retry_within_paid_cap": True,
                "per_shot_repair_limit": 1,
            }
        }

        self.assertEqual(
            jobs_requiring_user_action(ledger, confirmation),
            [{"shot_id": "shot_01", "reason": "terminal_provider_failure_no_paid_retry"}],
        )

    def test_mock_poll_updates_job_to_verified(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            asset = project / "avatar.png"
            asset.write_bytes(b"avatar")
            plan = base_plan(asset)
            clip = project / "clips" / "shot_01.mp4"
            plan["shots"][0]["clip_file"] = str(clip)
            contract = build_contract(plan, base_model(), base_request())
            (project / "production-contract.json").write_text(json.dumps(contract), encoding="utf-8")
            (project / "model-snapshot.json").write_text(json.dumps(contract["model_snapshot"]), encoding="utf-8")
            ledger = load_or_create_jobs(project, plan, contract["contract_digest"], max_paid_submissions=1)
            transition_job(project, ledger, "shot_01", "submitting")
            record_submission_attempt(project, ledger, "shot_01")
            request_file = project / "requests" / "shot_01_request.json"
            request_file.parent.mkdir(parents=True)
            request_file.write_text(json.dumps({
                "shot_id": "shot_01",
                "model_key": "grok_talking_head_basic",
                "contract_digest": contract["contract_digest"],
                "response": {"request_id": "mock-request"},
            }), encoding="utf-8")
            transition_job(project, ledger, "shot_01", "submitted", request_id="mock-request", request_file=str(request_file))

            mock_video = project / "mock.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                "-t", "1", "-c:v", "libx264", "-c:a", "aac", str(mock_video),
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            result = run_command([
                "python3", str(SCRIPTS / "poll_video.py"),
                "--request-file", str(request_file),
                "--mock-video", str(mock_video),
                "--require-audio",
            ])
            self.assertTrue(json.loads(result.stdout)["ok"])
            updated = json.loads((project / "jobs.json").read_text(encoding="utf-8"))
            self.assertEqual(updated["jobs"]["shot_01"]["state"], "verified")
            self.assertEqual(updated["jobs"]["shot_01"]["clip_file"], str(clip.resolve()))
            self.assertTrue(updated["jobs"]["shot_01"]["clip_sha256"])
            self.assertEqual(updated["jobs"]["shot_01"]["clip_sha256"], json.loads(result.stdout)["output_sha256"])
            poll_record = json.loads(Path(json.loads(result.stdout)["result_file"]).read_text(encoding="utf-8"))
            self.assertEqual(poll_record.get("shot_id"), "shot_01")
            self.assertEqual(poll_record.get("request_id"), "mock-request")
            self.assertEqual(poll_record.get("contract_digest"), contract["contract_digest"])
            self.assertEqual(poll_record["video"]["local_path"], str(clip.resolve()))


class WorkflowFinalizationTests(unittest.TestCase):
    def test_review_render_hard_blocks_real_mp4_above_delivery_max(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        for requested_duration in (30.08, 30.9, 31.4):
            with self.subTest(requested_duration=requested_duration), tempfile.TemporaryDirectory() as tmp:
                project = Path(tmp)
                video = project / "final.mp4"
                subprocess.run([
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=25",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                    "-t", str(requested_duration),
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(video),
                ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                plan = {
                    "content_mode": "avatar_talking_head",
                    "execution_route": "video_generation",
                    "total_duration_seconds": 30,
                    "delivery_duration_seconds": 30,
                    "duration_plan": {
                        "delivery_max_seconds": 30,
                        "planned_duration_seconds": 30,
                        "estimated_script_seconds": 26,
                        "duration_tolerance": "content_complete_flexible",
                    },
                    "subtitle_plan": {"enabled": False},
                    "script_pacing": {"status": "ok"},
                    "shots": [{
                        "id": "shot_01",
                        "clip_file": str(video),
                        "duration_seconds": 30,
                        "script_boundary": {"stitch_safe": True},
                    }],
                }
                plan_path = project / "generation-plan.json"
                plan_path.write_text(json.dumps(plan), encoding="utf-8")

                result = run_command([
                    "python3", str(SCRIPTS / "review_render.py"),
                    "--project-dir", str(project),
                    "--plan", str(plan_path),
                    "--video", str(video),
                ], expect_success=False)

                data = json.loads(result.stdout)
                self.assertEqual(data["status"], "fail")
                self.assertTrue(any("hard limit" in item.lower() for item in data["issues_found"]), data)

    def test_captioned_delivery_reuses_the_matching_raw_stitch_report(self):
        from review_render import read_stitch_report

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "final.fixed-restitch.subtitled.mp4"
            video.write_bytes(b"video")
            report = root / "final.fixed-restitch.stitch-report.json"
            report.write_text(json.dumps({
                "audio_boundary_policy": {
                    "per_clip_fades_applied": False,
                    "single_final_aac_encode": True,
                }
            }), encoding="utf-8")

            loaded = read_stitch_report(video)

            self.assertEqual(loaded["path"], str(report))
            self.assertFalse(loaded["data"]["audio_boundary_policy"]["per_clip_fades_applied"])

    def write_project(self, project: Path, with_clip: bool, visual_status: str = "pass") -> tuple[Path, Path]:
        clips_dir = project / "clips"
        clips_dir.mkdir(parents=True)
        clip = clips_dir / "shot_01.mp4"
        avatar = project / "avatar.png"
        avatar.write_bytes(b"finalization-avatar")
        if with_clip:
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=24",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                "-t", "4", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(clip),
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        plan = {
            "duration_plan_digest": "b" * 64,
            "project_name": "finalization-test",
            "project_dir": str(project),
            "model_key": "test-model",
            "content_mode": "avatar_talking_head",
            "platform": "douyin",
            "language": "zh",
            "total_duration_seconds": 4,
            "delivery_duration_seconds": 4,
            "duration_plan": {
                "duration_plan_digest": "b" * 64,
                "delivery_max_seconds": 4,
                "planned_duration_seconds": 4,
            },
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "subtitle_strategy": "fixed zero-subtitle policy",
            "subtitle_plan": {
                "enabled": False,
                "choice": "disabled",
                "source": "none",
                "srt_output": "",
                "burned_video_output": "",
            },
            "script_pacing": {"status": "ok"},
            "confirmed_assets": [{
                "id": "avatar",
                "kind": "file",
                "role": "avatar_reference",
                "value": str(avatar),
            }],
            "stitching_plan": {
                "required": True,
                "target_resolution": "720x1280",
                "target_fps": 24,
                "final_output": str(project / "final.mp4"),
            },
            "shots": [{
                "id": "shot_01",
                "duration_seconds": 4,
                "script_segment": "这是最终交付测试。",
                "script_pacing": {"status": "ok", "estimated_spoken_seconds": 4, "target_duration_seconds": 4},
                "script_boundary": {"boundary_type": "strong_sentence", "stitch_safe": True},
                "clip_file": str(clip),
            }],
        }
        plan_path = project / "generation-plan.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        model = base_model()
        model["key"] = "test-model"
        dry_run_record = {
            "shot_id": "shot_01",
            "model_key": "test-model",
            "payload": {"prompt": "test", "duration": 4},
            "asset_trace": {},
            "dry_run": True,
        }
        dry_run_dir = project / "requests" / "dry-run"
        dry_run_dir.mkdir(parents=True)
        (dry_run_dir / "shot_01.json").write_text(json.dumps(dry_run_record), encoding="utf-8")
        contract = build_contract(plan, model, [dry_run_record])
        (project / "production-contract.json").write_text(json.dumps(contract), encoding="utf-8")
        (project / "model-snapshot.json").write_text(json.dumps(contract["model_snapshot"]), encoding="utf-8")
        payload_asset_digests = [
            item["sha256"] for item in contract["asset_fingerprints"]
            if item.get("role") in {"avatar_reference", "video_source", "first_frame", "segment_source"}
        ]
        confirmation = {
            "version": "1.0",
            "confirmation_stage": "production_authorized",
            "plan_confirmed": True,
            "image_assets_confirmed": True,
            "video_generation_confirmed": True,
            "single_production_package_confirmed": True,
            "two_confirmation_package_confirmed": True,
            "image_confirmation_intent": "confirm_images_and_start",
            "confirmed_asset_digests": payload_asset_digests,
            "confirmed_duration_plan_digest": plan["duration_plan_digest"],
            "contract_digest": contract["contract_digest"],
            "contract_file": str(project / "production-contract.json"),
            "approved_by": "finalization-test-user",
            "approved_at": 1,
            "max_paid_submissions": 1,
            "autonomous_execution": {
                "enabled": True,
                "base_paid_request_count": 1,
                "repair_reserve_paid_submissions": 0,
                "per_shot_repair_limit": 0,
                "allow_terminal_provider_retry_within_paid_cap": False,
                "allow_quality_regeneration_within_paid_cap": False,
            },
        }
        (project / "video-confirmation.json").write_text(json.dumps(confirmation), encoding="utf-8")
        request_file = project / "requests" / "shot_01_request.json"
        request_file.write_text(json.dumps({
            **dry_run_record,
            "contract_digest": contract["contract_digest"],
            "dry_run": False,
            "response": {"request_id": "request-shot-01"},
        }), encoding="utf-8")
        poll_file = project / "requests" / "shot_01_poll.json"
        poll_file.write_text(json.dumps({
            "status": "done",
            "shot_id": "shot_01",
            "request_id": "request-shot-01",
            "contract_digest": contract["contract_digest"],
            "video": {"local_path": str(clip)},
            "output_sha256": hashlib.sha256(clip.read_bytes()).hexdigest() if clip.exists() else "",
        }), encoding="utf-8")
        jobs = {
            "contract_digest": contract["contract_digest"],
            "max_paid_submissions": 1,
            "paid_submission_attempts": 1,
            "jobs": {"shot_01": {
                "shot_id": "shot_01",
                "state": "verified",
                "submission_attempts": 1,
                "repair_submission_attempts": 0,
                "last_submission_reason": "initial",
                "request_id": "request-shot-01",
                "request_file": str(request_file),
                "poll_file": str(poll_file),
                "clip_file": str(clip),
                "clip_sha256": hashlib.sha256(clip.read_bytes()).hexdigest() if clip.exists() else "",
            }},
        }
        (project / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
        visual = {
            "status": visual_status,
            "identity_consistent": visual_status == "pass",
            "outfit_consistent": visual_status == "pass",
            "scene_consistent": visual_status == "pass",
            "framing_consistent": visual_status == "pass",
            "lip_sync_acceptable": visual_status == "pass",
            "mouth_visible": visual_status == "pass",
            "subtitle_safe": visual_status == "pass",
            "subtitle_readable": visual_status == "pass",
            "subtitle_matches_speech": visual_status == "pass",
            "subtitle_background_absent": visual_status == "pass",
            "no_unapproved_visual_insert": visual_status == "pass",
            "no_generated_text": visual_status == "pass",
            "spoken_content_complete": visual_status == "pass",
            "reviewed_frames": [str(project / "review-frame-01.jpg")],
            "reviewed_video": {"path": "", "sha256": ""},
            "speech_evidence": {
                "status": "pass" if visual_status == "pass" else "revise",
                "method": "test_fixture_review",
                "transcript": str(project / "speech-transcript.txt"),
                "segments_reviewed": ["shot_01"],
                "pronunciation_acceptable": visual_status == "pass",
                "voice_consistent": visual_status == "pass",
                "volume_consistent": visual_status == "pass",
                "unresolved_discrepancies": [],
            },
        }
        (project / "review-frame-01.jpg").write_bytes(b"review-frame")
        (project / "speech-transcript.txt").write_text("spoken content", encoding="utf-8")
        (project / "visual-review.json").write_text(json.dumps(visual), encoding="utf-8")
        return plan_path, clip

    def test_finalize_blocks_plan_drift_from_the_confirmed_contract(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            plan_path, _ = self.write_project(project, with_clip=True)
            stale_postprocess = project / "postprocess-manifest.json"
            stale_postprocess.write_text(json.dumps({
                "status": "pass",
                "finalize_run_id": "stale-previous-run",
            }), encoding="utf-8")
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["subtitle_strategy"] = "changed after confirmation"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            result = run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ], expect_success=False)

            self.assertIn("production contract", result.stdout.lower())
            self.assertFalse((project / "delivery-manifest.json").exists())
            self.assertTrue(stale_postprocess.exists())
            blocked = json.loads((project / "finalize-report.json").read_text(encoding="utf-8"))
            self.assertNotIn("postprocess_manifest", blocked)

    def test_finalize_blocks_missing_planned_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_project(project, with_clip=False)
            result = run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ], expect_success=False)
            self.assertIn("missing", result.stdout.lower())
            self.assertFalse((project / "delivery-manifest.json").exists())

    def test_finalize_blocks_clip_changed_after_poll_verification(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _, clip = self.write_project(project, with_clip=True)
            with clip.open("ab") as handle:
                handle.write(b"tampered-after-verification")

            result = run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ], expect_success=False)

            self.assertIn("verified clip sha256 mismatch", result.stdout.lower())
            self.assertFalse((project / "delivery-manifest.json").exists())

    def test_finalize_blocks_paid_attempts_above_base_request_count(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_project(project, with_clip=True)
            jobs_path = project / "jobs.json"
            jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
            jobs["max_paid_submissions"] = 2
            jobs["paid_submission_attempts"] = 2
            jobs_path.write_text(json.dumps(jobs), encoding="utf-8")

            result = run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ], expect_success=False)

            self.assertIn("base paid request", result.stdout.lower())
            self.assertFalse((project / "delivery-manifest.json").exists())

    def test_finalize_blocks_quality_regeneration_history(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_project(project, with_clip=True)
            jobs_path = project / "jobs.json"
            jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
            jobs["jobs"]["shot_01"].update({
                "submission_attempts": 1,
                "repair_submission_attempts": 1,
                "last_submission_reason": "quality_regeneration",
            })
            jobs_path.write_text(json.dumps(jobs), encoding="utf-8")

            result = run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ], expect_success=False)

            self.assertIn("quality_regeneration", result.stdout)
            self.assertFalse((project / "delivery-manifest.json").exists())

    def test_finalize_requires_exact_base_paid_submission_count(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_project(project, with_clip=True)
            jobs_path = project / "jobs.json"
            jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
            jobs["paid_submission_attempts"] = 0
            jobs_path.write_text(json.dumps(jobs), encoding="utf-8")

            result = run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ], expect_success=False)

            self.assertIn("must equal", result.stdout.lower())
            self.assertIn("base paid request", result.stdout.lower())

    def test_finalize_blocks_paid_request_payload_drift_from_dry_run(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_project(project, with_clip=True)
            request_path = project / "requests" / "shot_01_request.json"
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request["payload"]["prompt"] = "tampered paid payload"
            request_path.write_text(json.dumps(request), encoding="utf-8")

            result = run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ], expect_success=False)

            self.assertIn("paid request payload", result.stdout.lower())
            self.assertIn("dry-run", result.stdout.lower())

    def test_finalize_blocks_poll_request_and_clip_binding_drift(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_project(project, with_clip=True)
            poll_path = project / "requests" / "shot_01_poll.json"
            poll = json.loads(poll_path.read_text(encoding="utf-8"))
            poll["request_id"] = "wrong-request-id"
            poll_path.write_text(json.dumps(poll), encoding="utf-8")

            result = run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ], expect_success=False)

            self.assertIn("poll", result.stdout.lower())
            self.assertIn("request_id", result.stdout.lower())

    def test_finalize_blocks_confirmation_duration_digest_drift(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_project(project, with_clip=True)
            confirmation_path = project / "video-confirmation.json"
            confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
            confirmation["confirmed_duration_plan_digest"] = "c" * 64
            confirmation_path.write_text(json.dumps(confirmation), encoding="utf-8")

            result = run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ], expect_success=False)

            self.assertIn("confirmation", result.stdout.lower())
            self.assertIn("duration plan digest", result.stdout.lower())

    def test_finalize_independently_blocks_actual_mp4_above_delivery_max(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _, clip = self.write_project(project, with_clip=True)
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                "-t", "4.08", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(clip),
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            clip_digest = hashlib.sha256(clip.read_bytes()).hexdigest()
            jobs_path = project / "jobs.json"
            jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
            jobs["jobs"]["shot_01"]["clip_sha256"] = clip_digest
            jobs_path.write_text(json.dumps(jobs), encoding="utf-8")
            poll_path = project / "requests" / "shot_01_poll.json"
            poll = json.loads(poll_path.read_text(encoding="utf-8"))
            poll["output_sha256"] = clip_digest
            poll_path.write_text(json.dumps(poll), encoding="utf-8")

            result = run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ], expect_success=False)

            self.assertIn("delivery duration hard limit exceeded", result.stdout.lower())
            self.assertFalse((project / "delivery-manifest.json").exists())

    def test_finalize_rechecks_protected_request_evidence_before_delivery(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        import finalize_project

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_project(project, with_clip=True)
            run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ], expect_success=False)
            final_video = project / "final.mp4"
            visual_path = project / "visual-review.json"
            visual = json.loads(visual_path.read_text(encoding="utf-8"))
            visual["reviewed_video"] = {
                "path": str(final_video),
                "sha256": hashlib.sha256(final_video.read_bytes()).hexdigest(),
            }
            visual_path.write_text(json.dumps(visual), encoding="utf-8")
            request_path = project / "requests" / "shot_01_request.json"
            real_run_worker = finalize_project.run_worker

            def mutate_after_review(command):
                result = real_run_worker(command)
                if Path(command[1]).name == "review_render.py":
                    request = json.loads(request_path.read_text(encoding="utf-8"))
                    request["created_at"] = int(request.get("created_at") or 0) + 1
                    request_path.write_text(json.dumps(request), encoding="utf-8")
                return result

            output = io.StringIO()
            with (
                patch.object(sys, "argv", ["finalize_project.py", "--project-dir", str(project)]),
                patch("finalize_project.run_worker", side_effect=mutate_after_review),
                patch("sys.stdout", output),
            ):
                self.assertEqual(finalize_project.main(), 1)

            self.assertIn("changed during finalize", output.getvalue().lower())
            self.assertFalse((project / "delivery-manifest.json").exists())

    def test_finalize_creates_delivery_manifest_only_after_both_reviews_pass(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_project(project, with_clip=True)
            first = run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ], expect_success=False)
            self.assertIn("reviewed video", first.stdout.lower())
            postprocess_path = project / "postprocess-manifest.json"
            self.assertTrue(postprocess_path.exists())
            first_postprocess = json.loads(postprocess_path.read_text(encoding="utf-8"))
            self.assertEqual(first_postprocess["status"], "completed_review_blocked")
            self.assertTrue(first_postprocess["finalize_run_id"])
            self.assertEqual(first_postprocess["paid_video_requests_added"], 0)
            final_video = project / "final.mp4"
            visual_path = project / "visual-review.json"
            visual = json.loads(visual_path.read_text(encoding="utf-8"))
            import hashlib
            visual["reviewed_video"] = {
                "path": str(final_video),
                "sha256": hashlib.sha256(final_video.read_bytes()).hexdigest(),
            }
            visual_path.write_text(json.dumps(visual), encoding="utf-8")

            result = run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ])
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "pass")
            delivery = json.loads((project / "delivery-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(delivery["status"], "pass")
            self.assertTrue(delivery["final_video_sha256"])
            review = json.loads((project / "final-review.json").read_text(encoding="utf-8"))
            self.assertEqual(review["status"], "pass")
            self.assertEqual(review["output_sha256"], delivery["final_video_sha256"])
            self.assertEqual(delivery["artifact_hashes"]["final_video"]["sha256"], delivery["final_video_sha256"])
            self.assertEqual(len(delivery["artifact_hashes"]["clips"]), 1)
            for field in ("raw_final_video", "stitch_report", "technical_review", "visual_review"):
                self.assertTrue(delivery["artifact_hashes"][field]["sha256"], field)
            self.assertFalse(delivery["artifact_hashes"]["subtitle_file"]["sha256"])
            self.assertTrue(delivery["artifact_hashes"]["video_confirmation"]["sha256"])
            self.assertEqual(len(delivery["artifact_hashes"]["paid_requests"]), 1)
            self.assertEqual(len(delivery["artifact_hashes"]["poll_results"]), 1)
            self.assertTrue(delivery["artifact_hashes"]["paid_requests"][0]["sha256"])
            self.assertTrue(delivery["artifact_hashes"]["poll_results"][0]["sha256"])
            jobs_after = json.loads((project / "jobs.json").read_text(encoding="utf-8"))
            self.assertEqual(jobs_after["paid_submission_attempts"], 1)
            self.assertTrue(postprocess_path.exists())
            postprocess = json.loads(postprocess_path.read_text(encoding="utf-8"))
            self.assertEqual(postprocess["status"], "pass")
            self.assertNotEqual(postprocess["finalize_run_id"], first_postprocess["finalize_run_id"])
            self.assertTrue((project / "postprocess-history" / f"{first_postprocess['finalize_run_id']}.json").exists())
            self.assertEqual(postprocess["paid_video_requests_added"], 0)
            self.assertEqual(postprocess["paid_submission_attempts_before"], 1)
            self.assertEqual(postprocess["paid_submission_attempts_after"], 1)

    def test_failed_recheck_invalidates_existing_delivery_manifest(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_project(project, with_clip=True)
            first = run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ], expect_success=False)
            self.assertIn("reviewed video", first.stdout.lower())
            final_video = project / "final.mp4"
            visual_path = project / "visual-review.json"
            visual = json.loads(visual_path.read_text(encoding="utf-8"))
            import hashlib
            visual["reviewed_video"] = {
                "path": str(final_video),
                "sha256": hashlib.sha256(final_video.read_bytes()).hexdigest(),
            }
            visual_path.write_text(json.dumps(visual), encoding="utf-8")
            run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ])
            self.assertTrue((project / "delivery-manifest.json").exists())

            visual["status"] = "revise"
            visual_path.write_text(json.dumps(visual), encoding="utf-8")
            run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ], expect_success=False)
            self.assertFalse((project / "delivery-manifest.json").exists())
            postprocess_path = project / "postprocess-manifest.json"
            self.assertTrue(postprocess_path.exists())
            postprocess = json.loads(postprocess_path.read_text(encoding="utf-8"))
            self.assertEqual(postprocess["status"], "completed_review_blocked")
            self.assertEqual(postprocess["paid_video_requests_added"], 0)

    def test_finalize_blocks_failed_visual_review(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_project(project, with_clip=True, visual_status="revise")
            result = run_command([
                "python3", str(SCRIPTS / "finalize_project.py"),
                "--project-dir", str(project),
            ], expect_success=False)
            self.assertIn("visual review", result.stdout.lower())
            self.assertFalse((project / "delivery-manifest.json").exists())

    def test_workflow_engine_status_reports_current_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_project(project, with_clip=False)
            result = run_command([
                "python3", str(SCRIPTS / "workflow_engine.py"),
                "--project-dir", str(project),
                "status",
            ])
            self.assertEqual(json.loads(result.stdout)["stage"], "ready_to_finalize")

    def test_workflow_engine_status_blocks_ambiguous_paid_failure_without_reasking(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "generation-plan.json").write_text(json.dumps({"shots": [{"id": "shot_01"}]}), encoding="utf-8")
            (project / "jobs.json").write_text(json.dumps({
                "jobs": {"shot_01": {
                    "state": "failed",
                    "request_id": "",
                    "submission_attempts": 1,
                    "last_error": "network error during submission",
                }}
            }), encoding="utf-8")

            result = run_command([
                "python3", str(SCRIPTS / "workflow_engine.py"),
                "--project-dir", str(project),
                "status",
            ])

            self.assertEqual(json.loads(result.stdout)["stage"], "blocked_unsafe_to_continue")

    def test_workflow_engine_status_reports_blocked_finalize(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.write_project(project, with_clip=False)
            (project / "final-review.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")
            (project / "finalize-report.json").write_text(json.dumps({
                "status": "blocked",
                "issues": ["speech evidence has unresolved discrepancies"],
            }), encoding="utf-8")

            result = run_command([
                "python3", str(SCRIPTS / "workflow_engine.py"),
                "--project-dir", str(project),
                "status",
            ])

            data = json.loads(result.stdout)
            self.assertEqual(data["stage"], "blocked")
            self.assertTrue(data["files"]["finalize"])

    def test_postproduction_only_candidate_uses_zero_paid_delivery_gate(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source = project / "source.mp4"
            candidate = project / "final.postproduced.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                "-t", "4", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(source),
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            shutil.copy2(source, candidate)
            plan = {
                "project_name": "postproduction-test",
                "project_dir": str(project),
                "execution_route": "postproduction_only",
                "content_mode": "hybrid_broll_edit",
                "platform": "douyin",
                "language": "zh",
                "aspect_ratio": "16:9",
                "resolution": "360p",
                "total_duration_seconds": 4,
                "existing_video_file": {"value": str(source), "role": "existing_video"},
                "postproduction_plan": {
                    "enabled": True,
                    "candidate_output": str(candidate),
                    "edit_manifest": str(project / "postproduction-manifest.json"),
                    "paid_video_generation_requests": 0,
                },
                "effects_plan": {"enabled": True},
                "subtitle_strategy": "no subtitles",
                "subtitle_plan": {"enabled": False},
                "script_pacing": {"status": "ok"},
                "shots": [],
            }
            (project / "generation-plan.json").write_text(json.dumps(plan), encoding="utf-8")
            (project / "preflight-report.json").write_text(json.dumps({
                "ok": True,
                "execution_route": "postproduction_only",
                "paid_generation_allowed": False,
                "expected_paid_requests": 0,
                "plan_digest": canonical_digest(plan),
            }), encoding="utf-8")
            visual = {
                "status": "pass",
                "identity_consistent": True,
                "outfit_consistent": True,
                "scene_consistent": True,
                "framing_consistent": True,
                "lip_sync_acceptable": True,
                "mouth_visible": True,
                "subtitle_safe": True,
                "subtitle_readable": True,
                "subtitle_matches_speech": True,
                "no_unapproved_visual_insert": True,
                "no_generated_text": True,
                "spoken_content_complete": True,
                "reviewed_frames": ["frame.jpg"],
                "reviewed_video": {"path": "", "sha256": ""},
                "speech_evidence": {
                    "status": "pass",
                    "method": "human_test_review",
                    "transcript": "speech.txt",
                    "segments_reviewed": ["source_video"],
                    "pronunciation_acceptable": True,
                    "voice_consistent": True,
                    "volume_consistent": True,
                    "unresolved_discrepancies": [],
                },
            }
            (project / "frame.jpg").write_bytes(b"frame")
            (project / "speech.txt").write_text("spoken content", encoding="utf-8")
            visual_path = project / "visual-review.json"
            visual_path.write_text(json.dumps(visual), encoding="utf-8")
            edit_manifest_path = project / "postproduction-manifest.json"
            edit_manifest_path.write_text(json.dumps({
                "status": "pass",
                "source_video_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                "preserve_source_speech": True,
                "all_operations_user_approved": True,
                "caption_mask_applied": False,
                "operations": [{"type": "title_card", "status": "applied"}],
            }), encoding="utf-8")

            first = run_command([
                "python3", str(SCRIPTS / "workflow_engine.py"),
                "--project-dir", str(project),
                "finalize",
            ], expect_success=False)
            self.assertIn("unchanged", first.stdout.lower())

            subprocess.run([
                "ffmpeg", "-y", "-i", str(source),
                "-vf", "drawbox=x=0:y=0:w=120:h=40:color=black@0.8:t=fill",
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy", str(candidate),
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            edit_manifest = json.loads(edit_manifest_path.read_text(encoding="utf-8"))
            edit_manifest["candidate_sha256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
            edit_manifest_path.write_text(json.dumps(edit_manifest), encoding="utf-8")

            second = run_command([
                "python3", str(SCRIPTS / "workflow_engine.py"),
                "--project-dir", str(project),
                "finalize",
            ], expect_success=False)
            self.assertIn("reviewed video", second.stdout.lower())
            visual["reviewed_video"] = {
                "path": str(candidate),
                "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
            }
            visual_path.write_text(json.dumps(visual), encoding="utf-8")

            result = run_command([
                "python3", str(SCRIPTS / "workflow_engine.py"),
                "--project-dir", str(project),
                "finalize",
            ])
            delivery = json.loads(result.stdout)
            self.assertEqual(delivery["status"], "pass")
            self.assertEqual(delivery["execution_route"], "postproduction_only")
            self.assertEqual(delivery["paid_submission_attempts"], 0)
            self.assertEqual(delivery["artifact_hashes"]["source_video"]["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(delivery["artifact_hashes"]["final_video"]["sha256"], hashlib.sha256(candidate.read_bytes()).hexdigest())
            self.assertEqual(delivery["artifact_hashes"]["postproduction_manifest"]["sha256"], hashlib.sha256(edit_manifest_path.read_bytes()).hexdigest())
            self.assertEqual(delivery["artifact_hashes"]["reviewed_frames"][0]["sha256"], hashlib.sha256((project / "frame.jpg").read_bytes()).hexdigest())
            self.assertEqual(delivery["artifact_hashes"]["speech_transcript"]["sha256"], hashlib.sha256((project / "speech.txt").read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
