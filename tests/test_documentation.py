from __future__ import annotations

from pathlib import Path
import re
import unittest
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


class DocumentationTests(unittest.TestCase):
    def test_local_markdown_links_resolve(self):
        markdown_files = [ROOT / "README.md", *sorted(DOCS.glob("*.md"))]
        missing: list[str] = []

        for source in markdown_files:
            text = source.read_text(encoding="utf-8")
            for raw_target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                target = raw_target.strip().strip("<>").split("#", 1)[0]
                if not target or target.startswith(("http://", "https://", "mailto:")):
                    continue

                target_path = (source.parent / unquote(target)).resolve()
                if not target_path.exists():
                    missing.append(
                        f"{source.relative_to(ROOT)} -> {raw_target}"
                    )

        self.assertEqual([], missing, "Broken local Markdown links:\n" + "\n".join(missing))

    def test_readme_is_concise_and_covers_safe_public_sharing(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertLessEqual(len(readme.splitlines()), 320)
        self.assertIn("Quick Tunnel 步驟", readme)
        self.assertIn("GRAFANA_ADMIN_PASSWORD", readme)
        self.assertIn("http://localhost:9093", readme)
        self.assertIn('"generate_explanation": false', readme)
        self.assertIn("PostgreSQL 不發布 host port", readme)
        self.assertIn("非官方、非商業", readme)
        self.assertIn("[docs/README.md](docs/README.md)", readme)
        self.assertNotIn("raw.githubusercontent.com/PokeAPI/sprites", readme)

    def test_documentation_index_lists_every_maintained_guide(self):
        index = (DOCS / "README.md").read_text(encoding="utf-8")

        for guide in (
            "architecture.md",
            "operations.md",
            "production.md",
            "cost-controls.md",
            "aws-artwork.md",
            "evaluation-workflow.md",
            "recommendation-feedback.md",
            "roadmap.md",
        ):
            self.assertIn(f"({guide})", index)

    def test_operations_guide_does_not_freeze_volatile_counts(self):
        operations = (DOCS / "operations.md").read_text(encoding="utf-8")

        self.assertIn("`change-me-before-use`（空白時 fallback）", operations)
        self.assertIn("production 不接受空值", operations)
        self.assertNotIn("目前 migration head 是", operations)
        self.assertIsNone(re.search(r"全部\s+\d+\s+個案例", operations))


if __name__ == "__main__":
    unittest.main()
