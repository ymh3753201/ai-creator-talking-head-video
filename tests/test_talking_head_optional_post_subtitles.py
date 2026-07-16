#!/usr/bin/env python3
"""Regression tests for user-confirmed postproduction subtitles."""

from __future__ import annotations

import inspect
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "ai-creator-talking-head-video"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

from finalize_postproduction import validate_postproduction_operations  # noqa: E402
from finalize_project import visual_review_errors  # noqa: E402
from generate_video import build_payload  # noqa: E402
from prepare_project import build_segment_prompt, build_subtitle_plan  # noqa: E402
from review_render import collect_subtitle_delivery  # noqa: E402
from validate_project import validate_plan  # noqa: E402


def minimal_plan(subtitle_plan: dict) -> dict:
    effects = {"enabled": False, "choice": "disabled", "caption_mask_allowed": False}
    return {
        "project_name": "optional-post-subtitles",
        "project_dir": "/tmp/optional-post-subtitles",
        "model_key": "test-model",
        "content_mode": "avatar_talking_head",
        "platform": "douyin",
        "language": "zh",
        "total_duration_seconds": 15,
        "delivery_duration_seconds": 15,
        "duration_plan": {"confirmation_status": "confirmed", "delivery_fit_status": "ok"},
        "duration_plan_digest": "a" * 64,
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "execution_route": "video_generation",
        "intake_route": {"desired_output": "new_avatar_video", "speech_source": "generated_dialogue", "timing_authority": "script_and_target_duration"},
        "business_context": {},
        "source_fact_map": [],
        "localization_contract": {"enabled": False},
        "postproduction_plan": {"enabled": False},
        "avatar_plan": {"needs_generated_avatar_reference": False},
        "script_file": "",
        "script_text": "这是一段经过确认的字幕测试口播。",
        "script_pacing": {"status": "ok"},
        "broll_plan": {"entries": []},
        "effects_plan": effects,
        "creative_choices": {"subtitle": subtitle_plan, "effects": effects},
        "subtitle_strategy": subtitle_plan.get("strategy", ""),
        "subtitle_plan": subtitle_plan,
        "visual_bible": {"continuity_priority": "same_avatar_same_scene_same_style"},
        "visual_asset_strategy": "single_source_frame",
        "image_consistency_plan": {"strategy": "single_source_frame"},
        "longform_generation_strategy": {"segment_count": 1},
        "stitching_plan": {"required": False},
        "confirmed_assets": [],
        "shots": [],
    }


