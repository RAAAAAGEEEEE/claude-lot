"""scripts/installer.sh : installe le dernier commit, refuse une copie installée modifiée hors dépôt."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


def git(d, *args):
    return subprocess.run(["git", "-C", str(d), *args], check=True, capture_output=True, text=True).stdout


class Installer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.depot = self.d / "depot"
        (self.depot / "scripts").mkdir(parents=True)
        shutil.copy(RACINE / "scripts" / "installer.sh", self.depot / "scripts")
        shutil.copy(RACINE / "scripts" / "claude_lot.py", self.depot / "scripts")
        git(self.depot, "init", "-q")
        git(self.depot, "add", "scripts/installer.sh", "scripts/claude_lot.py")
        git(self.depot, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "v1")
        self.cible = self.d / "bin" / "claude-lot"
        self.cible.parent.mkdir()
        self.etat = self.d / "etat" / "installe.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def installer(self, *args):
        env = {**os.environ, "CLAUDE_LOT_CIBLE": str(self.cible), "CLAUDE_LOT_INSTALLE": str(self.etat),
               "CLAUDE_LOT_SANS_TESTS": "1"}
        return subprocess.run(["bash", str(self.depot / "scripts" / "installer.sh"), *args],
                              capture_output=True, text=True, env=env)

    def test_premiere_installation_sans_cible(self):
        r = self.installer()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.cible.read_bytes(), (self.depot / "scripts" / "claude_lot.py").read_bytes())
        self.assertTrue(self.etat.read_text().startswith(git(self.depot, "rev-parse", "HEAD").strip()))

    def test_cible_inconnue_refusee_sans_adopter(self):
        self.cible.write_text("ancienne copie\n")
        r = self.installer()
        self.assertEqual(r.returncode, 1)
        self.assertIn("--adopter", r.stderr)
        self.assertEqual(self.cible.read_text(), "ancienne copie\n")
        r = self.installer("--adopter")
        self.assertEqual(r.returncode, 0, r.stderr)
        sauvegardes = list(self.cible.parent.glob("claude-lot.bak-*"))
        self.assertEqual(len(sauvegardes), 1)
        self.assertEqual(sauvegardes[0].read_text(), "ancienne copie\n")

    def test_copie_installee_modifiee_hors_depot_refusee(self):
        self.assertEqual(self.installer().returncode, 0)
        with open(self.cible, "a") as f:
            f.write("# retouche à la main\n")
        r = self.installer()
        self.assertEqual(r.returncode, 1)
        self.assertIn("diffère du commit installé", r.stderr)
        self.assertIn("retouche", self.cible.read_text())

    def test_copie_de_travail_non_commitee_refusee(self):
        with open(self.depot / "scripts" / "claude_lot.py", "a") as f:
            f.write("# brouillon\n")
        r = self.installer()
        self.assertEqual(r.returncode, 1)
        self.assertIn("non commitées", r.stderr)
        self.assertFalse(self.cible.exists())

    def test_mise_a_jour_normale(self):
        self.assertEqual(self.installer().returncode, 0)
        with open(self.depot / "scripts" / "claude_lot.py", "a") as f:
            f.write("# v2\n")
        git(self.depot, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qam", "v2")
        r = self.installer()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.cible.read_text().endswith("# v2\n"))


if __name__ == "__main__":
    unittest.main()
