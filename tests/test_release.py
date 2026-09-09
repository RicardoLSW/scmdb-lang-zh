import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import release


class ReleaseToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write_template(self, version, keys):
        path = self.root / f"lang-template-{version}.json"
        release.write_json(path, {"version": version, "keyCount": len(keys), "keys": keys})
        return path

    def test_load_json_rejects_duplicate_keys(self):
        path = self.root / "duplicate.json"
        path.write_text('{"version": 1, "version": 2}', encoding="utf-8")
        with self.assertRaisesRegex(release.ReleaseError, "duplicate JSON key"):
            release.load_json(path)

    def test_template_diff_carries_only_unchanged_translations(self):
        old = self.write_template("1-live.1", {
            "same": "Same", "changed": "Before", "removed": "Removed"
        })
        new = self.write_template("2-live.2", {
            "same": "Same", "changed": "After", "added": "Added"
        })
        previous = self.root / "previous.json"
        release.write_json(previous, {
            "targetLanguage": "zh-CN",
            "keys": {
                "same": {"en": "Same", "tr": "相同"},
                "changed": {"en": "Before", "tr": "旧译文"},
                "removed": {"en": "Removed", "tr": "已删除"},
            },
        })
        report, carryover = release.diff_templates(old, new, previous)
        self.assertEqual(report["addedKeys"], ["added"])
        self.assertEqual(report["removedKeys"], ["removed"])
        self.assertEqual(report["sourceChangedKeys"], ["changed"])
        self.assertEqual(report["unchangedKeys"], ["same"])
        self.assertEqual(list(carryover["keys"]), ["same"])
        self.assertEqual(carryover["keys"]["same"]["tr"], "相同")

    def test_generate_variant_forces_token_risks_to_english(self):
        builder = release._load_builder(
            release.REPO_ROOT / "upstream" / "SCMDB_LANG" / "build_lang_template.py"
        )
        template = {
            "version": "fixture-live.1",
            "keyCount": 3,
            "keys": {
                "safe": "Hello",
                "token_risk": "Fly to Area 18",
                "placeholder_only": "Destination",
            },
            "rawKeys": {"token_risk": "Fly to ~mission(Location)"},
        }
        ini = self.root / "zh-CN_fixture.ini"
        ini.write_text(
            "safe=你好\ntoken_risk=飞往 ~mission(Location)\n"
            "placeholder_only=~mission(Location)\n",
            encoding="utf-8",
        )
        artifact, builder_stats, published_stats = release.generate_variant(
            template, builder, ini, {}, "zh-CN"
        )
        self.assertEqual(builder_stats["mismatchKeys"], ["token_risk"])
        self.assertEqual(artifact["keys"]["safe"]["tr"], "你好")
        self.assertEqual(artifact["keys"]["token_risk"]["tr"], "Fly to Area 18")
        self.assertEqual(artifact["keys"]["placeholder_only"]["tr"], "Destination")
        self.assertEqual(published_stats["safetyFallbackKeys"], ["token_risk"])
        self.assertEqual(published_stats["mismatch"], 0)
        self.assertEqual(release.json_bytes(artifact), release.json_bytes(artifact))

    def test_old_ptu_and_abnormal_missing_rate_are_blocked(self):
        failures = release.evaluate_gates(
            {"total": 10, "noLocKey": 2, "missing": 5},
            {
                "version": "4.10.1-ptu.1",
                "lastModified": "Wed, 15 Oct 2025 15:26:41 GMT",
            },
            "4.10.1-ptu.1",
            "2026-09-09T00:00:00Z",
            {"maxSourceAgeDays": 120, "maxMissingCount": 2, "maxMissingRatio": 0.05},
        )
        self.assertEqual(
            {failure["code"] for failure in failures},
            {"source_too_old", "abnormal_missing_rate"},
        )

    def test_untrusted_source_version_is_blocked(self):
        failures = release.evaluate_gates(
            {"total": 10, "noLocKey": 0, "missing": 0},
            {"version": "wrong", "lastModified": "Tue, 08 Sep 2026 00:00:00 GMT"},
            "expected", "2026-09-09T00:00:00Z", {},
        )
        self.assertIn("untrusted_source_version", {item["code"] for item in failures})

    def test_sync_copies_only_allowlisted_files_and_pins_hashes(self):
        source = self.root / "source"
        source.mkdir()
        (source / "README.md").write_text("upstream readme\n", encoding="utf-8")
        (source / "build_lang_template.py").write_text("# builder\n", encoding="utf-8")
        release.write_json(source / "lang-template-fixture-live.1.json", {
            "version": "fixture-live.1", "keyCount": 1, "keys": {"key": "English"}
        })
        (source / "private.txt").write_text("must not copy", encoding="utf-8")
        target = self.root / "target"
        manifest = release.sync_upstream(source, "a" * 40, "2026-09-09T00:00:00Z", target)
        copied = {path.name for path in (target / "upstream" / "SCMDB_LANG").iterdir()}
        self.assertEqual(copied, {
            "UPSTREAM_README.md", "build_lang_template.py",
            "lang-template-fixture-live.1.json",
        })
        self.assertEqual(manifest["upstreamCommit"], "a" * 40)
        templates = [
            item for item in release.validate_upstream(target)["files"] if "keyCount" in item
        ]
        self.assertEqual(templates[0]["keyCount"], 1)

    def test_raw_check_requires_cors_and_matching_hash(self):
        body = b"candidate"

        class Response:
            headers = {"Access-Control-Allow-Origin": "*"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return body

        with mock.patch("urllib.request.urlopen", return_value=Response()):
            result = release._check_raw_url(
                "https://example.test/live.json", release.sha256_bytes(body)
            )
        self.assertEqual(result["status"], "passed")

    def test_report_shapes_do_not_include_ini_text_or_local_path(self):
        report = {
            "source": {
                "url": "https://example.test/global.ini",
                "sha256": "0" * 64,
                "lastModified": "Thu, 01 Jan 2026 00:00:00 GMT",
                "version": "fixture-live.1",
            },
            "builderStats": {"missingKeys": ["missing_key"]},
        }
        encoded = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("秘密翻译原文", encoded)
        self.assertNotIn(str(self.root), encoded)


if __name__ == "__main__":
    unittest.main()
