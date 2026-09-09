import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import release, ui_sidecar


class UiSidecarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.template = {
            "version": "fixture-live.1",
            "keyCount": 3,
            "keys": {
                "scmdb_ui_fab_filter": "Filter",
                "scmdb_ui_tag_new_tt": "Added in patch {patch}",
                "game_key": "Game text",
            },
        }
        self.source = {
            "schemaVersion": 1,
            "repository": "https://github.com/example/scmdb-zh-extension",
            "commit": "1" * 40,
            "path": "src/extension/scmdb-ui/dictionary.ts",
            "dictionaryVersion": "2026.09.0",
            "entries": [
                {
                    "id": "filter.label",
                    "sourceText": "Filter",
                    "translation": "筛选",
                    "context": "filter",
                    "pageFamilies": ["fabricator"],
                    "status": "active",
                    "review": {
                        "status": "approved",
                        "reviewedBy": "fixture review",
                        "reviewedAt": "2026-09-08",
                    },
                },
                {
                    "id": "unmatched",
                    "sourceText": "No exact template source",
                    "translation": "不会迁移",
                    "context": "view",
                    "pageFamilies": ["fabricator"],
                    "status": "active",
                    "review": {
                        "status": "approved",
                        "reviewedBy": "fixture review",
                        "reviewedAt": "2026-09-08",
                    },
                },
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_migration_uses_exact_source_and_context_only(self):
        sidecar, coverage = ui_sidecar.build_migration(self.template, self.source)

        self.assertEqual(sidecar["keys"]["scmdb_ui_fab_filter"]["tr"], "筛选")
        self.assertNotIn("scmdb_ui_tag_new_tt", sidecar["keys"])
        self.assertEqual(coverage["summary"]["migrated"], 1)
        self.assertEqual(coverage["summary"]["englishFallback"], 1)
        self.assertEqual(coverage["summary"]["sourceUnmatched"], 1)
        self.assertEqual(
            coverage["entries"][1]["tokens"],
            [{"kind": "curly_placeholder", "value": "{patch}"}],
        )

    def test_migration_rejects_context_mismatch(self):
        self.source["entries"][0]["pageFamilies"] = ["missions"]
        sidecar, coverage = ui_sidecar.build_migration(self.template, self.source)

        self.assertEqual(sidecar["keys"], {})
        entry = next(item for item in coverage["entries"] if item["key"] == "scmdb_ui_fab_filter")
        self.assertEqual(entry["reason"], "context_mismatch")

    def test_migration_rejects_token_mismatch(self):
        self.source["entries"][0].update({
            "id": "tag.new",
            "sourceText": "Added in patch {patch}",
            "translation": "在补丁中新增",
            "context": "view",
            "pageFamilies": ["missions"],
        })
        sidecar, coverage = ui_sidecar.build_migration(self.template, self.source)

        self.assertEqual(sidecar["keys"], {})
        entry = next(item for item in coverage["entries"] if item["key"] == "scmdb_ui_tag_new_tt")
        self.assertEqual(entry["reason"], "token_mismatch")

    def test_migration_reports_conflicting_exact_sources(self):
        duplicate = dict(self.source["entries"][0])
        duplicate["id"] = "filter.label.duplicate"
        self.source["entries"].append(duplicate)
        sidecar, coverage = ui_sidecar.build_migration(self.template, self.source)

        self.assertEqual(sidecar["keys"], {})
        entry = next(item for item in coverage["entries"] if item["key"] == "scmdb_ui_fab_filter")
        self.assertEqual(entry["reason"], "conflicting_exact_source")
        self.assertEqual(entry["sourceEntryIds"], ["filter.label", "filter.label.duplicate"])

    def test_incompatible_exact_source_does_not_create_false_conflict(self):
        incompatible = dict(self.source["entries"][0])
        incompatible["id"] = "filter.label.missions"
        incompatible["pageFamilies"] = ["missions"]
        self.source["entries"].append(incompatible)

        sidecar, coverage = ui_sidecar.build_migration(self.template, self.source)

        self.assertEqual(sidecar["keys"]["scmdb_ui_fab_filter"]["tr"], "筛选")
        entry = next(item for item in coverage["entries"] if item["key"] == "scmdb_ui_fab_filter")
        self.assertEqual(entry["status"], "migrated")
        self.assertEqual(entry["sourceEntryIds"], ["filter.label"])

    def test_reviewed_source_rejects_whitespace_translation(self):
        self.source["entries"][0]["translation"] = "  "
        with self.assertRaisesRegex(release.ReleaseError, "translation is required"):
            ui_sidecar.build_migration(self.template, self.source)

    def test_reviewed_source_requires_supported_schema(self):
        self.source["schemaVersion"] = 2
        with self.assertRaisesRegex(release.ReleaseError, "schemaVersion must be 1"):
            ui_sidecar.build_migration(self.template, self.source)

    def test_percent_format_tokens_are_protected(self):
        tokens = ["%s", "%1$s", "%02d", "%1.2f", "%(name)s", "%%", "%name%"]
        for token in tokens:
            with self.subTest(token=token):
                valid = release.validate_translation_tokens(
                    f"Value {token}", f"值 {token}"
                )
                self.assertTrue(valid["valid"])
                missing = release.validate_translation_tokens(
                    f"Value {token}", "值"
                )
                self.assertFalse(missing["valid"])
        self.assertTrue(
            release.validate_translation_tokens("Quality 50%", "品质 50%")["valid"]
        )
        self.assertFalse(
            release.validate_translation_tokens("Value %02q", "值 %02q")["valid"]
        )
        for source, translated in (
            ("Value %?", "值"),
            ("Value %{count}", "值 {count}"),
            ("Value %[name]", "值 [name]"),
        ):
            with self.subTest(source=source):
                self.assertFalse(
                    release.validate_translation_tokens(source, translated)["valid"]
                )
        self.assertTrue(
            release.validate_translation_tokens(
                "Ace Pilot - {chance}% spawn chance",
                "王牌飞行员 - {chance}% 出现概率",
            )["valid"]
        )
        self.assertFalse(
            release.validate_translation_tokens(
                "First %s then %d", "先 %d 再 %s"
            )["valid"]
        )
        self.assertTrue(
            release.validate_translation_tokens(
                "First %1$s then %2$d", "先 %2$d 再 %1$s"
            )["valid"]
        )

    def test_config_paths_cannot_escape_repository(self):
        with self.assertRaisesRegex(release.ReleaseError, "escapes the repository"):
            release._resolve_config_path({"path": "../outside.json"}, "path", self.root)
        with self.assertRaisesRegex(release.ReleaseError, "repository-relative"):
            release._resolve_config_path(
                {"path": str((self.root / "absolute.json").resolve())}, "path", self.root
            )

    def test_cli_rejects_output_path_collisions_before_writing(self):
        template_path = self.root / "lang-template-fixture-live.1.json"
        release.write_json(template_path, self.template)
        source_path = self.root / "source.json"
        release.write_json(source_path, self.source)
        original_source = source_path.read_bytes()

        result = ui_sidecar.main([
            "--template", str(template_path),
            "--source", str(source_path),
            "--sidecar", str(source_path),
            "--coverage", str(self.root / "coverage.json"),
        ])
        self.assertEqual(result, 2)
        self.assertEqual(source_path.read_bytes(), original_source)

        shared_output = self.root / "shared.json"
        result = ui_sidecar.main([
            "--template", str(template_path),
            "--source", str(source_path),
            "--sidecar", str(shared_output),
            "--coverage", str(shared_output),
        ])
        self.assertEqual(result, 2)
        self.assertFalse(shared_output.exists())

        result = ui_sidecar.main([
            "--template", str(template_path),
            "--source", str(source_path),
            "--sidecar", str(self.root / "result.json"),
            "--coverage", str(self.root / "result.json."),
        ])
        self.assertEqual(result, 2)
        self.assertFalse((self.root / "result.json").exists())

    def test_atomic_outputs_preserve_existing_files_when_second_backup_fails(self):
        sidecar = self.root / "sidecar.json"
        coverage = self.root / "coverage.json"
        sidecar.write_text("old sidecar", encoding="utf-8")
        coverage.write_text("old coverage", encoding="utf-8")
        original_replace = Path.replace

        def fail_second_backup(path, target):
            if path == coverage and str(target).endswith(".bak"):
                raise OSError("locked coverage")
            return original_replace(path, target)

        with mock.patch.object(Path, "replace", autospec=True, side_effect=fail_second_backup):
            with self.assertRaisesRegex(OSError, "locked coverage"):
                ui_sidecar._write_outputs([
                    (sidecar, {"new": "sidecar"}),
                    (coverage, {"new": "coverage"}),
                ])
        self.assertEqual(sidecar.read_text(encoding="utf-8"), "old sidecar")
        self.assertEqual(coverage.read_text(encoding="utf-8"), "old coverage")

    def test_backup_cleanup_failure_does_not_rollback_committed_outputs(self):
        sidecar = self.root / "sidecar.json"
        coverage = self.root / "coverage.json"
        release.write_json(sidecar, {"old": "sidecar"})
        release.write_json(coverage, {"old": "coverage"})
        original_unlink = Path.unlink

        def fail_backup_cleanup(path, *args, **kwargs):
            if str(path).endswith(".bak"):
                raise OSError("locked backup")
            return original_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", autospec=True, side_effect=fail_backup_cleanup):
            ui_sidecar._write_outputs([
                (sidecar, {"new": "sidecar"}),
                (coverage, {"new": "coverage"}),
            ])
        self.assertEqual(release.load_json(sidecar), {"new": "sidecar"})
        self.assertEqual(release.load_json(coverage), {"new": "coverage"})

    def test_directory_replace_preserves_original_when_backup_rename_fails(self):
        staged = self.root / "staged"
        target = self.root / "target"
        staged.mkdir()
        target.mkdir()
        (staged / "value.txt").write_text("new", encoding="utf-8")
        (target / "value.txt").write_text("old", encoding="utf-8")
        original_replace = Path.replace

        def fail_original_backup(path, replacement):
            if path == target:
                raise OSError("locked target")
            return original_replace(path, replacement)

        with mock.patch.object(Path, "replace", autospec=True, side_effect=fail_original_backup):
            with self.assertRaisesRegex(OSError, "locked target"):
                release._replace_output_directory(staged, target)
        self.assertEqual((target / "value.txt").read_text(encoding="utf-8"), "old")
        self.assertEqual((staged / "value.txt").read_text(encoding="utf-8"), "new")

    def test_release_loader_validates_source_tokens_and_unknown_keys(self):
        sidecar, _coverage = ui_sidecar.build_migration(self.template, self.source)
        path = self.root / "sidecar.json"
        release.write_json(path, sidecar)

        loaded, coverage = release.load_project_ui_sidecar(path, self.template, "zh-CN", self.root)
        self.assertEqual(loaded, {"scmdb_ui_fab_filter": "筛选"})
        self.assertEqual(coverage["translatedCount"], 1)
        self.assertEqual(coverage["englishFallbackKeys"], ["scmdb_ui_tag_new_tt"])

        sidecar["keys"]["scmdb_ui_unknown"] = sidecar["keys"]["scmdb_ui_fab_filter"]
        release.write_json(path, sidecar)
        with self.assertRaisesRegex(release.ReleaseError, "unknown UI sidecar key"):
            release.load_project_ui_sidecar(path, self.template, "zh-CN", self.root)

    def test_release_loader_rejects_missing_tokens_and_source_change(self):
        sidecar, _coverage = ui_sidecar.build_migration(self.template, self.source)
        path = self.root / "sidecar.json"
        token_entry = {
            "en": "Added in patch {patch}",
            "tr": "在补丁中新增",
            "source": sidecar["keys"]["scmdb_ui_fab_filter"]["source"],
        }
        sidecar["keys"] = {"scmdb_ui_tag_new_tt": token_entry}
        release.write_json(path, sidecar)
        with self.assertRaisesRegex(release.ReleaseError, "token mismatch"):
            release.load_project_ui_sidecar(path, self.template, "zh-CN", self.root)

        token_entry["tr"] = "在补丁 {patch} 中新增"
        token_entry["en"] = "Changed source {patch}"
        release.write_json(path, sidecar)
        with self.assertRaisesRegex(release.ReleaseError, "English source changed"):
            release.load_project_ui_sidecar(path, self.template, "zh-CN", self.root)

    def test_empty_reviewed_source_generates_complete_fallback_matrix(self):
        self.source["entries"] = []
        sidecar, coverage = ui_sidecar.build_migration(self.template, self.source)

        self.assertEqual(sidecar["keys"], {})
        self.assertEqual(coverage["summary"]["templateUiKeys"], 2)
        self.assertEqual(coverage["summary"]["migrated"], 0)
        self.assertEqual(coverage["summary"]["englishFallback"], 2)
        self.assertEqual(
            [entry["key"] for entry in coverage["entries"]],
            ["scmdb_ui_fab_filter", "scmdb_ui_tag_new_tt"],
        )

    def test_release_gate_rebuilds_migration_from_reviewed_source(self):
        sidecar, coverage = ui_sidecar.build_migration(self.template, self.source)
        release.write_json(self.root / "source.json", self.source)
        release.write_json(self.root / "sidecar.json", sidecar)
        release.write_json(self.root / "coverage.json", coverage)
        config = {
            "targetLanguage": "zh-CN",
            "uiSidecar": "sidecar.json",
            "uiReviewedSource": "source.json",
            "uiCoverageReport": "coverage.json",
        }

        loaded, report = release.load_checked_ui_migration(config, self.template, self.root)
        self.assertEqual(loaded, {"scmdb_ui_fab_filter": "筛选"})
        self.assertEqual(report["migrationSummary"]["migrated"], 1)

        sidecar["keys"]["scmdb_ui_fab_filter"]["tr"] = "未经审校的替换"
        release.write_json(self.root / "sidecar.json", sidecar)
        with self.assertRaisesRegex(
            release.ReleaseError, "does not match the reviewed source migration"
        ):
            release.load_checked_ui_migration(config, self.template, self.root)

    def test_checked_in_live_sidecar_and_coverage_are_deterministic(self):
        root = release.REPO_ROOT
        template = release.validate_template(
            root / "upstream/SCMDB_LANG/lang-template-4.10.0-live.12568521.json"
        )
        source = release.load_json(
            root / "ui/reviewed/scmdb-zh-extension-2026.09.0.json"
        )
        sidecar, coverage = ui_sidecar.build_migration(template, source)

        self.assertEqual(
            sidecar,
            release.load_json(root / "ui/scmdb_ui_zh-CN.json"),
        )
        self.assertEqual(
            coverage,
            release.load_json(
                root / "reports/4.10.0-live.12568521/ui-sidecar-coverage.json"
            ),
        )
        self.assertEqual(coverage["summary"]["templateUiKeys"], 59)
        self.assertEqual(coverage["summary"]["reviewedEntries"], 16)
        self.assertEqual(coverage["summary"]["migrated"], 0)
        self.assertEqual(coverage["summary"]["englishFallback"], 59)


if __name__ == "__main__":
    unittest.main()
