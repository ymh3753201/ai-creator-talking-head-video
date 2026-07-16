#!/usr/bin/env python3
"""Regression tests for the default no-subtitle and Provider no-text policy."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "ai-creator-talking-head-video"
SCRIPTS = SKILL / "scripts"
CONFIG = SKILL / "assets" / "templates" / "model-config.example.json"
sys.path.insert(0, str(SCRIPTS))

from generate_video import build_payload  # noqa: E402
from prepare_project import build_segment_prompt, build_subtitle_plan  # noqa: E402
from validate_project import validate_plan  # noqa: E402


class TalkingHeadNoSubtitlePolicyTests(unittest.TestCase):
    def test_prepare_and_preflight_keep_default_disabled_delivery_subtitle_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"offline-avatar")
            env = os.environ.copy()
            for key in list(env):
                if key.endswith("API_KEY") or key in {"FAL_KEY", "YUNWU_API_KEY", "XAI_API_KEY"}:
                    env.pop(key, None)
            env["AI_CREATOR_TALKING_HEAD_VIDEO_ENV_FILE"] = str(root / "missing.env")
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            prepared = subprocess.run(
                [
                    "python3", str(SCRIPTS / "prepare_project.py"),
                    "--name", "zero-subtitle-integration",
                    "--project-root", str(root / "projects"),
                    "--content-mode", "avatar_talking_head",
                    "--platform", "douyin",
                    "--duration", "15",
                    "--avatar-reference", str(avatar),
                    "--script-text", "今天用一个清晰方法说明人工智能工具如何减少重复工作并帮助团队记录真实结果形成可复用的检查流程。",
                    "--subtitle-choice", "disabled",
                    "--effects-choice", "disabled",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            plan_path = Path(json.loads(prepared.stdout)["plan"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertFalse(plan["subtitle_plan"]["enabled"])
            self.assertEqual(plan["subtitle_plan"]["choice"], "disabled")
            self.assertNotIn("Add user-confirmed subtitles", plan["shots"][0]["prompt"])

            preflight = subprocess.run(
                [
                    "python3", str(SCRIPTS / "preflight_project.py"),
                    "--plan", str(plan_path),
                    "--config", str(CONFIG),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            report = json.loads(preflight.stdout)
            self.assertTrue(report["ok"])
            dry_run = json.loads((plan_path.parent / "requests" / "dry-run" / "shot_01.json").read_text(encoding="utf-8"))
            self.assertFalse(dry_run["asset_trace"]["subtitle_included_in_payload"])
            self.assertEqual(dry_run["asset_trace"]["subtitle_policy"], "never_send_to_provider_postproduction_only")
            self.assertFalse(any("subtitle" in key.lower() for key in dry_run["payload"] if key != "prompt"))

    def test_finalize_blocks_legacy_enabled_plan_before_any_caption_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "generation-plan.json").write_text(
                json.dumps({"subtitle_plan": {"enabled": True}}, ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                ["python3", str(SCRIPTS / "finalize_project.py"), "--project-dir", str(project)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("user-confirmed postproduction-only subtitle plan", result.stdout)
            self.assertFalse((project / "subtitles").exists())
            self.assertFalse((project / "final.subtitled.mp4").exists())

    def test_legacy_subtitle_clis_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "generation-plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "subtitle_plan": {"enabled": False},
                        "shots": [{"duration_seconds": 4, "script_segment": "不应生成字幕。"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            srt_output = root / "forbidden.srt"
            generated = subprocess.run(
                [
                    "python3", str(SCRIPTS / "generate_subtitles.py"),
                    "--plan", str(plan),
                    "--video", str(root / "missing.mp4"),
                    "--output", str(srt_output),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertNotEqual(generated.returncode, 0)
            self.assertIn("subtitles are disabled", generated.stdout.lower())
            self.assertFalse(srt_output.exists())

            video = root / "input.mp4"
            srt = root / "input.srt"
            output = root / "forbidden.mp4"
            video.write_bytes(b"not-a-real-video")
            srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕\n", encoding="utf-8")
            burned = subprocess.run(
                [
                    "python3", str(SCRIPTS / "burn_subtitles.py"),
                    "--plan", str(plan),
                    "--video", str(video),
                    "--srt", str(srt),
                    "--output", str(output),
                    "--dry-run",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertNotEqual(burned.returncode, 0)
            self.assertIn("subtitles are disabled", burned.stdout.lower())
            self.assertFalse(output.exists())

    def test_segment_prompt_has_one_unambiguous_zero_text_contract(self):
        prompt = build_segment_prompt(
            "同一位数字人在工作室自然口播。",
            "这是一段完整口播。",
            "这是一段完整口播。",
            1,
            1,
            15,
            "complete message",
            {"broll_rule": "Do not insert B-roll or cutaway images."},
            {
                "minimum_recommended_spoken_seconds": 13.5,
                "maximum_recommended_spoken_seconds": 14.2,
                "estimated_spoken_seconds": 13.8,
                "head_padding_seconds": 0.4,
            },
        )

        self.assertNotIn("Add user-confirmed subtitles", prompt)
        self.assertIn("Spoken dialogue must remain audio only", prompt)
        self.assertIn("free of any written or typographic element", prompt)
        for forbidden_kind in (
            "subtitles",
            "captions",
            "lower thirds",
            "title cards",
            "speech bubbles",
            "letters",
            "numbers",
            "punctuation",
            "logos",
            "watermarks",
        ):
            self.assertIn(forbidden_kind, prompt)

    def test_unconfirmed_enabled_request_is_pending_and_cannot_render(self):
        plan = build_subtitle_plan(
            Path("/tmp/no-subtitles"),
            None,
            "white captions with outline",
            "zh",
            "9:16",
            choice="enabled",
        )

        self.assertTrue(plan["enabled"])
        self.assertEqual(plan["choice"], "enabled")
        self.assertEqual(plan["confirmation_status"], "pending")
        self.assertTrue(plan["requires_user_confirmation"])
        self.assertEqual(plan["request_source"], "default")
        self.assertEqual(plan["render_policy"], "postproduction_burn_only")

    def test_video_payload_never_sends_a_subtitle_asset_to_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            subtitle = Path(tmp) / "provided.srt"
            subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\n测试字幕\n", encoding="utf-8")
            plan = {
                "aspect_ratio": "9:16",
                "resolution": "720p",
                "confirmed_assets": [],
                "generation_requirements": {},
                "subtitle_file": {"id": "subtitle", "role": "subtitle", "kind": "file", "value": str(subtitle)},
                "warnings": [],
            }
            shot = {"id": "shot_01", "duration_seconds": 15, "prompt": "clean talking-head video"}
            model = {
                "model": "test-model",
                "supports_image_to_video": False,
                "supports_audio_input": False,
                "subtitle_field": "subtitle_url",
                "subtitle_payload_format": "url_string",
            }

            payload, trace = build_payload(plan, shot, model)

            self.assertNotIn("subtitle_url", payload)
            self.assertFalse(trace["subtitle_included_in_payload"])
            self.assertEqual(trace["subtitle_policy"], "never_send_to_provider_postproduction_only")

    def test_validator_rejects_legacy_enabled_subtitle_plan(self):
        plan = {
            "project_name": "legacy-subtitle-plan",
            "project_dir": "/tmp/legacy-subtitle-plan",
            "model_key": "test-model",
            "content_mode": "avatar_talking_head",
            "platform": "douyin",
            "language": "zh",
            "total_duration_seconds": 15,
            "delivery_duration_seconds": 15,
            "duration_plan": {"confirmation_status": "confirmed", "delivery_fit_status": "ok"},
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "subtitle_strategy": "bottom captions",
            "subtitle_plan": {"enabled": True, "choice": "enabled", "background_policy": "none"},
            "effects_plan": {"enabled": False, "choice": "disabled", "caption_mask_allowed": False},
            "creative_choices": {
                "subtitle": {"enabled": True, "choice": "enabled"},
                "effects": {"enabled": False, "choice": "disabled", "caption_mask_allowed": False},
            },
            "script_pacing": {"status": "ok"},
            "confirmed_assets": [],
            "shots": [],
        }

        errors, _warnings = validate_plan(plan)

        self.assertTrue(any("request_source=user_plan_confirmation" in item for item in errors), errors)

    def test_policy_docs_define_default_disabled_and_confirmed_local_burn(self):
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        proposal_text = (SKILL / "references" / "proposal-template.md").read_text(encoding="utf-8")
        subtitle_text = (SKILL / "references" / "subtitles-and-safe-layout.md").read_text(encoding="utf-8")
        combined = "\n".join((skill_text, proposal_text, subtitle_text))

        self.assertIn("fixed zero-text Provider policy", combined)
        self.assertIn("postproduction_burn_only", combined)
        self.assertIn("确认方案，需要字幕", combined)
        self.assertIn("## 8. 字幕选择", proposal_text)


if __name__ == "__main__":
    unittest.main()
