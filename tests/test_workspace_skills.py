import json
import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".github" / "skills" / "handwriting-grading"


class WorkspaceSkillTests(unittest.TestCase):
    def test_workspace_discovers_skill_without_symlinks(self):
        for directory in (SKILL.parent.parent, SKILL.parent, SKILL):
            with self.subTest(directory=directory):
                self.assertTrue(directory.is_dir())
                self.assertFalse(directory.is_symlink())
        entry_point = SKILL / "SKILL.md"
        self.assertIn(entry_point, list(SKILL.parent.glob("*/SKILL.md")))
        frontmatter = entry_point.read_text(encoding="utf-8").split("---", 2)
        self.assertEqual(frontmatter[0], "")
        metadata = yaml.safe_load(frontmatter[1])
        self.assertEqual(metadata["name"], SKILL.name)
        self.assertIsInstance(metadata["description"], str)
        self.assertTrue(metadata["description"].strip())
        registry = json.loads((ROOT / ".agents" / "skills.json").read_text(encoding="utf-8"))
        registered_skills = [
            path
            for entry in registry["entries"]
            for path in (ROOT / entry["path"]).glob("*/SKILL.md")
        ]
        self.assertIn(entry_point, registered_skills)

    def test_skill_resources_and_relative_links_survive_workspace_layout(self):
        references = SKILL / "references"
        self.assertTrue(references.is_dir())
        self.assertFalse(references.is_symlink())
        for document in SKILL.rglob("*.md"):
            self.assertFalse(document.is_symlink())
            text = document.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^\]]+\]\(([^)\s]+)\)", text):
                parsed = urlsplit(target)
                if parsed.scheme or not parsed.path:
                    continue
                with self.subTest(document=document, target=target):
                    self.assertTrue((document.parent / parsed.path).is_file())
