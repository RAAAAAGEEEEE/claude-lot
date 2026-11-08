"""Nettoyage du scope d'un lot à la fin du processus claude (scripts/claude_lot.py)."""
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("claude_lot", RACINE / "scripts" / "claude_lot.py")
cl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cl)


class TestScope(unittest.TestCase):
    def test_regex_ne_vise_que_les_scopes_de_lot(self):
        bons = ["/tachesclaude.slice/tache-claude-123.scope", "/x/tachesclaude.slice/tache-claude-9.scope"]
        mauvais = ["/system.slice/siteservi-api.service", "/system.slice/cron.service",
                   "/user.slice/session-1.scope", "/tachesclaude.slice/autre.scope"]
        for c in bons:
            self.assertTrue(cl.SCOPE_LOT.match(c), c)
        for c in mauvais:
            self.assertFalse(cl.SCOPE_LOT.match(c), c)

    def test_pids_du_scope_exclut_soi_et_lit_cgroup_procs(self):
        with tempfile.TemporaryDirectory() as d:
            scope = "/tachesclaude.slice/tache-claude-1.scope"
            p = Path(d + scope)
            p.mkdir(parents=True)
            (p / "cgroup.procs").write_text(f"{os.getpid()}\n4242\n")
            os.environ["CLAUDE_LOT_CGROUP_RACINE"] = d
            try:
                self.assertEqual(cl.pids_du_scope(scope), [4242])
            finally:
                del os.environ["CLAUDE_LOT_CGROUP_RACINE"]

    def test_code_de_sortie_propage_sans_scope(self):
        # hors scope systemd : aucun nettoyage, le code du fils est rendu tel quel
        code = cl.executer_lot({"journal": "/dev/null"}, "t", ["bash", "-c", "exit 7"])
        self.assertEqual(code, 7)


if __name__ == "__main__":
    unittest.main()