class TalkingHeadOptionalPostSubtitleTests(unittest.TestCase):
    @staticmethod
    def create_test_video(path: Path) -> None:
        if not shutil.which("ffmpeg"):
            raise unittest.SkipTest("ffmpeg is not installed")
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=640x360:d=1",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(path),
            ],
            check=True,
        )

    def test_enabled_subtitle_plan_requires_explicit_plan_confirmation_source(self):
        signature = inspect.signature(build_subtitle_plan)
        self.assertIn("request_source", signature.parameters)

        confirmed = build_subtitle_plan(
            Path("/tmp/optional-subtitles"),
            None,
            "platform-safe postproduction captions",
            "zh",
            "9:16",
            choice="enabled",
            request_source="user_plan_confirmation",
            platform="douyin",
        )

        self.assertTrue(confirmed["enabled"])
        self.assertEqual(confirmed["choice"], "enabled")
        self.assertEqual(confirmed["confirmation_status"], "confirmed")
        self.assertEqual(confirmed["request_source"], "user_plan_confirmation")
        self.assertEqual(confirmed["provider_policy"], "never_send")
        self.assertEqual(confirmed["render_policy"], "postproduction_burn_only")
        self.assertTrue(confirmed["srt_output"].endswith("subtitles/final.srt"))
        self.assertTrue(confirmed["burned_video_output"].endswith("final.captioned.mp4"))
        self.assertTrue(confirmed["clean_video_output"].endswith("final.clean.mp4"))

    def test_disabled_remains_default_and_creates_no_subtitle_outputs(self):
        plan = build_subtitle_plan(
            Path("/tmp/no-subtitles"),
            None,
            "",
            "zh",
            "16:9",
            choice="disabled",
        )

        self.assertFalse(plan["enabled"])
        self.assertEqual(plan["choice"], "disabled")
        self.assertEqual(plan.get("request_source"), "default")
        self.assertEqual(plan.get("render_policy"), "none")
        self.assertEqual(plan["srt_output"], "")
        self.assertEqual(plan["burned_video_output"], "")

    def test_enabled_plan_is_valid_only_with_user_plan_confirmation(self):
        enabled = {
            "enabled": True,
            "choice": "enabled",
            "confirmation_status": "confirmed",
            "request_source": "user_plan_confirmation",
            "provider_policy": "never_send",
            "render_policy": "postproduction_burn_only",
            "profile": {"id": "vertical_social"},
            "srt_output": "/tmp/optional-post-subtitles/subtitles/final.srt",
            "burned_video_output": "/tmp/optional-post-subtitles/final.captioned.mp4",
            "clean_video_output": "/tmp/optional-post-subtitles/final.clean.mp4",
        }

        errors, _warnings = validate_plan(minimal_plan(enabled))

        self.assertFalse(any("subtitles are disabled" in item for item in errors), errors)
        self.assertFalse(any("fixed zero-subtitle" in item for item in errors), errors)

        unconfirmed = {**enabled, "request_source": "default"}
        errors, _warnings = validate_plan(minimal_plan(unconfirmed))
        self.assertTrue(any("user_plan_confirmation" in item for item in errors), errors)

    def test_platform_profile_template_has_distinct_vertical_and_horizontal_safe_zones(self):
        path = SKILL / "assets" / "templates" / "subtitle-style-profiles.example.json"
        self.assertTrue(path.exists(), path)
        data = json.loads(path.read_text(encoding="utf-8"))
        vertical = data["profiles"]["vertical_social"]
        horizontal = data["profiles"]["youtube_horizontal"]

        self.assertEqual(vertical["aspect_ratio"], "9:16")
        self.assertEqual(horizontal["aspect_ratio"], "16:9")
        self.assertGreater(vertical["margin_bottom_ratio"], horizontal["margin_bottom_ratio"])
        self.assertGreater(vertical["margin_right_ratio"], horizontal["margin_right_ratio"])
        self.assertEqual(vertical["max_lines"], 2)
        self.assertEqual(horizontal["max_lines"], 2)

    def test_ass_style_converts_target_pixels_into_libass_script_coordinates(self):
        from subtitle_profiles import build_ass_style, resolve_subtitle_profile

        style = build_ass_style(resolve_subtitle_profile("youtube", "16:9"), 1280, 720)
        fields = dict(item.split("=", 1) for item in style.split(","))

        # libass renders SRT in a 384x288 script space. These values target
        # roughly 36px type, 2px outline and a 65px bottom margin at 1280x720.
        self.assertGreaterEqual(int(fields["FontSize"]), 13)
        self.assertLessEqual(int(fields["FontSize"]), 15)
        self.assertEqual(int(fields["Outline"]), 1)
        self.assertGreaterEqual(int(fields["MarginV"]), 25)
        self.assertLessEqual(int(fields["MarginV"]), 27)

    def test_provider_prompt_and_payload_stay_text_free_when_post_subtitles_enabled(self):
        prompt = build_segment_prompt(
            "同一位数字人在工作室自然口播。",
            "这是一段完整口播。",
            "这是一段完整口播。",
            1,
            1,
            15,
            "complete message",
            {"broll_rule": "Do not insert B-roll or cutaway images."},
            {"estimated_spoken_seconds": 12.0, "head_padding_seconds": 0.4},
        )
        plan = {
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "confirmed_assets": [],
            "generation_requirements": {},
            "subtitle_plan": {
                "enabled": True,
                "request_source": "user_plan_confirmation",
                "confirmation_status": "confirmed",
                "provider_policy": "never_send",
                "render_policy": "postproduction_burn_only",
            },
            "warnings": [],
        }
        shot = {"id": "shot_01", "duration_seconds": 15, "prompt": prompt}
        model = {"model": "test-model", "supports_image_to_video": False, "supports_audio_input": False, "subtitle_field": "subtitle_url"}

        payload, trace = build_payload(plan, shot, model)

        self.assertIn("free of any written or typographic element", payload["prompt"])
        self.assertNotIn("subtitle_url", payload)
        self.assertFalse(trace["subtitle_included_in_payload"])
        self.assertEqual(trace["subtitle_policy"], "never_send_to_provider_postproduction_only")

    def test_confirmed_postproduction_subtitle_burn_is_allowed_but_provider_text_is_not(self):
        plan = {
            "subtitle_plan": {
                "enabled": True,
                "request_source": "user_plan_confirmation",
                "confirmation_status": "confirmed",
                "provider_policy": "never_send",
                "render_policy": "postproduction_burn_only",
            },
            "effects_plan": {"enabled": False},
        }
        manifest = {
            "all_operations_user_approved": True,
            "caption_mask_applied": False,
            "operations": [{"type": "postproduction_subtitle_burn", "status": "applied", "paid_api_call": False}],
        }

        errors = validate_postproduction_operations(plan, manifest)

        self.assertEqual(errors, [])

    def test_captioned_visual_review_requires_postproduction_origin_and_no_unapproved_text(self):
        review = {
            "status": "pass",
            "identity_consistent": True,
            "outfit_consistent": True,
            "scene_consistent": True,
            "framing_consistent": True,
            "lip_sync_acceptable": True,
            "mouth_visible": True,
            "no_unapproved_visual_insert": True,
            "no_generated_text": True,
            "spoken_content_complete": True,
            "subtitle_safe": True,
            "subtitle_readable": True,
            "subtitle_matches_speech": True,
            "subtitle_background_absent": True,
        }

        errors = visual_review_errors(review, subtitles_enabled=True)

        self.assertTrue(any("subtitle_postproduced" in item for item in errors), errors)
        self.assertTrue(any("subtitle_present" in item for item in errors), errors)
        self.assertTrue(any("no_unapproved_text" in item for item in errors), errors)

    def test_runtime_preflight_blocks_local_transcription_without_a_model(self):
        runtime_path = SCRIPTS / "subtitle_runtime.py"
        self.assertTrue(runtime_path.exists(), runtime_path)
        from subtitle_runtime import subtitle_runtime_errors

        plan = {
            "subtitle_plan": {
                "enabled": True,
                "request_source": "user_plan_confirmation",
                "confirmation_status": "confirmed",
                "provider_policy": "never_send",
                "render_policy": "postproduction_burn_only",
                "timing_source": "local_whisper_cpp",
                "whisper_model": "/tmp/definitely-missing-whisper-model.bin",
            }
        }
        errors = subtitle_runtime_errors(plan)
        self.assertTrue(any("Whisper model" in item for item in errors), errors)

    def test_generate_subtitles_accepts_confirmed_provided_srt_without_whisper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "clean.mp4"
            self.create_test_video(video)
            supplied = root / "supplied.srt"
            supplied.write_text("1\n00:00:00,000 --> 00:00:00,800\n你好\n", encoding="utf-8")
            output = root / "subtitles" / "final.srt"
            audit = root / "subtitles" / "final.audit.json"
            plan = {
                "language": "zh",
                "subtitle_plan": {
                    "enabled": True,
                    "request_source": "user_plan_confirmation",
                    "confirmation_status": "confirmed",
                    "provider_policy": "never_send",
                    "render_policy": "postproduction_burn_only",
                    "timing_source": "provided_srt",
                    "input_subtitle": {"value": str(supplied)},
                    "srt_output": str(output),
                    "subtitle_audit_output": str(audit),
                },
            }
            plan_path = root / "generation-plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

            result = subprocess.run(
                [
                    "python3", str(SCRIPTS / "generate_subtitles.py"),
                    "--plan", str(plan_path), "--video", str(video),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("你好", output.read_text(encoding="utf-8"))
            self.assertTrue(audit.exists())
            self.assertEqual(json.loads(audit.read_text(encoding="utf-8"))["timing_source"], "provided_srt")

    def test_subtitle_normalization_enforces_profile_line_count_and_length(self):
        from generate_subtitles import normalize_srt_for_profile

        source = "1\n00:00:00,000 --> 00:00:04,000\n这是一段非常长的中文字幕用于验证平台安全换行规则\n"
        normalized = normalize_srt_for_profile(
            source,
            {"max_chars_zh_per_line": 8, "max_chars_latin_per_line": 16, "max_lines": 2},
        )
        blocks = [block for block in normalized.strip().split("\n\n") if block.strip()]
        self.assertGreaterEqual(len(blocks), 2)
        for block in blocks:
            lines = block.splitlines()[2:]
            self.assertLessEqual(len(lines), 2)
            self.assertTrue(all(len(line) <= 8 for line in lines), lines)

    def test_local_asr_tail_timestamp_can_be_clamped_to_exact_video_duration(self):
        from generate_subtitles import clamp_srt_to_duration, last_srt_end_seconds

        source = "1\n00:00:00,000 --> 00:00:01,533\n最后一句\n"
        clamped = clamp_srt_to_duration(source, 1.0)
        self.assertEqual(last_srt_end_seconds(clamped), 1.0)
        self.assertIn("最后一句", clamped)

    def test_confirmed_script_can_supply_caption_words_while_final_audio_supplies_timing(self):
        from generate_subtitles import confirmed_script_srt, last_srt_end_seconds

        text = confirmed_script_srt(
            "职场人和企业管理者注意了！现在不用精通编程。",
            start_second=0.2,
            end_second=3.8,
            profile={"max_chars_zh_per_line": 8, "max_chars_latin_per_line": 16, "max_lines": 2},
        )
        self.assertIn("企业管理者", text.replace("\n", ""))
        self.assertNotIn("实验观音者", text)
        self.assertEqual(last_srt_end_seconds(text), 3.8)

    def test_confirmed_script_uses_matching_local_audio_cue_windows(self):
        from generate_subtitles import confirmed_script_srt

        text = confirmed_script_srt(
            "第一句。第二句。",
            start_second=0.2,
            end_second=2.2,
            profile={"max_chars_zh_per_line": 6, "max_chars_latin_per_line": 16, "max_lines": 2},
            timing_entries=[
                {"start": 0.2, "end": 1.1, "text": "错误一"},
                {"start": 1.4, "end": 2.2, "text": "错误二"},
            ],
        )

        self.assertIn("00:00:00,200 --> 00:00:01,100", text)
        self.assertIn("00:00:01,400 --> 00:00:02,200", text)
        self.assertIn("第一句。", text)
        self.assertIn("第二句。", text)

    def test_burn_subtitles_dry_run_uses_confirmed_platform_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "clean.mp4"
            self.create_test_video(video)
            srt = root / "final.srt"
            srt.write_text("1\n00:00:00,000 --> 00:00:00,800\n平台安全字幕\n", encoding="utf-8")
            output = root / "captioned.mp4"
            subtitle_plan = build_subtitle_plan(
                root,
                {"value": str(srt)},
                "",
                "zh",
                "16:9",
                choice="enabled",
                request_source="user_plan_confirmation",
                platform="youtube",
            )
            plan_path = root / "generation-plan.json"
            plan_path.write_text(json.dumps({"subtitle_plan": subtitle_plan}, ensure_ascii=False), encoding="utf-8")

            result = subprocess.run(
                [
                    "python3", str(SCRIPTS / "burn_subtitles.py"),
                    "--plan", str(plan_path), "--video", str(video),
                    "--srt", str(srt), "--output", str(output), "--dry-run",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            record = json.loads(result.stdout)
            self.assertEqual(record["profile_id"], "youtube_horizontal")
            self.assertIn("subtitles=", " ".join(record["command"]))

    def test_delivery_review_requires_only_confirmed_postproduced_subtitles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            burned = root / "final.captioned.mp4"
            srt = root / "subtitles" / "final.srt"
            plan = {
                "subtitle_plan": {
                    "enabled": True,
                    "request_source": "user_plan_confirmation",
                    "confirmation_status": "confirmed",
                    "provider_policy": "never_send",
                    "render_policy": "postproduction_burn_only",
                    "srt_output": str(srt),
                    "burned_video_output": str(burned),
                }
            }

            missing = collect_subtitle_delivery(root, burned, plan)
            self.assertTrue(missing["required"])
            self.assertTrue(missing["missing"])

            burned.write_bytes(b"captioned-video")
            srt.parent.mkdir(parents=True)
            srt.write_text("1\n00:00:00,000 --> 00:00:00,500\n测试\n", encoding="utf-8")
            present = collect_subtitle_delivery(root, burned, plan)
            self.assertFalse(present["missing"])
            self.assertEqual(present["policy"], "confirmed_postproduction_burn_only")

    def test_subtitle_only_existing_video_route_can_use_source_as_clean_candidate(self):
        from finalize_postproduction import candidate_must_differ_from_source

        confirmed = {
            "subtitle_plan": {
                "enabled": True,
                "request_source": "user_plan_confirmation",
                "confirmation_status": "confirmed",
                "provider_policy": "never_send",
                "render_policy": "postproduction_burn_only",
            },
            "effects_plan": {"enabled": False},
        }
        self.assertFalse(candidate_must_differ_from_source(confirmed))
        self.assertTrue(candidate_must_differ_from_source({"subtitle_plan": {"enabled": False}}))

    def test_unconfirmed_subtitle_opt_in_marks_project_not_ready_for_paid_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"offline-avatar")
            result = subprocess.run(
                [
                    "python3", str(SCRIPTS / "prepare_project.py"),
                    "--name", "pending-subtitles",
                    "--project-root", str(root / "projects"),
                    "--content-mode", "avatar_talking_head",
                    "--platform", "douyin",
                    "--duration", "15",
                    "--avatar-reference", str(avatar),
                    "--script-text", "这是一段已确认时长但尚未确认字幕选择的完整中文口播脚本，用于本地预检。",
                    "--subtitle-choice", "enabled",
                    "--effects-choice", "disabled",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            plan_path = Path(json.loads(result.stdout)["plan"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertFalse(plan["ready_for_paid_generation"])
            self.assertTrue(any("user_plan_confirmation" in item for item in plan["blocking_reasons"]), plan["blocking_reasons"])

    def test_skill_docs_define_default_disabled_and_first_confirmation_opt_in(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        proposal = (SKILL / "references" / "proposal-template.md").read_text(encoding="utf-8")
        subtitle = (SKILL / "references" / "subtitles-and-safe-layout.md").read_text(encoding="utf-8")
        combined = "\n".join((skill, proposal, subtitle))

        self.assertIn("user_plan_confirmation", combined)
        self.assertIn("postproduction_burn_only", combined)
        self.assertIn("default disabled", combined.lower())
        self.assertIn("确认方案，需要字幕", combined)
        self.assertIn("Provider payload", combined)
        self.assertIn("lexical_source=confirmed_script", combined)
        self.assertIn("libass script coordinates", combined)


if __name__ == "__main__":
    unittest.main()
