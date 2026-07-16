#!/usr/bin/env python3
"""Offline validation for the ai-creator-talking-head-video skill."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "ai-creator-talking-head-video"
SCRIPTS = SKILL / "scripts"
CONFIG = SKILL / "assets" / "templates" / "model-config.example.json"
QUICK_VALIDATE_CANDIDATES = (
    Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex"))) / "skills" / ".system" / "skill-creator" / "scripts" / "quick_validate.py",
    Path.home() / ".agents" / "skills" / "skill-creator" / "scripts" / "quick_validate.py",
)
QUICK_VALIDATE = next((path for path in QUICK_VALIDATE_CANDIDATES if path.is_file()), None)


ENV_KEYS = {
    "AI_CREATOR_TALKING_HEAD_VIDEO_API_KEY",
    "AI_TALKING_HEAD_VIDEO_API_KEY",
    "AI_CREATOR_TALKING_HEAD_VIDEO_BASE_URL",
    "AI_CREATOR_TALKING_HEAD_VIDEO_MODEL",
    "AI_CREATOR_TALKING_HEAD_VIDEO_ENV_FILE",
    "YUNWU_API_KEY",
    "XAI_API_KEY",
    "FAL_KEY",
}

READY_10S_SCRIPT = "先说明多参考图作用再展示同一个数字人同一场景同一镜头风格如何稳定进入视频模型并保持画面一致。"
READY_SEGMENT_1 = "开场先说明问题不是工具少而是主题没有帮观众判断价值我们会用一个标准同时看来源场景成本变化和风险边界帮助观众继续看并明确下一步行动路径。"
READY_SEGMENT_2 = "第二段重点讲清具体判断方法先看来源是否可靠再看产品入口是否明确看这个变化能否节省时间降低成本或把重复工作变成标准流程并形成复用检查清单。"
READY_SEGMENT_3 = "最后给出行动建议团队不要只看热度而要记录前后耗时失败原因和真实反馈下次看到人工智能热点先判断价值再决定要不要测试减少预算浪费和内容误判。"
READY_SEGMENT_4 = "收尾时提醒观众把这套标准保存下来下次遇到新工具新模型或新政策先用同一张表做判断这样内容既能保持专业也能避免跟风方便复盘每次选择是否有效。"
READY_15S_SCRIPT = READY_SEGMENT_1
READY_30S_SCRIPT = READY_SEGMENT_1 + READY_SEGMENT_2
READY_45S_SCRIPT = READY_SEGMENT_1 + READY_SEGMENT_2 + READY_SEGMENT_3
READY_60S_SCRIPT_WITH_PADDING = READY_SEGMENT_1 + (" " * 1000) + READY_SEGMENT_2 + READY_SEGMENT_3 + READY_SEGMENT_4


def with_confirmed_creative_choices(args):
    values = [str(item) for item in args]
    if not any(Path(value).name == "prepare_project.py" for value in values):
        return args
    result = list(args)
    if "--subtitle-choice" not in values:
        result.extend(["--subtitle-choice", "disabled"])
    if "--effects-choice" not in values:
        result.extend(["--effects-choice", "enabled" if "--broll-plan" in values else "disabled"])
    return result


def run_cmd(args, cwd=ROOT, env=None):
    args = with_confirmed_creative_choices(args)
    full_env = os.environ.copy()
    for key in list(full_env):
        if key in ENV_KEYS or key.startswith("AI_CREATOR_TALKING_HEAD_VIDEO_MODEL_"):
            full_env.pop(key, None)
    full_env["AI_CREATOR_TALKING_HEAD_VIDEO_ENV_FILE"] = str(ROOT / ".nonexistent-talking-head-test-env")
    full_env["PYTHONDONTWRITEBYTECODE"] = "1"
    if env:
        full_env.update(env)
    result = subprocess.run(args, cwd=cwd, env=full_env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise AssertionError(f"Command failed: {' '.join(map(str, args))}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def run_cmd_fail(args, cwd=ROOT, env=None):
    args = with_confirmed_creative_choices(args)
    full_env = os.environ.copy()
    for key in list(full_env):
        if key in ENV_KEYS or key.startswith("AI_CREATOR_TALKING_HEAD_VIDEO_MODEL_"):
            full_env.pop(key, None)
    full_env["AI_CREATOR_TALKING_HEAD_VIDEO_ENV_FILE"] = str(ROOT / ".nonexistent-talking-head-test-env")
    full_env["PYTHONDONTWRITEBYTECODE"] = "1"
    if env:
        full_env.update(env)
    result = subprocess.run(args, cwd=cwd, env=full_env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode == 0:
        raise AssertionError(f"Command unexpectedly passed: {' '.join(map(str, args))}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


class TalkingHeadSkillValidationTests(unittest.TestCase):
    def test_required_files_exist(self):
        expected = [
            SKILL / "SKILL.md",
            SKILL / "references" / "workflow.md",
            SKILL / "references" / "content-modes.md",
            SKILL / "references" / "business-scenarios.md",
            SKILL / "references" / "platform-styles.md",
            SKILL / "references" / "script-frameworks.md",
            SKILL / "references" / "script-duration-and-pacing.md",
            SKILL / "references" / "viral-teardown.md",
            SKILL / "references" / "avatar-and-scene.md",
            SKILL / "references" / "b-roll-and-editing.md",
            SKILL / "references" / "post-generation-review.md",
            SKILL / "references" / "speech-acceptance.md",
            SKILL / "references" / "subtitles-and-safe-layout.md",
            SKILL / "references" / "model-capabilities.md",
            SKILL / "references" / "asset-consistency.md",
            SKILL / "references" / "proposal-template.md",
            SKILL / "references" / "quality-checklist.md",
            SKILL / "references" / "first-response-imagegen.md",
            SCRIPTS / "prepare_project.py",
            SCRIPTS / "validate_config.py",
            SCRIPTS / "generate_video.py",
            SCRIPTS / "poll_video.py",
            SCRIPTS / "stitch_clips.py",
            SCRIPTS / "review_render.py",
            SCRIPTS / "generate_subtitles.py",
            SCRIPTS / "burn_subtitles.py",
            SCRIPTS / "subtitle_policy.py",
            SCRIPTS / "analyze_script_timeline.py",
            SCRIPTS / "validate_project.py",
            SCRIPTS / "_workflow.py",
            SCRIPTS / "_routing.py",
            SCRIPTS / "preflight_project.py",
            SCRIPTS / "create_confirmation.py",
            SCRIPTS / "workflow_engine.py",
            SCRIPTS / "finalize_project.py",
            SCRIPTS / "finalize_postproduction.py",
            SCRIPTS / "validate_first_response_trace.py",
            SKILL / "assets" / "templates" / "model-config.example.json",
            SKILL / "assets" / "templates" / "project-brief.example.json",
            SKILL / "assets" / "templates" / "visual-review.example.json",
            SKILL / "assets" / "templates" / "postproduction-manifest.example.json",
            SKILL / "assets" / "templates" / "env.example",
            SKILL / "evals" / "evals.json",
            SKILL / "agents" / "openai.yaml",
        ]
        for path in expected:
            self.assertTrue(path.exists(), path)

    def test_quick_validate_passes(self):
        if QUICK_VALIDATE is None:
            self.skipTest("Codex skill-creator quick validator is not installed")
        result = run_cmd(["python3", str(QUICK_VALIDATE), str(SKILL)])
        self.assertIn("Skill is valid", result.stdout)

    def test_distribution_package_matches_current_skill_sources(self):
        package = ROOT / "dist" / "ai-creator-talking-head-video.skill"
        if not package.exists():
            self.skipTest("distribution package is created only for a release build")
        required = {
            "ai-creator-talking-head-video/LICENSE",
            "ai-creator-talking-head-video/scripts/_routing.py",
            "ai-creator-talking-head-video/scripts/_workflow.py",
            "ai-creator-talking-head-video/scripts/workflow_engine.py",
            "ai-creator-talking-head-video/scripts/preflight_project.py",
            "ai-creator-talking-head-video/scripts/finalize_project.py",
            "ai-creator-talking-head-video/scripts/finalize_postproduction.py",
            "ai-creator-talking-head-video/scripts/subtitle_policy.py",
            "ai-creator-talking-head-video/scripts/review_render.py",
            "ai-creator-talking-head-video/agents/openai.yaml",
            "ai-creator-talking-head-video/references/first-response-imagegen.md",
            "ai-creator-talking-head-video/references/speech-acceptance.md",
            "ai-creator-talking-head-video/assets/templates/visual-review.example.json",
        }
        with zipfile.ZipFile(package) as archive:
            names = {name for name in archive.namelist() if not name.endswith("/")}
            self.assertTrue(required.issubset(names), required - names)
            self.assertFalse(any(
                "__pycache__" in name
                or name.endswith(".pyc")
                or name.endswith("/.env")
                or "/projects/" in name
                or name.endswith((".mp4", ".wav"))
                for name in names
            ))
            for name in names:
                relative = Path(name).relative_to("ai-creator-talking-head-video")
                source = SKILL / relative
                self.assertTrue(source.exists(), source)
                self.assertEqual(archive.read(name), source.read_bytes(), name)

    def test_docs_cover_required_business_capabilities(self):
        docs = []
        for path in [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md"))]:
            docs.append(path.read_text(encoding="utf-8"))
        combined = "\n".join(docs)
        required_terms = [
            "选题策划",
            "爆款拆解",
            "脚本改写",
            "数字人口播",
            "B-roll",
            "字幕",
            "fixed zero-text Provider policy",
            "长视频",
            "exactly two user confirmations",
            "subtitle_included_in_payload=false",
            "effects choice",
            "postproduction_burn_only",
            "user_plan_confirmation",
            "model_output_only",
            "API keys",
            "supports_lipsync",
            "supports_audio_input",
            "external_audio_lipsync",
            "Do not force TTS",
            "visual_bible",
            "longform_generation_strategy",
            "stitching_plan",
            "image_consistency_plan",
            "script_pacing",
            "script_boundary",
            "review_render.py",
            "generate_subtitles.py",
            "burn_subtitles.py",
            "silencedetect",
            "freezedetect",
            "first_frame",
            "segment_source",
            "storyboard_sheet",
            "业务场景",
            "企业培训",
            "客户服务",
            "多语言本地化",
            "合规",
            "source_fact_map",
            "production-contract.json",
            "workflow_engine.py",
            "delivery-manifest.json",
            "Codex built-in image_gen",
            "validate_first_response_trace.py",
            "pass_with_notes",
            "speech_fidelity_mode",
            "critical_facts_exact",
            "material_discrepancies",
        ]
        for term in required_terms:
            self.assertIn(term, combined)
        self.assertIn("Do not default to e-commerce selling", combined)

    def test_first_delivery_uses_two_confirmation_stages(self):
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        workflow_text = (SKILL / "references" / "workflow.md").read_text(encoding="utf-8")
        proposal_text = (SKILL / "references" / "proposal-template.md").read_text(encoding="utf-8")
        avatar_text = (SKILL / "references" / "avatar-and-scene.md").read_text(encoding="utf-8")
        script_framework_text = (SKILL / "references" / "script-frameworks.md").read_text(encoding="utf-8")
        checklist_text = (SKILL / "references" / "quality-checklist.md").read_text(encoding="utf-8")

        required_markers = {
            "SKILL.md": (skill_text, [
                "proposal_delivered=true",
                "plan_confirmed=false",
                "image_assets_confirmed=false",
                "Codex built-in image_gen",
                "gpt-image-2",
                "professionally optimized final spoken script",
            ]),
            "workflow.md": (workflow_text, [
                "Plan Confirmation Gate",
                "Image Confirmation Gate",
                "complete proposal text",
                "Codex built-in image_gen",
            ]),
            "proposal-template.md": (proposal_text, [
                "素材与原脚本专业审查",
                "优化后的完整口播稿",
                "图片计划与确认说明",
            ]),
            "avatar-and-scene.md": (avatar_text, [
                "built-in imagegen",
                "video_payload",
                "only when the user explicitly enabled those effects",
            ]),
            "script-frameworks.md": (script_framework_text, [
                "only when effects are explicitly enabled",
            ]),
            "quality-checklist.md": (checklist_text, [
                "first assistant response contains the complete text proposal",
                "actual gpt-image-2 production images",
                "The optimized full spoken script",
            ]),
        }
        for filename, (text, markers) in required_markers.items():
            for marker in markers:
                self.assertIn(marker, text, f"{filename} missing {marker}")

        self.assertNotIn(
            "First analyze the request and generate only the necessary proposal images, then show one consolidated package",
            skill_text,
        )
        self.assertNotIn("请先确认文字方案，并授权", proposal_text)
        eval_data = json.loads((SKILL / "evals" / "evals.json").read_text(encoding="utf-8"))
        regression_eval = next((item for item in eval_data["evals"] if item.get("id") == 18), None)
        self.assertIsNotNone(regression_eval)
        self.assertIn("完整文字视频方案", regression_eval["prompt"])
        self.assertIn("The first response includes the complete text plan on the primary assistant response surface and does not call imagegen", regression_eval["expectations"])
        self.assertTrue(any("full professionally optimized verbatim script" in item for item in regression_eval["expectations"]))
        self.assertIn(
            "After plan confirmation, the next assistant response uses built-in gpt-image-2 for real video payload images and waits for image confirmation",
            regression_eval["expectations"],
        )
        self.assertEqual(regression_eval["files"], ["evals/fixtures/knowledge-product-material.json"])
        self.assertTrue((SKILL / regression_eval["files"][0]).exists())

    def test_cost_aware_graded_speech_acceptance_is_documented_and_evaluated(self):
        speech_policy = (SKILL / "references" / "speech-acceptance.md").read_text(encoding="utf-8")
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        workflow_text = (SKILL / "references" / "workflow.md").read_text(encoding="utf-8")
        for marker in (
            "semantic_tolerance",
            "critical_facts_exact",
            "verbatim_required",
            "pass_with_notes",
            "ASR uncertainty never authorizes paid regeneration",
            "repair_reserve=0",
            "per_shot_repair_limit=0",
        ):
            self.assertIn(marker, "\n".join((speech_policy, skill_text, workflow_text)), marker)

        eval_data = json.loads((SKILL / "evals" / "evals.json").read_text(encoding="utf-8"))
        regression_eval = next((item for item in eval_data["evals"] if item.get("id") == 21), None)
        self.assertIsNotNone(regression_eval)
        self.assertIn("多次 ASR", regression_eval["prompt"])
        self.assertTrue(any("pass_with_notes" in item for item in regression_eval["expectations"]))
        self.assertTrue(any("no paid regeneration" in item for item in regression_eval["expectations"]))

    def test_two_confirmation_contract_prevents_image_only_first_response(self):
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        workflow_text = (SKILL / "references" / "workflow.md").read_text(encoding="utf-8")
        proposal_text = (SKILL / "references" / "proposal-template.md").read_text(encoding="utf-8")
        orchestration_text = (SKILL / "references" / "first-response-imagegen.md").read_text(encoding="utf-8")

        combined = "\n".join((skill_text, workflow_text, proposal_text, orchestration_text))
        self.assertIn("TWO-CONFIRMATION CODEX IMAGEGEN CONTRACT", skill_text)
        self.assertIn("Codex built-in image_gen", skill_text)
        self.assertIn("gpt-image-2", skill_text)
        self.assertIn("图片计划与确认说明", proposal_text)
        self.assertNotIn("generate_production_images.py", combined)
        self.assertNotIn("image-model-config.example.json", combined)
        self.assertNotIn("AI_CREATOR_TALKING_HEAD_IMAGE_API_KEY", combined)
        self.assertNotIn("visual-board", combined)
        self.assertIn("Never generate a visual confirmation board", skill_text)
        self.assertIn("primary assistant response", orchestration_text)
        self.assertIn("stage=awaiting_plan_confirmation", orchestration_text)
        self.assertIn("stage=awaiting_image_confirmation", orchestration_text)
        self.assertIn("stage=production_authorized", orchestration_text)
        self.assertIn("proposal_delivered=true", orchestration_text)
        self.assertIn("plan_confirmed=false", orchestration_text)
        self.assertIn("image_assets_confirmed=false", orchestration_text)
        self.assertIn("paid_video_authorized=false", orchestration_text)
        self.assertIn("Do not call imagegen in Stage 1", orchestration_text)
        self.assertNotIn("Use a composite `functions.exec` response", orchestration_text)
        self.assertNotIn("text(proposal);", orchestration_text)

    def test_first_response_trace_rejects_tool_output_only_proposal(self):
        validator = SCRIPTS / "validate_first_response_trace.py"
        broken_trace = SKILL / "evals" / "fixtures" / "first-response-tool-output-only.json"
        result = subprocess.run(
            ["python3", str(validator), str(broken_trace)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("proposal_in_tool_output_only", result.stdout)
        self.assertIn("empty_final_after_image", result.stdout)

    def test_trace_accepts_two_confirmation_flow(self):
        validator = SCRIPTS / "validate_first_response_trace.py"
        valid_trace = SKILL / "evals" / "fixtures" / "two-confirmation-valid.json"
        result = run_cmd(["python3", str(validator), str(valid_trace)])
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["proposal_surface"], "primary_assistant_response")
        self.assertEqual(report["stages"], [
            "awaiting_plan_confirmation",
            "plan_confirmed",
            "awaiting_image_confirmation",
            "production_authorized",
        ])
        self.assertTrue(report["paid_video_authorized"])

    def test_trace_accepts_image_revision_when_only_latest_images_are_confirmed(self):
        validator = SCRIPTS / "validate_first_response_trace.py"
        valid_trace = SKILL / "evals" / "fixtures" / "two-confirmation-valid-image-revision.json"
        result = run_cmd(["python3", str(validator), str(valid_trace)])
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["confirmed_asset_digests"], ["b" * 64])

    def test_trace_rejects_duration_plan_digest_drift_between_confirmations(self):
        validator = SCRIPTS / "validate_first_response_trace.py"
        trace = json.loads((SKILL / "evals" / "fixtures" / "two-confirmation-valid.json").read_text(encoding="utf-8"))
        trace["events"][0]["duration_plan_digest"] = "a" * 64
        trace["events"][1]["confirmed_duration_plan_digest"] = "a" * 64
        trace["events"][3]["confirmed_duration_plan_digest"] = "b" * 64
        trace["events"][4]["duration_plan_digest"] = "a" * 64
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duration-drift.json"
            path.write_text(json.dumps(trace), encoding="utf-8")
            result = subprocess.run(
                ["python3", str(validator), str(path)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("confirmed_duration_plan_digest_mismatch", result.stdout)

    def test_trace_rejects_image_before_plan_and_paid_before_image_confirmation(self):
        validator = SCRIPTS / "validate_first_response_trace.py"
        fixtures = {
            "two-confirmation-image-before-plan.json": "image_before_plan_confirmation",
            "two-confirmation-paid-before-image-approval.json": "paid_before_image_confirmation",
            "two-confirmation-third-routine-confirmation.json": "third_routine_confirmation_requested",
            "two-confirmation-digest-mismatch.json": "confirmed_asset_digest_mismatch",
            "two-confirmation-incomplete-production.json": "incomplete_automatic_production_loop",
            "two-confirmation-wrong-action-order.json": "wrong_production_action_order",
        }
        for fixture, expected_issue in fixtures.items():
            result = subprocess.run(
                ["python3", str(validator), str(SKILL / "evals" / "fixtures" / fixture)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertNotEqual(result.returncode, 0, fixture)
            self.assertIn(expected_issue, result.stdout, fixture)

    def test_second_confirmation_authorizes_autonomous_execution_to_delivery(self):
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        workflow_text = (SKILL / "references" / "workflow.md").read_text(encoding="utf-8")
        proposal_text = (SKILL / "references" / "proposal-template.md").read_text(encoding="utf-8")
        checklist_text = (SKILL / "references" / "quality-checklist.md").read_text(encoding="utf-8")

        for marker in (
            "autonomous execution contract",
            "no additional user confirmation",
            "repair reserve",
            "approved paid cap",
            "exactly two user confirmations",
        ):
            self.assertIn(marker, skill_text)
        self.assertIn("Continue-To-Delivery Loop", workflow_text)
        self.assertIn("Do not send internal approval questions", workflow_text)
        self.assertIn("自动执行与零付费返修授权", proposal_text)
        self.assertIn("No ordinary post-confirmation step asks the user to approve", checklist_text)

        combined = "\n".join((skill_text, workflow_text, proposal_text))
        self.assertNotIn("retry it only after an explicit user decision", combined)
        self.assertNotIn("terminal provider failure requires user decision", combined)

    def test_paid_gate_requires_second_confirmation_intent_and_exact_image_digests(self):
        create_text = (SCRIPTS / "create_confirmation.py").read_text(encoding="utf-8")
        generate_text = (SCRIPTS / "generate_video.py").read_text(encoding="utf-8")
        workflow_text = (SKILL / "references" / "workflow.md").read_text(encoding="utf-8")
        checklist_text = (SKILL / "references" / "quality-checklist.md").read_text(encoding="utf-8")
        combined = "\n".join((create_text, generate_text, workflow_text, checklist_text))

        for marker in (
            "confirm_images_and_start",
            "confirmed_asset_digests",
            "confirmation_stage",
            "production_authorized",
            "two_confirmation_package_confirmed",
            "production contract payload images",
        ):
            self.assertIn(marker, combined)
        self.assertNotIn("The first assistant response embeds real production images", checklist_text)

    def test_business_scenarios_reference_maps_popular_use_cases(self):
        text = (SKILL / "references" / "business-scenarios.md").read_text(encoding="utf-8")
        required = [
            "Course / enterprise training",
            "Product explainer / sales enablement",
            "Customer service / FAQ / after-sales",
            "HR / recruiting / onboarding / internal comms",
            "Finance / insurance / legal / medical explainers",
            "Real estate / auto / travel / cultural tourism",
            "Multilingual localization / cross-border",
            "Existing talking-head enhancement",
            "success metric",
            "risk boundary",
        ]
        for term in required:
            self.assertIn(term, text)
        self.assertIn("PPT", text)
        self.assertIn("FAQ", text)
        self.assertIn("sales deck", text)

    def test_skill_tree_does_not_contain_raw_api_keys(self):
        pattern = re.compile(r"sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}")
        scanned = []
        for path in SKILL.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".py", ".json", ".example"}:
                scanned.append(path)
                self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")), path)
        self.assertGreater(len(scanned), 20)

    def test_skill_package_hygiene_has_no_runtime_or_private_files(self):
        forbidden = []
        for path in SKILL.rglob("*"):
            if path.name == "__pycache__" or path.suffix == ".pyc" or path.name == ".stitch_tmp":
                forbidden.append(path)
            if path.is_file() and (path.name == ".env" or path.name.endswith(".env.local")):
                forbidden.append(path)
        self.assertEqual(forbidden, [])

    def test_private_env_setup_accepts_stdin_not_command_line_secrets(self):
        result = run_cmd(["python3", str(SCRIPTS / "setup_private_env.py"), "--help"])
        self.assertIn("--key-stdin", result.stdout)
        self.assertIn("--fal-key-stdin", result.stdout)
        self.assertNotRegex(result.stdout, r"--key\s+KEY")
        self.assertNotRegex(result.stdout, r"--fal-key\s+FAL_KEY")

    def test_validate_config_exposes_creator_capability_fields(self):
        result = run_cmd(["python3", str(SCRIPTS / "validate_config.py"), "--config", str(CONFIG)])
        data = json.loads(result.stdout)
        selected = data["models"]["grok_talking_head_basic"]
        seedance = data["models"]["seedance_reference_video"]
        self.assertEqual(data["selected_model"], "grok_talking_head_basic")
        self.assertEqual(data["selected_model_id"], "grok-video-1.5")
        self.assertEqual(data["selected_base_url"], "https://api.119337.xyz/v1")
        self.assertNotIn("api_key_preview", data)
        self.assertTrue(selected["supports_lipsync"])
        self.assertFalse(selected["supports_audio_input"])
        self.assertTrue(selected["supports_script_to_speech"])
        self.assertEqual(selected["lipsync_mode"], "native_generated_dialogue")
        self.assertFalse(selected["external_audio_lipsync"])
        self.assertTrue(seedance["supports_lipsync"])
        self.assertTrue(seedance["supports_audio_input"])
        self.assertTrue(seedance["external_audio_lipsync"])
        self.assertTrue(selected["supports_avatar_reference"])
        self.assertTrue(selected["source_image_becomes_first_frame"])
        self.assertFalse(selected["supports_reference_to_video"])
        self.assertFalse(selected["supports_reference_images"])
        self.assertEqual(selected["official_model"], "grok-imagine-video-1.5")
        self.assertIn("max_script_chars", selected)
        self.assertEqual(selected["api_key_env_names"], ["AI_CREATOR_TALKING_HEAD_VIDEO_API_KEY", "YUNWU_API_KEY", "XAI_API_KEY"])
        self.assertTrue(selected["capability_source"])
        self.assertTrue(selected["verified_at"])
        self.assertTrue(selected["provider_route"])
        self.assertIn("runtime_verified", selected["verification_level"])
        self.assertFalse(data["models"]["multi_reference_creator_video"]["enabled"])
        self.assertNotIn("4k", seedance["supported_resolutions"])
        self.assertNotIn("bitrate_mode", seedance["payload_defaults"])
        self.assertEqual(seedance["external_audio_alignment_level"], "reference_audio_conditioning_not_frame_accurate_guarantee")

    def test_project_brief_exposes_intake_routing_and_source_trace_fields(self):
        data = json.loads((SKILL / "assets" / "templates" / "project-brief.example.json").read_text(encoding="utf-8"))
        for field in ("existing_video_file", "desired_output", "speech_source", "timing_authority", "speech_fidelity_mode", "source_fact_map_required", "source_fact_map"):
            self.assertIn(field, data)
        self.assertIsInstance(data["source_fact_map"], list)

    def test_skill_uses_contract_bound_workflow_engine(self):
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        workflow_text = (SKILL / "references" / "workflow.md").read_text(encoding="utf-8")
        self.assertIn("workflow_engine.py", skill_text)
        self.assertIn("production-contract.json", workflow_text)
        self.assertIn("delivery-manifest.json", workflow_text)
        self.assertNotIn("Use `generate_video.py --confirmed`", skill_text)

    def test_prepare_project_records_core_creator_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script = tmp_path / "script.md"
            avatar = tmp_path / "avatar.png"
            broll = tmp_path / "broll.json"
            scene = tmp_path / "scene.png"
            script.write_text(READY_60S_SCRIPT_WITH_PADDING.replace("主题", "选题", 1), encoding="utf-8")
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            scene.write_bytes(b"\x89PNG\r\n\x1a\n")
            broll.write_text(json.dumps([{"time": "0-3s", "visual": "标题卡"}], ensure_ascii=False), encoding="utf-8")
            result = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "AI Tool Commentary",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--language", "zh",
                "--duration", "60",
                "--aspect-ratio", "9:16",
                "--resolution", "1080p",
                "--script-file", str(script),
                "--avatar-reference", str(avatar),
                "--broll-plan", str(broll),
                "--subtitle-strategy", "大字标题 + 关键词高亮 + 底部安全区",
                "--business-scenario", "enterprise training",
                "--user-intent", "帮助新员工理解 AI 工具视频选题流程",
                "--success-metric", "新员工能独立完成选题检查表",
                "--risk-boundary", "必须忠于内部培训材料，不编造流程",
                "--confirmed-asset", f"scene_reference={scene}",
            ])
            plan = json.loads(Path(json.loads(result.stdout)["plan"]).read_text(encoding="utf-8"))
            self.assertEqual(plan["content_mode"], "avatar_talking_head")
            self.assertEqual(plan["platform"], "douyin")
            self.assertEqual(plan["language"], "zh")
            self.assertEqual(plan["speech_fidelity_mode"], "critical_facts_exact")
            self.assertEqual(plan["aspect_ratio"], "9:16")
            self.assertEqual(plan["resolution"], "1080p")
            self.assertTrue(plan["avatar_reference"])
            self.assertTrue(plan["script_file"])
            self.assertIn("选题", plan["script_text"])
            self.assertTrue(plan["broll_plan"]["entries"])
            self.assertIn("Provider output is always text-free", plan["subtitle_strategy"])
            self.assertFalse(plan["subtitle_plan"]["enabled"])
            self.assertEqual(plan["subtitle_plan"]["source"], "none")
            self.assertEqual(plan["business_scenario"], "enterprise training")
            self.assertEqual(plan["business_context"]["success_metric"], "新员工能独立完成选题检查表")
            self.assertIn("enterprise training", plan["visual_bible"]["business_scenario"])
            roles = [asset["role"] for asset in plan["confirmed_assets"]]
            self.assertIn("avatar_reference", roles)
            self.assertIn("scene_reference", roles)

    def test_long_duration_splits_with_visual_bible_and_stitching_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            avatar = tmp_path / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            script_text = READY_45S_SCRIPT
            result = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Long Digital Human",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--duration", "45",
                "--avatar-reference", str(avatar),
                "--script-text", script_text,
                "--subtitle-strategy", "底部字幕 + 关键词高亮",
            ])
            plan_path = Path(json.loads(result.stdout)["plan"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(len(plan["shots"]), 3)
            self.assertTrue(plan["ready_for_paid_generation"])
            self.assertEqual(plan["visual_bible"]["continuity_priority"], "same_avatar_same_scene_same_style")
            self.assertEqual(plan["image_consistency_plan"]["strategy"], "single_source_frame")
            self.assertTrue(plan["longform_generation_strategy"]["requires_multi_segment"])
            self.assertEqual(plan["longform_generation_strategy"]["segment_count"], 3)
            self.assertTrue(plan["stitching_plan"]["required"])
            self.assertEqual(plan["stitching_plan"]["target_fps"], 30)
            self.assertIn("final.mp4", plan["stitching_plan"]["final_output"])
            for index, shot in enumerate(plan["shots"], start=1):
                self.assertEqual(shot["segment_index"], index)
                self.assertEqual(shot["segment_count"], 3)
                self.assertIn(f"Segment {index}/3", shot["prompt"])
                self.assertIn("same confirmed avatar", shot["continuity_contract"])
                self.assertEqual(shot["visual_bible"]["continuity_priority"], "same_avatar_same_scene_same_style")
                self.assertTrue(shot["script_segment"])
                self.assertIn("script_pacing", shot)
                self.assertIn("script_boundary", shot)
            validation = run_cmd(["python3", str(SCRIPTS / "validate_project.py"), "--plan", str(plan_path)])
            self.assertTrue(json.loads(validation.stdout)["ok"])

    def test_duration_aware_split_blocks_script_that_needs_an_extra_paid_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            avatar = tmp_path / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            script_text = (
                "开场先说，今天的 AI 新闻真正值得关注的不是标题，而是它会不会改变普通人的工作方式。"
                "先看第一个判断，信息来源是否可靠，是否有产品入口，是否已经给出明确的使用场景。"
                "第二个判断，看它能不能节省时间，降低成本，或者帮团队把重复工作变成标准流程。"
                "第三个判断，看风险边界，如果只是概念很热，但没有稳定体验，就不要急着投入预算。"
                "如果团队已经开始使用，还要记录前后耗时，失败原因和真实反馈，方便下一次复盘投入产出。"
                "最后给一个简单行动，收藏这三个判断，下次看到 AI 热点，先判断价值，再决定要不要测试。"
            )
            result = run_cmd_fail([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Pacing Balance",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--duration", "45",
                "--avatar-reference", str(avatar),
                "--script-text", script_text,
            ])
            self.assertIn("minimum 3 paid segments", result.stdout)
            self.assertIn("professional rewrite", result.stdout)
            self.assertIn("extend the requested delivery duration", result.stdout)

    def test_prepare_project_blocks_weak_script_boundary_before_paid_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            avatar = tmp_path / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            result = run_cmd_fail([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Weak Boundary",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--duration", "30",
                "--avatar-reference", str(avatar),
                "--script-text", "第一，第二，第三，",
            ])
            self.assertIn("strong sentence boundaries", result.stdout)
            self.assertIn("professional rewrite", result.stdout)

    def test_prepared_project_never_generates_subtitle_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            avatar = tmp_path / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            prep = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Subtitle Plan",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "youtube_horizontal",
                "--duration", "30",
                "--avatar-reference", str(avatar),
                "--script-text", READY_30S_SCRIPT,
            ])
            plan_path = Path(json.loads(prep.stdout)["plan"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertFalse(plan["subtitle_plan"]["enabled"])
            self.assertEqual(plan["subtitle_plan"]["choice"], "disabled")
            self.assertEqual(plan["subtitle_plan"]["srt_output"], "")
            self.assertEqual(plan["subtitle_plan"]["burned_video_output"], "")
            self.assertFalse((plan_path.parent / "subtitles").exists())

    def test_short_complete_segment_is_usable_and_trimmed_instead_of_blocking_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            avatar = tmp_path / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            result = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Too Short",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--duration", "15",
                "--avatar-reference", str(avatar),
                "--script-text", "这是一段内容完整、结尾自然的简短口播。",
                "--subtitle-choice", "disabled",
                "--effects-choice", "disabled",
            ])
            plan_path = json.loads(result.stdout)["plan"]
            plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
            self.assertTrue(plan["ready_for_paid_generation"], plan["blocking_reasons"])
            self.assertEqual(plan["shots"][0]["script_pacing"]["status"], "short_but_usable")
            self.assertTrue(plan["stitching_plan"]["auto_trim_tail_silence"])
            validation = run_cmd([
                "python3", str(SCRIPTS / "validate_project.py"),
                "--plan", plan_path,
                "--enforce-script-pacing",
            ])
            data = json.loads(validation.stdout)
            self.assertTrue(data["ok"], data["errors"])

    def test_overlong_two_part_script_does_not_silently_add_a_third_paid_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            avatar = tmp_path / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            segments = tmp_path / "segments.json"
            segments.write_text(json.dumps({"segments": [
                {
                    "duration_seconds": 15,
                    "script": "OpenAI 又放大招了！7 月 9 日，GPT-5.6 系列正式全面发布，带来 Sol、Terra 和 Luna 三档模型，分别覆盖旗舰性能、日常性价比和高速低成本需求。从高性能到低成本，选择更加完整。",
                },
                {
                    "duration_seconds": 15,
                    "script": "更值得关注的是全新的 ultra 模式，它能协调多个智能体并行处理复杂任务。目前，新模型已陆续进入 ChatGPT、Codex 和 API，价格也会根据不同能力档位区分。开发者也能根据任务和预算灵活选择。",
                },
            ]}, ensure_ascii=False), encoding="utf-8")

            result = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Adaptive Segments",
                "--project-root", str(tmp_path / "projects"),
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

            self.assertEqual(len(plan["shots"]), 2)
            self.assertFalse(plan["duration_plan"]["automatic_content_fit"])
            self.assertEqual(plan["duration_plan"]["segmentation_reason"], "explicit_user_confirmed_segments")
            self.assertEqual(plan["duration_plan"]["planned_duration_seconds"], sum(shot["duration_seconds"] for shot in plan["shots"]))
            self.assertEqual(plan["delivery_duration_seconds"], 30)
            self.assertEqual([shot["duration_seconds"] for shot in plan["shots"]], [15, 15])
            self.assertTrue(any(shot["script_pacing"]["status"] == "too_long" for shot in plan["shots"]))
            self.assertTrue(all(shot["script_boundary"]["stitch_safe"] for shot in plan["shots"][:-1]))
            self.assertFalse(plan["ready_for_paid_generation"])
            validation = run_cmd_fail([
                "python3", str(SCRIPTS / "validate_project.py"),
                "--plan", str(plan_path),
                "--enforce-script-pacing",
            ])
            self.assertIn("too_long", validation.stdout)
            preflight = run_cmd_fail([
                "python3", str(SCRIPTS / "preflight_project.py"),
                "--plan", str(plan_path),
                "--config", str(SKILL / "assets" / "templates" / "model-config.example.json"),
            ])
            preflight_data = json.loads(preflight.stdout)
            self.assertFalse(preflight_data["ok"])
            self.assertEqual(preflight_data["expected_paid_requests"], len(plan["shots"]))

    def test_explicit_segments_use_legal_slots_for_a_confirmed_27_second_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            avatar = tmp_path / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            segments = tmp_path / "segments.json"
            first_script = "职场人和企业管理者注意了！现在，不用精通编程，靠 vibe coding，也能自主开发 AI 智能体。日常报表整理和客户跟进回访，都可以交给智能体自动完成。"
            second_script = "企业流程审批等重复工作，也能交给智能体自动完成。这样既能提升效率，也能降低运营成本。越早把智能体落地，就越容易拉开差距。"
            segments.write_text(json.dumps({"segments": [
                {"duration_seconds": 15, "script": first_script},
                {"duration_seconds": 12, "script": second_script},
            ]}, ensure_ascii=False), encoding="utf-8")

            result = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Confirmed 27 Seconds",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--duration", "27",
                "--avatar-reference", str(avatar),
                "--segments-file", str(segments),
                "--subtitle-choice", "disabled",
                "--effects-choice", "disabled",
            ])
            plan = json.loads(Path(json.loads(result.stdout)["plan"]).read_text(encoding="utf-8"))

            self.assertEqual([shot["duration_seconds"] for shot in plan["shots"]], [15, 12])
            self.assertEqual(plan["duration_plan"]["confirmed_duration_seconds"], 27)
            self.assertEqual(plan["duration_plan"]["planned_duration_seconds"], 27)
            self.assertEqual(plan["duration_plan"]["delivery_max_seconds"], 27)
            self.assertEqual(plan["delivery_duration_seconds"], 27)
            self.assertTrue(plan["ready_for_paid_generation"], plan["blocking_reasons"])

    def test_review_render_detects_tail_silence_and_missing_clip(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            clips_dir = tmp_path / "clips"
            clips_dir.mkdir()
            clip1 = clips_dir / "shot_01.mp4"
            clip2 = clips_dir / "shot_02.mp4"
            partial = tmp_path / "partial-4s-preview.mp4"
            for clip in (clip1, clip2):
                proc = subprocess.run([
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", "color=c=blue:s=160x284:r=24:d=2",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-shortest",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    str(clip),
                ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(proc.returncode, 0, proc.stderr)
            concat = tmp_path / "concat.txt"
            concat.write_text(f"file '{clip1}'\nfile '{clip2}'\n", encoding="utf-8")
            proc = subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(partial)
            ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            plan = {
                "total_duration_seconds": 6,
                "script_pacing": {"status": "ok"},
                "shots": [
                    {"id": "shot_01", "clip_file": str(clip1)},
                    {"id": "shot_02", "clip_file": str(clip2)},
                    {"id": "shot_03", "clip_file": str(clips_dir / "shot_03.mp4")},
                ],
            }
            plan_path = tmp_path / "generation-plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            result = run_cmd_fail([
                "python3", str(SCRIPTS / "review_render.py"),
                "--project-dir", str(tmp_path),
                "--video", str(partial),
                "--plan", str(plan_path),
            ])
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "revise")
            self.assertEqual(data["recommended_action"], "wait_for_missing_clips")
            joined = "\n".join(data["issues_found"])
            self.assertIn("missing expected clip", joined)
            self.assertIn("tail silence", joined)
            self.assertIn("duration mismatch", joined)

    def test_review_render_detects_active_audio_at_stitch_boundary(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            clips_dir = tmp_path / "clips"
            clips_dir.mkdir()
            clip1 = clips_dir / "shot_01.mp4"
            clip2 = clips_dir / "shot_02.mp4"
            final = tmp_path / "final.mp4"
            for clip in (clip1, clip2):
                proc = subprocess.run([
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", "color=c=red:s=160x284:r=24:d=2",
                    "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100:duration=2",
                    "-shortest",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    str(clip),
                ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(proc.returncode, 0, proc.stderr)
            concat = tmp_path / "concat.txt"
            concat.write_text(f"file '{clip1}'\nfile '{clip2}'\n", encoding="utf-8")
            proc = subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(final)
            ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            plan = {
                "total_duration_seconds": 4,
                "subtitle_strategy": "不要字幕",
                "subtitle_plan": {"enabled": False},
                "script_pacing": {"status": "ok"},
                "shots": [
                    {
                        "id": "shot_01",
                        "clip_file": str(clip1),
                        "script_segment": "第一段完整结束。",
                        "script_boundary": {"boundary_type": "strong_sentence", "stitch_safe": True},
                    },
                    {
                        "id": "shot_02",
                        "clip_file": str(clip2),
                        "script_segment": "第二段完整结束。",
                        "script_boundary": {"boundary_type": "strong_sentence", "stitch_safe": True, "is_final_segment": True},
                    },
                ],
            }
            plan_path = tmp_path / "generation-plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            result = run_cmd_fail([
                "python3", str(SCRIPTS / "review_render.py"),
                "--project-dir", str(tmp_path),
                "--video", str(final),
                "--plan", str(plan_path),
            ])
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "revise")
            joined = "\n".join(data["issues_found"])
            self.assertIn("active audio at stitch boundary", joined)

    def test_long_script_can_be_ready_when_each_segment_prompt_fits_model_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            avatar = tmp_path / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            script_text = READY_60S_SCRIPT_WITH_PADDING
            result = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Long Script Split",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--duration", "60",
                "--avatar-reference", str(avatar),
                "--script-text", script_text,
            ])
            plan = json.loads(Path(json.loads(result.stdout)["plan"]).read_text(encoding="utf-8"))
            self.assertGreater(len(script_text), plan["model_capabilities"]["max_script_chars"])
            self.assertEqual(len(plan["shots"]), 4)
            self.assertTrue(plan["ready_for_paid_generation"])
            self.assertTrue(any("full script_text length" in warning for warning in plan["warnings"]))
            self.assertFalse(any("shot prompt length" in warning for warning in plan["warnings"]))

    def test_single_image_route_blocks_storyboard_sheet_as_only_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            storyboard = tmp_path / "storyboard.png"
            storyboard.write_bytes(b"\x89PNG\r\n\x1a\n")
            result = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Storyboard Only",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--duration", "15",
                "--storyboard-image", str(storyboard),
                "--reference-image", f"storyboard_sheet={storyboard}",
                "--script-text", "只提供多宫格分镜图是不够的。",
            ])
            plan = json.loads(Path(json.loads(result.stdout)["plan"]).read_text(encoding="utf-8"))
            self.assertFalse(plan["ready_for_paid_generation"])
            self.assertTrue(any("storyboard_sheet as the only video source" in warning for warning in plan["warnings"]))
            self.assertTrue(any("storyboard sheet cannot be the only source" in reason.lower() for reason in plan["blocking_reasons"]))

    def test_per_segment_source_frames_are_used_per_shot(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shot1 = tmp_path / "shot-1.png"
            shot2 = tmp_path / "shot-2.png"
            shot1.write_bytes(b"\x89PNG\r\n\x1a\nshot-one")
            shot2.write_bytes(b"\x89PNG\r\n\x1a\nshot-two")
            prep = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Segment Sources",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--duration", "30",
                "--segment-source-image", f"shot_01={shot1}",
                "--segment-source-image", f"shot_02={shot2}",
                "--script-text", READY_30S_SCRIPT,
            ])
            plan_path = json.loads(prep.stdout)["plan"]
            plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
            self.assertTrue(plan["ready_for_paid_generation"])
            self.assertEqual(plan["visual_asset_strategy"], "per_segment_source_frames")
            self.assertEqual(plan["image_consistency_plan"]["segment_source_count"], 2)
            self.assertEqual(plan["shots"][0]["segment_source_asset"]["segment_index"], 1)
            self.assertEqual(plan["shots"][1]["segment_source_asset"]["segment_index"], 2)
            dry = run_cmd([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", plan_path,
                "--dry-run",
            ])
            results = json.loads(dry.stdout)["results"]
            self.assertEqual(len(results), 2)
            first_record = json.loads(Path(results[0]["request_file"]).read_text(encoding="utf-8"))
            second_record = json.loads(Path(results[1]["request_file"]).read_text(encoding="utf-8"))
            self.assertEqual(first_record["asset_trace"]["source_asset_segment_index"], 1)
            self.assertEqual(second_record["asset_trace"]["source_asset_segment_index"], 2)
            self.assertNotEqual(first_record["payload"]["image_urls"][0], second_record["payload"]["image_urls"][0])

    def test_multi_reference_route_does_not_cross_mix_segment_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shot1 = tmp_path / "shot-1.png"
            shot2 = tmp_path / "shot-2.png"
            scene = tmp_path / "scene.png"
            shot1.write_bytes(b"\x89PNG\r\n\x1a\nshot-one")
            shot2.write_bytes(b"\x89PNG\r\n\x1a\nshot-two")
            scene.write_bytes(b"\x89PNG\r\n\x1a\nscene")
            prep = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "No Cross Mix",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--model-key", "multi_reference_creator_video",
                "--duration", "20",
                "--segment-source-image", f"shot_01={shot1}",
                "--segment-source-image", f"shot_02={shot2}",
                "--reference-image", f"scene_reference={scene}",
                "--script-text", (
                    READY_10S_SCRIPT
                    + "接着检查每个片段只使用对应来源图并保留同一场景参考，避免把另一段人物姿态错误混入当前镜头。"
                ),
            ])
            plan_path = json.loads(prep.stdout)["plan"]
            dry = run_cmd([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", plan_path,
                "--dry-run",
            ])
            results = json.loads(dry.stdout)["results"]
            first_record = json.loads(Path(results[0]["request_file"]).read_text(encoding="utf-8"))
            second_record = json.loads(Path(results[1]["request_file"]).read_text(encoding="utf-8"))
            self.assertEqual(first_record["asset_trace"]["source_asset_segment_index"], 1)
            self.assertEqual(second_record["asset_trace"]["source_asset_segment_index"], 2)
            self.assertEqual(first_record["asset_trace"]["reference_roles"], ["scene_reference"])
            self.assertEqual(second_record["asset_trace"]["reference_roles"], ["scene_reference"])
            self.assertEqual(len(first_record["payload"]["image_urls"]), 2)
            self.assertEqual(len(second_record["payload"]["image_urls"]), 2)

    def test_segment_source_labels_must_be_unique_and_cover_every_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shot1 = tmp_path / "shot-1.png"
            shot2 = tmp_path / "shot-2.png"
            shot1.write_bytes(b"shot-one")
            shot2.write_bytes(b"shot-two")
            duplicate = run_cmd_fail([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "duplicate-segment-source",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--duration", "30",
                "--segment-source-image", f"shot_01={shot1}",
                "--segment-source-image", f"shot_01={shot2}",
                "--script-text", READY_30S_SCRIPT,
            ])
            self.assertIn("duplicate segment source", duplicate.stdout.lower())

            missing = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "missing-segment-source",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--duration", "30",
                "--segment-source-image", f"shot_01={shot1}",
                "--segment-source-image", f"shot_03={shot2}",
                "--script-text", READY_30S_SCRIPT,
            ])
            plan = json.loads(Path(json.loads(missing.stdout)["plan"]).read_text(encoding="utf-8"))
            self.assertFalse(plan["ready_for_paid_generation"])
            self.assertEqual(plan["image_consistency_plan"]["segment_source_indices"], [1, 3])

    def test_prepare_without_avatar_records_original_avatar_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "No Avatar",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "script_rewrite",
                "--platform", "xiaohongshu",
                "--script-text", "这是一条小红书口播草稿。",
            ])
            plan = json.loads(Path(json.loads(result.stdout)["plan"]).read_text(encoding="utf-8"))
            self.assertFalse(plan["avatar_plan"]["has_avatar_reference"])
            self.assertTrue(plan["avatar_plan"]["needs_generated_avatar_reference"])
            self.assertIn("原创数字人形象参考图", plan["avatar_plan"]["message"])
            self.assertFalse(plan["ready_for_paid_generation"])
            self.assertTrue(any("No avatar reference or final video_source" in reason for reason in plan["blocking_reasons"]))

    def test_confirmed_final_video_source_allows_no_separate_avatar_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "approved-source.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\n")
            result = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Final Source",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--duration", "15",
                "--script-text", READY_15S_SCRIPT,
                "--confirmed-asset", f"video_source={source}",
            ])
            plan = json.loads(Path(json.loads(result.stdout)["plan"]).read_text(encoding="utf-8"))
            self.assertTrue(plan["avatar_plan"]["needs_generated_avatar_reference"])
            self.assertTrue(plan["ready_for_paid_generation"])
            self.assertEqual(plan["blocking_reasons"], [])

    def test_existing_audio_and_subtitles_do_not_force_tts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio = tmp_path / "voice.mp3"
            subtitle = tmp_path / "captions.srt"
            audio.write_bytes(b"fake mp3 bytes")
            subtitle.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好\n", encoding="utf-8")
            result = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Hybrid Broll",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "hybrid_broll_edit",
                "--platform", "douyin",
                "--audio-file", str(audio),
                "--subtitle-file", str(subtitle),
                "--script-text", "保留原口播，补 B-roll。",
            ])
            plan = json.loads(Path(json.loads(result.stdout)["plan"]).read_text(encoding="utf-8"))
            self.assertFalse(plan["generation_requirements"]["tts_required"])
            self.assertTrue(plan["asset_contract"]["has_existing_audio"])
            self.assertTrue(plan["asset_contract"]["has_existing_subtitle"])

    def test_lipsync_required_on_default_model_does_not_warn_to_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            avatar = tmp_path / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            result = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Default Lip Sync",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--duration", "15",
                "--avatar-reference", str(avatar),
                "--script-text", "这一条是数字人口播新闻稿，要求主播自然开口讲解，画面和声音保持同步。",
                "--lipsync-required",
            ])
            data = json.loads(result.stdout)
            self.assertFalse(any("supports_lipsync=false" in warning for warning in data["warnings"]))
            self.assertFalse(any("Switch to a lip-sync/audio-input model" in warning for warning in data["warnings"]))
            plan = json.loads(Path(data["plan"]).read_text(encoding="utf-8"))
            self.assertTrue(plan["generation_requirements"]["strict_lipsync_supported"])
            self.assertEqual(plan["model_capabilities"]["lipsync_mode"], "native_generated_dialogue")

    def test_lipsync_required_on_unsupported_model_warns_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "model-config.json"
            config = json.loads(CONFIG.read_text(encoding="utf-8"))
            config["models"]["unsupported_video"] = {
                **config["models"]["grok_talking_head_basic"],
                "supports_lipsync": False,
                "supports_script_to_speech": False,
                "lipsync_mode": "",
                "external_audio_lipsync": False,
            }
            config["models"]["unsupported_video"]["enabled"] = True
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            result = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Need Lip Sync",
                "--project-root", str(tmp_path / "projects"),
                "--config", str(config_path),
                "--model-key", "unsupported_video",
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--script-text", "这一条要求严格口型同步。",
                "--lipsync-required",
            ])
            data = json.loads(result.stdout)
            self.assertTrue(any("supports_lipsync=false" in warning for warning in data["warnings"]))
            plan = json.loads(Path(data["plan"]).read_text(encoding="utf-8"))
            self.assertFalse(plan["ready_for_paid_generation"])

    def test_dry_run_does_not_leak_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            avatar = tmp_path / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            prep = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Dry Run",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--avatar-reference", str(avatar),
                "--script-text", "测试 dry-run 不泄露密钥。",
            ])
            plan_path = json.loads(prep.stdout)["plan"]
            secret = "unit-test-secret-value-that-should-not-appear"
            dry = run_cmd([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", plan_path,
                "--dry-run",
            ], env={"AI_CREATOR_TALKING_HEAD_VIDEO_API_KEY": secret})
            self.assertNotIn(secret, dry.stdout)
            request_file = Path(json.loads(dry.stdout)["results"][0]["request_file"])
            record_text = request_file.read_text(encoding="utf-8")
            self.assertNotIn(secret, record_text)
            record = json.loads(record_text)
            self.assertTrue(record["dry_run"])
            self.assertIn("asset_trace", record)
            self.assertIsInstance(record["payload"]["image_urls"], list)
            self.assertEqual(len(record["payload"]["image_urls"]), 1)

    def test_multi_segment_dry_run_creates_one_request_per_segment_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            avatar = tmp_path / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            prep = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Dry Run Multi Segment",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--duration", "30",
                "--avatar-reference", str(avatar),
                "--script-text", READY_30S_SCRIPT,
            ])
            plan_path = json.loads(prep.stdout)["plan"]
            dry = run_cmd([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", plan_path,
                "--dry-run",
            ])
            results = json.loads(dry.stdout)["results"]
            self.assertEqual(len(results), 2)
            for index, item in enumerate(results, start=1):
                record = json.loads(Path(item["request_file"]).read_text(encoding="utf-8"))
                self.assertIn(f"Segment {index}/2", record["payload"]["prompt"])
                self.assertIsInstance(record["payload"]["image_urls"], list)
                self.assertEqual(len(record["payload"]["image_urls"]), 1)
                self.assertTrue(record["asset_trace"]["source_included_in_payload"])
                self.assertEqual(record["asset_trace"]["source_asset"]["role"], "avatar_reference")

    def test_reference_images_are_merged_into_multi_reference_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            avatar = tmp_path / "avatar.png"
            scene = tmp_path / "scene.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            scene.write_bytes(b"\x89PNG\r\n\x1a\n")
            prep = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Multi Ref",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--model-key", "multi_reference_creator_video",
                "--avatar-reference", str(avatar),
                "--reference-image", f"scene_reference={scene}",
                "--script-text", READY_10S_SCRIPT,
            ])
            plan_path = json.loads(prep.stdout)["plan"]
            plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
            self.assertFalse(plan["ready_for_paid_generation"])
            self.assertTrue(any("disabled" in item for item in plan["blocking_reasons"]))
            dry = run_cmd([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", plan_path,
                "--dry-run",
            ])
            request_file = Path(json.loads(dry.stdout)["results"][0]["request_file"])
            record = json.loads(request_file.read_text(encoding="utf-8"))
            self.assertIsInstance(record["payload"]["image_urls"], list)
            self.assertEqual(len(record["payload"]["image_urls"]), 2)
            self.assertEqual(record["asset_trace"]["reference_count"], 1)
            self.assertEqual(record["asset_trace"]["reference_roles"], ["scene_reference"])

    def test_real_generation_refuses_not_ready_plan_before_key_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            confirmation = tmp_path / "video-confirmation.json"
            confirmation.write_text(json.dumps({
                "confirmation_stage": "production_authorized",
                "plan_confirmed": True,
                "image_assets_confirmed": True,
                "video_generation_confirmed": True,
                "single_production_package_confirmed": True,
                "two_confirmation_package_confirmed": True,
                "image_confirmation_intent": "confirm_images_and_start",
                "confirmed_asset_digests": ["0" * 64],
                "approved_by": "test",
            }), encoding="utf-8")
            prep = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Not Ready",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "script_rewrite",
                "--platform", "douyin",
                "--script-text", "没有头像参考图，不能直接付费生成。",
            ])
            plan_path = json.loads(prep.stdout)["plan"]
            result = run_cmd_fail([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", plan_path,
                "--confirmation-file", str(confirmation),
            ], env={"AI_CREATOR_TALKING_HEAD_VIDEO_API_KEY": "unit-test-key-that-should-not-be-needed"})
            self.assertIn("not ready for paid generation", result.stdout)

    def test_paid_generation_requires_confirmation_file_and_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            avatar = tmp_path / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            prep = run_cmd([
                "python3", str(SCRIPTS / "prepare_project.py"),
                "--name", "Paid Confirmation",
                "--project-root", str(tmp_path / "projects"),
                "--content-mode", "avatar_talking_head",
                "--platform", "douyin",
                "--duration", "15",
                "--avatar-reference", str(avatar),
                "--script-text", READY_15S_SCRIPT,
            ])
            plan_path = json.loads(prep.stdout)["plan"]
            plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
            self.assertTrue(plan["ready_for_paid_generation"])

            manual = run_cmd_fail([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", plan_path,
                "--confirmed",
            ])
            self.assertIn("Use --confirmation-file", manual.stdout)

            bad_confirmation = tmp_path / "bad-confirmation.json"
            bad_confirmation.write_text(json.dumps({"video_generation_confirmed": True}), encoding="utf-8")
            bad = run_cmd_fail([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", plan_path,
                "--confirmation-file", str(bad_confirmation),
            ])
            self.assertIn("image_assets_confirmed=true", bad.stdout)

            legacy_confirmation = tmp_path / "legacy-confirmation.json"
            legacy_confirmation.write_text(json.dumps({
                "image_assets_confirmed": True,
                "video_generation_confirmed": True,
            }), encoding="utf-8")
            legacy = run_cmd_fail([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", plan_path,
                "--confirmation-file", str(legacy_confirmation),
            ])
            self.assertIn("single_production_package_confirmed=true", legacy.stdout)

            preflight = run_cmd([
                "python3", str(SCRIPTS / "preflight_project.py"),
                "--plan", plan_path,
                "--config", str(CONFIG),
            ])
            contract_file = json.loads(preflight.stdout)["contract_file"]
            plan_only_confirmation = run_cmd_fail([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", contract_file,
                "--approved-by", "test",
            ])
            self.assertIn("confirm_images_and_start", plan_only_confirmation.stdout)
            contract = json.loads(Path(contract_file).read_text(encoding="utf-8"))
            image_digests = [
                item["sha256"] for item in contract["asset_fingerprints"]
                if item.get("role") in {"avatar_reference", "video_source", "first_frame", "segment_source"}
            ]
            self.assertTrue(image_digests)
            confirmed = run_cmd([
                "python3", str(SCRIPTS / "create_confirmation.py"),
                "--contract", contract_file,
                "--approved-by", "test",
                "--confirmation-intent", "confirm_images_and_start",
                *[value for digest in image_digests for value in ("--confirmed-asset-digest", digest)],
                "--confirmed-duration-plan-digest", contract["duration_plan_digest"],
            ])
            good_confirmation = json.loads(confirmed.stdout)["confirmation_file"]
            confirmation_data = json.loads(Path(good_confirmation).read_text(encoding="utf-8"))
            self.assertEqual(confirmation_data["confirmation_stage"], "production_authorized")
            self.assertEqual(confirmation_data["confirmed_asset_digests"], image_digests)
            self.assertEqual(confirmation_data["confirmed_duration_plan_digest"], contract["duration_plan_digest"])
            forged_confirmation = Path(good_confirmation).with_name("forged-image-confirmation.json")
            confirmation_data["confirmed_asset_digests"] = ["f" * 64]
            forged_confirmation.write_text(json.dumps(confirmation_data), encoding="utf-8")
            forged = run_cmd_fail([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", plan_path,
                "--confirmation-file", str(forged_confirmation),
            ])
            self.assertIn("confirmed image digests", forged.stdout.lower())
            missing_key = run_cmd_fail([
                "python3", str(SCRIPTS / "generate_video.py"),
                "--plan", plan_path,
                "--confirmation-file", good_confirmation,
            ])
            self.assertIn("Missing API key", missing_key.stdout)

    def test_analyze_script_timeline_outputs_segments(self):
        result = run_cmd([
            "python3", str(SCRIPTS / "analyze_script_timeline.py"),
            "--language", "zh",
            "--script-text", "第一段：先提出问题。第二段：给出方法。第三段：总结 CTA。",
        ])
        data = json.loads(result.stdout)
        self.assertGreaterEqual(data["total_estimated_seconds"], 1.5)
        self.assertTrue(data["segments"])


if __name__ == "__main__":
    unittest.main()
