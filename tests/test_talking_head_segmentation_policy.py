#!/usr/bin/env python3
"""Regression tests for model-aware minimal paid segmentation."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "ai-creator-talking-head-video"
SCRIPTS = SKILL / "scripts"
CONFIG = SKILL / "assets" / "templates" / "model-config.example.json"

VIBE_CODING_SCRIPT = (
    "职场人和企业管理者注意了！现在，不用精通编程，靠 vibe coding，也能自主开发 AI 智能体。"
    "从日常报表整理、客户跟进回访，到企业内部的流程审批，大量重复性工作，都可以交给智能体自动完成。"
    "它不仅能明显提升个人效率，还能有效降低团队的运营成本。AI 智能体，越早掌握，越早落地，就越容易拉开竞争差距。"
)
OPTIMIZED_VIBE_SEGMENTS = [
    "职场人和企业管理者注意了！现在，不用精通编程，靠 vibe coding，也能自主开发 AI 智能体。日常报表整理和客户跟进回访，都可以交给智能体自动完成。",
    "企业流程审批等重复性工作，也能让智能体自动完成。它既能明显提升个人效率，也能降低团队运营成本。AI 智能体越早掌握和落地，就越容易拉开竞争差距。",
]
OPTIMIZED_VIBE_SCRIPT = "".join(OPTIMIZED_VIBE_SEGMENTS)


def run_command(arguments: list[str], *, expect_success: bool) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in list(env):
        if key.endswith("API_KEY") or key in {"FAL_KEY", "YUNWU_API_KEY", "XAI_API_KEY"}:
            env.pop(key, None)
    env["AI_CREATOR_TALKING_HEAD_VIDEO_ENV_FILE"] = str(ROOT / ".nonexistent-segmentation-test-env")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if expect_success and result.returncode != 0:
        raise AssertionError(f"Command failed: {' '.join(arguments)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    if not expect_success and result.returncode == 0:
        raise AssertionError(f"Command unexpectedly passed: {' '.join(arguments)}\nSTDOUT:\n{result.stdout}")
    return result


def base_prepare_arguments(project_root: Path, avatar: Path, duration: int, script: str) -> list[str]:
    return [
        "python3",
        str(SCRIPTS / "prepare_project.py"),
        "--name",
        "Segmentation Regression",
        "--project-root",
        str(project_root),
        "--content-mode",
        "avatar_talking_head",
        "--platform",
        "douyin",
        "--duration",
        str(duration),
        "--config",
        str(CONFIG),
        "--avatar-reference",
        str(avatar),
        "--script-text",
        script,
        "--subtitle-choice",
        "disabled",
        "--effects-choice",
        "disabled",
    ]


class TalkingHeadSegmentationPolicyTests(unittest.TestCase):
    def test_raw_vibe_script_requires_professional_rewrite_for_strong_two_part_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            common = base_prepare_arguments(root / "projects", avatar, 30, VIBE_CODING_SCRIPT)

            proposal = run_command(common + ["--duration-plan-only"], expect_success=False)
            self.assertIn("professional rewrite", proposal.stdout.lower())
            self.assertIn("strong sentence", proposal.stdout.lower())
            self.assertFalse((root / "projects").exists())

    def test_optimized_vibe_script_is_two_15_second_requests_with_matching_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            segments = root / "segments.json"
            segments.write_text(
                json.dumps(
                    [
                        {"duration_seconds": 15, "script": OPTIMIZED_VIBE_SEGMENTS[0]},
                        {"duration_seconds": 15, "script": OPTIMIZED_VIBE_SEGMENTS[1]},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            common = base_prepare_arguments(root / "projects", avatar, 30, OPTIMIZED_VIBE_SCRIPT) + [
                "--segments-file",
                str(segments),
            ]

            proposal = run_command(common + ["--duration-plan-only"], expect_success=True)
            proposal_data = json.loads(proposal.stdout)
            self.assertEqual(proposal_data["planned_request_durations_seconds"], [15, 15])
            self.assertEqual(proposal_data["segment_count"], 2)
            self.assertEqual(proposal_data["delivery_max_seconds"], 30)
            self.assertGreater(proposal_data["planned_trim_seconds"], 0)
            self.assertEqual(proposal_data["planned_delivery_overshoot_seconds"], 0)
            self.assertEqual([item["script"] for item in proposal_data["segments"]], OPTIMIZED_VIBE_SEGMENTS)
            self.assertGreaterEqual(proposal_data["estimated_spoken_seconds"], 25.5)
            self.assertLessEqual(proposal_data["estimated_spoken_seconds"], 28.5)
            self.assertGreaterEqual(proposal_data["spoken_fill_ratio"], 0.85)
            self.assertLessEqual(proposal_data["spoken_fill_ratio"], 0.95)
            self.assertEqual(proposal_data["minimum_multi_segment_spoken_fill_ratio"], 0.75)
            for segment in proposal_data["segments"]:
                self.assertGreaterEqual(segment["estimated_spoken_seconds"], 12.0)
                self.assertLessEqual(segment["estimated_spoken_seconds"], 14.2)
            self.assertRegex(proposal_data["duration_plan_digest"], r"^[0-9a-f]{64}$")

            prepared = run_command(common, expect_success=True)
            plan_path = Path(json.loads(prepared.stdout)["plan"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual([shot["duration_seconds"] for shot in plan["shots"]], [15, 15])
            self.assertEqual(plan["duration_plan"]["request_duration_seconds"], [15, 15])
            self.assertEqual(plan["duration_plan"]["planned_request_total_seconds"], 30)
            self.assertEqual(plan["duration_plan"]["delivery_max_seconds"], 30)
            self.assertGreater(plan["duration_plan"]["planned_trim_seconds"], 0)
            self.assertEqual(plan["duration_plan"]["planned_delivery_overshoot_seconds"], 0)
            self.assertEqual(plan["delivery_duration_seconds"], 30)
            self.assertEqual(plan["duration_plan_digest"], proposal_data["duration_plan_digest"])
            self.assertEqual(plan["duration_plan"]["duration_plan_digest"], proposal_data["duration_plan_digest"])
            validation = run_command(
                [
                    "python3",
                    str(SCRIPTS / "validate_project.py"),
                    "--plan",
                    str(plan_path),
                    "--enforce-script-pacing",
                ],
                expect_success=True,
            )
            self.assertTrue(json.loads(validation.stdout)["ok"])

    def test_unsupported_explicit_durations_are_rejected_without_a_key_or_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            for unsupported in (11, 13, 14):
                with self.subTest(duration=unsupported):
                    segments = root / f"segments-{unsupported}.json"
                    segments.write_text(
                        json.dumps([{"duration_seconds": unsupported, "script": "一段完整的测试口播稿。"}], ensure_ascii=False),
                        encoding="utf-8",
                    )
                    result = run_command(
                        base_prepare_arguments(root / f"projects-{unsupported}", avatar, 15, "一段完整的测试口播稿。")
                        + ["--segments-file", str(segments)],
                        expect_success=False,
                    )
                    self.assertIn("allowed", result.stdout.lower())
                    self.assertIn("4, 6, 8, 10, 12, 15", result.stdout)
                    self.assertFalse((root / f"projects-{unsupported}").exists())

    def test_explicit_segment_count_must_exactly_match_two_segment_minimum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            cases = {
                1: [{"duration_seconds": 15, "script": "只有一段完整口播。"}],
                3: [
                    {"duration_seconds": 10, "script": "第一段完整口播。"},
                    {"duration_seconds": 10, "script": "第二段完整口播。"},
                    {"duration_seconds": 10, "script": "第三段完整口播。"},
                ],
            }
            for count, values in cases.items():
                with self.subTest(segment_count=count):
                    segments = root / f"segments-{count}.json"
                    segments.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
                    result = run_command(
                        base_prepare_arguments(root / f"projects-{count}", avatar, 30, "")
                        + ["--segments-file", str(segments)],
                        expect_success=False,
                    )
                    self.assertIn("must equal the minimum paid segment count of 2", result.stdout.lower())

    def test_duration_plan_digest_changes_when_exact_script_or_confirmed_slot_plan_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")

            def digest_for(name: str, durations: list[int], scripts: list[str], delivery: int = 30) -> str:
                segments = root / f"{name}.json"
                segments.write_text(
                    json.dumps(
                        [
                            {"duration_seconds": duration, "script": script}
                            for duration, script in zip(durations, scripts)
                        ],
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                result = run_command(
                    base_prepare_arguments(root / name, avatar, delivery, "".join(scripts))
                    + ["--segments-file", str(segments), "--duration-plan-only"],
                    expect_success=True,
                )
                return json.loads(result.stdout)["duration_plan_digest"]

            base_digest = digest_for("base", [15, 15], OPTIMIZED_VIBE_SEGMENTS)
            changed_scripts = [OPTIMIZED_VIBE_SEGMENTS[0].replace("注意了", "真正注意了"), OPTIMIZED_VIBE_SEGMENTS[1]]
            changed_script_digest = digest_for("changed-script", [15, 15], changed_scripts)
            changed_slot_digest = digest_for("changed-slot", [15, 12], OPTIMIZED_VIBE_SEGMENTS, delivery=27)
            self.assertNotEqual(base_digest, changed_script_digest)
            self.assertNotEqual(base_digest, changed_slot_digest)

    def test_explicit_nonfinal_semantic_fragment_is_rejected_even_with_a_period(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            first_segments = [
                "从日常报表整理、客户跟进回访，",
                "从日常报表整理、客户跟进回访，到企业内部的流程审批。",
                "先说明应用范围。从日常报表整理、客户跟进回访，到企业内部的流程审批。",
            ]
            for index, first_segment in enumerate(first_segments, start=1):
                with self.subTest(first_segment=first_segment):
                    scripts = [first_segment, "这些重复性工作都能交给智能体自动完成。"]
                    segments = root / f"semantic-fragment-{index}.json"
                    segments.write_text(
                        json.dumps(
                            [
                                {"duration_seconds": 15, "script": scripts[0]},
                                {"duration_seconds": 15, "script": scripts[1]},
                            ],
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                    result = run_command(
                        base_prepare_arguments(root / f"projects-{index}", avatar, 30, "".join(scripts))
                        + ["--segments-file", str(segments), "--duration-plan-only"],
                        expect_success=False,
                    )
                    self.assertIn("semantic", result.stdout.lower())

    def test_explicit_request_slots_must_match_deterministic_30_second_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            for durations in ([10, 10], [15, 12]):
                with self.subTest(durations=durations):
                    segments = root / f"segments-{'-'.join(str(value) for value in durations)}.json"
                    segments.write_text(
                        json.dumps(
                            [
                                {"duration_seconds": durations[0], "script": OPTIMIZED_VIBE_SEGMENTS[0]},
                                {"duration_seconds": durations[1], "script": OPTIMIZED_VIBE_SEGMENTS[1]},
                            ],
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                    result = run_command(
                        base_prepare_arguments(root / f"projects-{'-'.join(str(value) for value in durations)}", avatar, 30, OPTIMIZED_VIBE_SCRIPT)
                        + ["--segments-file", str(segments), "--duration-plan-only"],
                        expect_success=False,
                    )
                    self.assertIn("deterministic request slots", result.stdout.lower())
                    self.assertIn("15, 15", result.stdout)

    def test_extremely_underfilled_30_second_script_requires_professional_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            scripts = ["第一段说明一个简短观点。", "第二段给出清楚结论。"]
            segments = root / "underfilled.json"
            segments.write_text(
                json.dumps(
                    [
                        {"duration_seconds": 15, "script": scripts[0]},
                        {"duration_seconds": 15, "script": scripts[1]},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = run_command(
                base_prepare_arguments(root / "projects", avatar, 30, "".join(scripts))
                + ["--segments-file", str(segments), "--duration-plan-only"],
                expect_success=False,
            )
            self.assertIn("at least 75%", result.stdout.lower())
            self.assertIn("professional rewrite", result.stdout.lower())

    def test_validate_project_rejects_rehashed_nonoptimal_legal_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            segments = root / "segments.json"
            segments.write_text(
                json.dumps(
                    [
                        {"duration_seconds": 15, "script": OPTIMIZED_VIBE_SEGMENTS[0]},
                        {"duration_seconds": 15, "script": OPTIMIZED_VIBE_SEGMENTS[1]},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            prepared = run_command(
                base_prepare_arguments(root / "projects", avatar, 30, OPTIMIZED_VIBE_SCRIPT)
                + ["--segments-file", str(segments)],
                expect_success=True,
            )
            plan_path = Path(json.loads(prepared.stdout)["plan"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            changed_durations = [10, 10]
            for shot, duration in zip(plan["shots"], changed_durations):
                shot["duration_seconds"] = duration
            duration_plan = plan["duration_plan"]
            duration_plan["request_duration_seconds"] = changed_durations
            duration_plan["planned_request_total_seconds"] = sum(changed_durations)
            duration_plan["planned_duration_seconds"] = sum(changed_durations)
            duration_plan["planned_delivery_overshoot_seconds"] = 0
            payload = duration_plan["duration_plan_digest_payload"]
            payload["request_duration_seconds"] = changed_durations
            for item, duration in zip(payload["segments"], changed_durations):
                item["request_duration_seconds"] = duration
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            duration_plan["duration_plan_digest"] = digest
            plan["duration_plan_digest"] = digest
            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

            validation = run_command(
                [
                    "python3",
                    str(SCRIPTS / "validate_project.py"),
                    "--plan",
                    str(plan_path),
                    "--enforce-script-pacing",
                ],
                expect_success=False,
            )
            self.assertIn("deterministic request slots [15, 15]", validation.stdout.lower())

    def test_40_seconds_uses_minimum_legal_15_15_10_combination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            result = run_command(
                base_prepare_arguments(root / "projects", avatar, 40, ""),
                expect_success=True,
            )
            plan = json.loads(Path(json.loads(result.stdout)["plan"]).read_text(encoding="utf-8"))
            self.assertEqual([shot["duration_seconds"] for shot in plan["shots"]], [15, 15, 10])
            self.assertEqual(plan["duration_plan"]["planned_request_total_seconds"], 40)
            self.assertEqual(plan["duration_plan"]["delivery_max_seconds"], 40)
            self.assertEqual(plan["duration_plan"]["segment_count"], 3)

    def test_explicit_segment_that_cannot_preserve_speech_and_pauses_inside_delivery_cap_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            script = "请用清楚自然的语速完整说完这一段重要的测试内容。"
            segments = root / "segments.json"
            segments.write_text(
                json.dumps([{"duration_seconds": 6, "script": script}], ensure_ascii=False),
                encoding="utf-8",
            )
            result = run_command(
                base_prepare_arguments(root / "projects", avatar, 5, script)
                + ["--segments-file", str(segments)],
                expect_success=True,
            )
            plan = json.loads(Path(json.loads(result.stdout)["plan"]).read_text(encoding="utf-8"))
            duration_plan = plan["duration_plan"]
            self.assertEqual(duration_plan["planned_request_total_seconds"], 6)
            self.assertEqual(duration_plan["planned_delivery_overshoot_seconds"], 1)
            self.assertAlmostEqual(duration_plan["estimated_delivery_seconds"], 5.4, places=1)
            self.assertEqual(duration_plan["delivery_fit_status"], "revise")
            self.assertFalse(plan["ready_for_paid_generation"])
            self.assertTrue(any("delivery cap" in reason.lower() for reason in plan["blocking_reasons"]))

    def test_explicit_segments_must_cover_the_complete_approved_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            approved_script = "第一句必须保留。第二句也必须完整保留。"
            segments = root / "segments.json"
            segments.write_text(
                json.dumps([{"duration_seconds": 15, "script": "第一句必须保留。"}], ensure_ascii=False),
                encoding="utf-8",
            )
            result = run_command(
                base_prepare_arguments(root / "projects", avatar, 15, approved_script)
                + ["--segments-file", str(segments)],
                expect_success=False,
            )
            self.assertIn("do not cover the complete approved script", result.stdout.lower())
            self.assertFalse((root / "projects").exists())

    def test_config_and_preflight_enforce_discrete_duration_slots(self):
        config_result = run_command(
            ["python3", str(SCRIPTS / "validate_config.py"), "--config", str(CONFIG)],
            expect_success=True,
        )
        config_data = json.loads(config_result.stdout)
        self.assertEqual(
            config_data["models"]["grok_talking_head_basic"]["allowed_durations_seconds"],
            [4, 6, 8, 10, 12, 15],
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            avatar = root / "avatar.png"
            avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
            prepared = run_command(
                base_prepare_arguments(root / "projects", avatar, 15, "这是一段内容完整、结尾自然的简短口播。"),
                expect_success=True,
            )
            plan_path = Path(json.loads(prepared.stdout)["plan"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["shots"][0]["duration_seconds"] = 14
            plan["duration_plan"]["request_duration_seconds"] = [14]
            plan["duration_plan"]["planned_duration_seconds"] = 14
            plan["duration_plan"]["planned_request_total_seconds"] = 14
            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

            preflight = run_command(
                [
                    "python3",
                    str(SCRIPTS / "preflight_project.py"),
                    "--plan",
                    str(plan_path),
                    "--config",
                    str(CONFIG),
                ],
                expect_success=False,
            )
            self.assertIn("not a supported request slot", preflight.stdout)


if __name__ == "__main__":
    unittest.main()
