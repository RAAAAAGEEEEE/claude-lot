"""Structure du skill : fichiers attendus, versions concordantes, rien de privé."""

import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


class Structure(unittest.TestCase):
    def test_fichiers_presents(self):
        for f in ("SKILL.md", "README.md", "LICENSE", "CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md",
                  "scripts/claude_lot.py", "scripts/sonde-quota.sh", "examples/claude-lot.conf",
                  "docs/INSTALLATION.md", "docs/USAGE.md", "docs/CONFIGURATION.md", "docs/ARCHITECTURE.md",
                  "docs/LIMITATIONS.md", "docs/TROUBLESHOOTING.md", "docs/PRIVACY_AND_SECURITY.md"):
            with self.subTest(f=f):
                self.assertTrue((RACINE / f).is_file())

    def test_entete_du_skill(self):
        texte = (RACINE / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(texte.startswith("---\nname: claude-lot\n"))
        self.assertIn("description:", texte)
        self.assertIn("### 0. Cadrage", texte)

    def test_versions_concordantes(self):
        skill = re.search(r'version: "([\d.]+)"', (RACINE / "SKILL.md").read_text(encoding="utf-8")).group(1)
        script = re.search(r'VERSION = "([\d.]+)"', (RACINE / "scripts/claude_lot.py").read_text(encoding="utf-8")).group(1)
        journal = re.search(r"## \[([\d.]+)\]", (RACINE / "CHANGELOG.md").read_text(encoding="utf-8")).group(1)
        self.assertEqual(skill, script)
        self.assertEqual(skill, journal)

    def test_aucun_chemin_ni_adresse_privee(self):
        interdits = re.compile(r"/root/|@gmail|@[a-z0-9-]+\.(com|fr)\b|sk-ant-|oauth_token", re.I)
        for f in RACINE.rglob("*"):
            if f.is_file() and ".git" not in f.parts and f.suffix in (".md", ".py", ".sh", ".conf", ".yml", ""):
                if f.name == "test_skill_structure.py":
                    continue
                with self.subTest(f=str(f.relative_to(RACINE))):
                    self.assertIsNone(interdits.search(f.read_text(encoding="utf-8", errors="replace")))


if __name__ == "__main__":
    unittest.main()
