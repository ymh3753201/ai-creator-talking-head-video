#!/usr/bin/env python3
"""Regression tests for minimum-segment and zero-paid-repair policy contracts."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "ai-creator-talking-head-video"
VALIDATOR = SKILL / "scripts" / "validate_first_response_trace.py"
FIXTURES = SKILL / "evals" / "fixtures"


def validate_fixture(name: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        ["python3", str(VALIDATOR), str(FIXTURES / name)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result, json.loads(result.stdout)


class TalkingHeadPolicyContractTests(unittest.TestCase):
    def test_valid_trace_uses_local_postprocess_and_base_only_paid_calls(self):
        result, report = validate_fixture("two-confirmation-valid.json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(report["status"], "pass")

    def test_trace_rejects_paid_repair_action_and_calls_above_base(self):
        result, report = validate_fixture("two-confirmation-paid-repair-attempt.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("paid_repair_action_forbidden", report["issues"])
        self.assertIn("paid_calls_exceed_base", report["issues"])

    def test_policy_docs_forbid_unsupported_slots_and_paid_regeneration(self):
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        duration_text = (SKILL / "references" / "script-duration-and-pacing.md").read_text(encoding="utf-8")
        speech_text = (SKILL / "references" / "speech-acceptance.md").read_text(encoding="utf-8")
        combined = "\n".join((skill_text, duration_text, speech_text))

        self.assertIn("15s + 15s", combined)
        self.assertIn("allowed_durations_seconds", combined)
        self.assertIn("repair_reserve=0", combined)
        self.assertIn("per_shot_repair_limit=0", combined)
        self.assertIn("never submit a shot a second time", combined)
        self.assertNotIn("allow results such as 14s + 13s", combined)
        self.assertIn("14s + 13s + 12s` is invalid", combined)

    def test_no_cost_postprocess_has_a_separate_manifest_template(self):
        template_path = SKILL / "assets" / "templates" / "postprocess-manifest.example.json"
        template = json.loads(template_path.read_text(encoding="utf-8"))
        self.assertEqual(template["paid_video_requests_added"], 0)
        self.assertEqual(template["paid_submission_attempts_before"], template["paid_submission_attempts_after"])
        self.assertTrue(all(operation["paid_api_call"] is False for operation in template["operations"]))


if __name__ == "__main__":
    unittest.main()
