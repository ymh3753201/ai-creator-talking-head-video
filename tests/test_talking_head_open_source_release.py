#!/usr/bin/env python3
"""Release-readiness regressions for the public talking-head skill."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "ai-creator-talking-head-video"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))


class TalkingHeadOpenSourceReleaseTests(unittest.TestCase):
    def test_skill_metadata_is_portable_and_has_codex_ui_metadata(self):
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = skill_text.split("---", 2)[1]
        keys = {
            match.group(1)
            for line in frontmatter.splitlines()
            if (match := re.match(r"^([a-z_]+):", line))
        }
        self.assertEqual(keys, {"name", "description"})
        self.assertIn("Python 3.10+", skill_text)

        metadata_path = SKILL / "agents" / "openai.yaml"
        self.assertTrue(metadata_path.exists(), metadata_path)
        metadata = metadata_path.read_text(encoding="utf-8")
        self.assertIn('display_name: "AI Creator Talking Head Video"', metadata)
        self.assertIn("$ai-creator-talking-head-video", metadata)

    def test_standalone_skill_carries_the_repository_license(self):
        repository_license = (ROOT / "LICENSE").read_bytes()
        skill_license = SKILL / "LICENSE"
        self.assertTrue(skill_license.exists(), skill_license)
        self.assertEqual(skill_license.read_bytes(), repository_license)

    def test_local_development_artifacts_are_gitignored(self):
        gitignore = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
        required = {
            "*-workspace/",
            "docs/superpowers/",
            "inputs/",
            "production-inputs/",
            "vibe-coding-ai-agent/",
            "assets/references/",
            "dist/",
            "projects/",
        }
        self.assertTrue(required.issubset(gitignore), required - gitignore)

    def test_public_skill_has_no_personal_absolute_paths(self):
        forbidden = ("/Users/", "/Volumes/", "file://")
        for path in SKILL.rglob("*"):
            if not path.is_file() or path.suffix not in {".md", ".py", ".json", ".yaml", ".example"}:
                continue
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                self.assertNotIn(marker, text, path)

    def test_public_model_config_has_no_subtitle_mapping_or_fake_provider(self):
        config_path = SKILL / "assets" / "templates" / "model-config.example.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        serialized = json.dumps(config, ensure_ascii=False)

        self.assertNotIn("subtitle_field", serialized)
        self.assertNotIn("example.invalid", serialized)
        self.assertNotIn("replace-with-lipsync-model", serialized)
        self.assertNotIn("lipsync_audio_avatar", config["models"])

    def test_removed_legacy_files_and_symbols_do_not_return(self):
        self.assertFalse((SKILL / "evals" / "fixtures" / "first-response-atomic-primary.json").exists())
        forbidden = [
            ("_common.py", "def split_duration("),
            ("_workflow.py", "def archive_job_for_resubmission("),
            ("prepare_project.py", "def split_script_text("),
            ("workflow_engine.py", "def autonomous_policy("),
            ("workflow_engine.py", "def jobs_requiring_automatic_repair("),
            ("generate_subtitles.py", "def build_entries("),
            ("burn_subtitles.py", "DEFAULT_STYLE ="),
        ]
        for filename, marker in forbidden:
            text = (SCRIPTS / filename).read_text(encoding="utf-8")
            self.assertNotIn(marker, text, filename)

    def test_one_strict_subtitle_contract_controls_postproduction(self):
        from subtitle_policy import enabled_subtitle_contract_errors
        from finalize_postproduction import validate_postproduction_operations

        confirmed = {
            "enabled": True,
            "choice": "enabled",
            "request_source": "user_plan_confirmation",
            "confirmation_status": "confirmed",
            "provider_policy": "never_send",
            "render_policy": "postproduction_burn_only",
        }
        self.assertEqual(enabled_subtitle_contract_errors({"subtitle_plan": confirmed}), [])

        missing_provider_policy = {**confirmed}
        missing_provider_policy.pop("provider_policy")
        self.assertTrue(enabled_subtitle_contract_errors({"subtitle_plan": missing_provider_policy}))

        manifest = {
            "all_operations_user_approved": True,
            "caption_mask_applied": False,
            "operations": [{
                "type": "postproduction_subtitle_burn",
                "status": "planned",
                "paid_api_call": False,
            }],
        }
        self.assertEqual(
            validate_postproduction_operations({"subtitle_plan": confirmed, "effects_plan": {"enabled": False}}, manifest),
            [],
        )

    def test_subtitle_operation_is_marked_applied_only_after_local_outputs_exist(self):
        from finalize_postproduction import mark_subtitle_operation_applied

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subtitle = root / "final.srt"
            video = root / "final.captioned.mp4"
            subtitle.write_text("subtitle", encoding="utf-8")
            video.write_bytes(b"captioned-video")
            manifest = {
                "operations": [{
                    "type": "postproduction_subtitle_burn",
                    "status": "planned",
                    "paid_api_call": False,
                }],
            }

            updated = mark_subtitle_operation_applied(manifest, subtitle, video, "burn.audit.json")

            self.assertEqual(manifest["operations"][0]["status"], "planned")
            self.assertEqual(updated["operations"][0]["status"], "applied")
            self.assertEqual(len(updated["operations"][0]["subtitle_sha256"]), 64)
            self.assertEqual(len(updated["operations"][0]["output_video_sha256"]), 64)
            self.assertTrue(updated["subtitle_burn_completed"])


if __name__ == "__main__":
    unittest.main()
