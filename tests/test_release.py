import json
import subprocess
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

    def test_load_json_reads_one_immutable_byte_snapshot(self):
        path = self.root / "snapshot.json"
        with mock.patch.object(
            Path, "read_bytes", autospec=True, return_value=b'{"version": 1}'
        ) as read_bytes:
            self.assertEqual(release.load_json(path), {"version": 1})
        read_bytes.assert_called_once_with(path)

    def test_template_diff_carries_only_unchanged_translations(self):
        old = self.write_template("1-live.1", {
            "same": "Same", "changed": "Before", "removed": "Removed"
        })
        new = self.write_template("2-live.2", {
            "same": "Same", "changed": "After", "added": "Added"
        })
        previous = self.root / "previous.json"
        release.write_json(previous, {
            "version": "1-live.1",
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

    def test_template_diff_rejects_mismatched_previous_english(self):
        old = self.write_template("1-live.1", {"same": "Same"})
        new = self.write_template("2-live.2", {"same": "Same"})
        previous = self.root / "previous.json"
        release.write_json(previous, {
            "version": "1-live.1",
            "targetLanguage": "zh-CN",
            "keys": {"same": {"en": "Wrong source", "tr": "错误继承"}},
        })
        report, carryover = release.diff_templates(old, new, previous)
        self.assertEqual(carryover["keys"], {})
        self.assertEqual(report["unsafeCarryoverKeys"], ["same"])

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
        subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "Fixture"], check=True)
        subprocess.run(
            ["git", "-C", str(source), "config", "user.email", "fixture@example.test"],
            check=True,
        )
        subprocess.run(["git", "-C", str(source), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(source), "commit", "-m", "fixture"],
            check=True,
            capture_output=True,
        )
        commit = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        remote = self.root / "approved.git"
        subprocess.run(
            ["git", "clone", "--bare", str(source), str(remote)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(source), "remote", "add", "origin", str(remote)],
            check=True,
        )
        target = self.root / "target"
        approved_url = str(remote).removesuffix(".git")
        with mock.patch.object(release, "UPSTREAM_REPOSITORY", approved_url):
            manifest = release.sync_upstream(
                source, commit, "2026-09-09T00:00:00Z", target
            )
            copied = {
                path.name for path in (target / "upstream" / "SCMDB_LANG").iterdir()
            }
            self.assertEqual(copied, {
                "UPSTREAM_README.md", "build_lang_template.py",
                "lang-template-fixture-live.1.json",
            })
            self.assertEqual(manifest["upstreamCommit"], commit)
            templates = [
                item for item in release.validate_upstream(target)["files"]
                if "keyCount" in item
            ]
            self.assertEqual(templates[0]["keyCount"], 1)

    def test_sync_rejects_non_git_source(self):
        source = self.root / "source"
        source.mkdir()
        with self.assertRaisesRegex(release.ReleaseError, "cannot verify upstream Git checkout"):
            release.sync_upstream(source, "a" * 40, "2026-09-09T00:00:00Z", self.root / "target")

    def test_candidate_output_cannot_target_repository_dist(self):
        with self.assertRaisesRegex(release.ReleaseError, "must stay under"):
            release.build_release(
                self.root / "missing-config.json",
                {},
                release.REPO_ROOT,
                release.REPO_ROOT,
            )
        for unsafe in ("../live.json", "nested/live.json", "C:\\live.json"):
            with self.assertRaises(release.ReleaseError):
                release._safe_output_name(unsafe, "alias")

    def test_checked_in_live_release_matches_current_output_contract(self):
        config = release.load_json(release.REPO_ROOT / "release" / "live.json")
        manifest = release.load_json(release.REPO_ROOT / "dist" / "manifest.json")
        self.assertEqual(manifest["schemaVersion"], 2)
        self.assertEqual(manifest["channel"], config["channel"])
        self.assertEqual(manifest["status"], "candidate")
        self.assertEqual(
            manifest["blocked"],
            release.load_blocked_releases(config, release.REPO_ROOT),
        )

        artifacts = {item["variant"]: item for item in manifest["artifacts"]}
        for item in [*manifest["artifacts"], *manifest["aliases"]]:
            info = release.file_info(release.REPO_ROOT / item["path"])
            self.assertEqual(info["sha256"], item["sha256"])
            self.assertEqual(info["byteLength"], item["byteLength"])

        for variant, source in config["sources"].items():
            report = release.load_json(
                release.REPO_ROOT / "reports" / config["build"] / f"{variant}.json"
            )
            self.assertEqual(report["schemaVersion"], 2)
            self.assertEqual(report["build"], config["build"])
            self.assertEqual(report["source"], source)
            self.assertEqual(report["gates"], {"status": "passed", "failures": []})
            self.assertEqual(report["artifact"], artifacts[variant])
            self.assertEqual(report["artifact"]["variant"], variant)
            self.assertEqual(report["uiSidecar"]["path"], config["uiSidecar"])

    def test_blocked_release_reports_are_hash_pinned(self):
        report_path = self.root / "reports" / "ptu.json"
        report = {
            "schemaVersion": 1,
            "status": "blocked",
            "variant": "ptu",
            "requestedBuild": "fixture-ptu.1",
        }
        release.write_json(report_path, report)
        config = {
            "variants": {"full": {}},
            "blocked": [{
                "variant": "ptu",
                "report": "reports/ptu.json",
                "sha256": release.file_info(report_path)["sha256"],
            }],
        }
        self.assertEqual(
            release.load_blocked_releases(config, self.root),
            [{
                "variant": "ptu",
                "build": "fixture-ptu.1",
                "report": "reports/ptu.json",
                "reportSchemaVersion": 1,
                "sha256": release.file_info(report_path)["sha256"],
            }],
        )
        report["reason"] = "changed"
        release.write_json(report_path, report)
        with self.assertRaisesRegex(release.ReleaseError, "blocked report SHA-256 mismatch"):
            release.load_blocked_releases(config, self.root)

        for unsafe in (
            "reports/ptu.json.",
            "reports/ptu.json ",
            "reports\\ptu.json",
            "reports/../ptu.json",
            "reports/CON",
            "reports/com1.json",
            "reports/NUL.txt",
        ):
            config["blocked"][0]["report"] = unsafe
            with self.assertRaisesRegex(release.ReleaseError, "canonical POSIX path"):
                release.load_blocked_releases(config, self.root)

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
