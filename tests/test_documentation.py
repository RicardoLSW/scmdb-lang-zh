import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE_COMMIT = "1748646cb4cb25e2d8578dfb628541e74143028b"


class DocumentationTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "release" / "live.json").read_text(encoding="utf-8"))
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.dist_readme = (ROOT / "dist" / "README.md").read_text(encoding="utf-8")

    def test_readme_lists_every_stable_alias_and_versioned_artifact(self):
        build = self.config["build"]
        raw_urls = self.config["rawUrls"]
        for variant, details in self.config["variants"].items():
            for alias in details["aliases"]:
                self.assertIn(raw_urls[f"dist/{alias}"], self.readme)
            versioned_url = (
                "https://raw.githubusercontent.com/RicardoLSW/scmdb-lang-zh/"
                f"{RELEASE_COMMIT}/dist/{build}/{details['artifact']}"
            )
            self.assertIn(versioned_url, self.readme, variant)

    def test_docs_keep_ptu_unpublished_and_separate_clear_contracts_explicit(self):
        self.assertIn("PTU 稳定 URL 尚未发布", self.readme)
        self.assertIn("缺失 1,042 个 keyed 条目", self.readme)
        self.assertIn("Clear/Disable translation", self.readme)
        self.assertIn("清除扩展本地 `global.ini`", self.readme)
        self.assertIn("不存在可用的 `ptu.json`", self.dist_readme)


if __name__ == "__main__":
    unittest.main()
