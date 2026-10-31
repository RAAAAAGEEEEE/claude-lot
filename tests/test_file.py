"""Tests de la file de tâches (`claude-lot file`) : quota par jour, garde, limite d'usage, lignes invalides."""

import io
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "scripts"))
import claude_lot  # noqa: E402


class FileDeTaches(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.d = Path(self.dossier.name)
        self.t = int(time.time())
        self.mesure = self.d / "mesure.txt"
        self.poser(10, 10)
        self.sonde = self.d / "sonde.sh"
        self.sonde.write_text(f"#!/bin/sh\ncat {self.mesure}\n")
        self.sonde.chmod(0o755)
        # Faux lanceur : note ses arguments, sort avec le code écrit dans le fichier « code ».
        self.code = self.d / "code"
        self.code.write_text("0")
        self.appels = self.d / "appels.txt"
        self.lanceur = self.d / "lanceur.sh"
        self.lanceur.write_text(
            f"#!/bin/sh\necho \"$1|$2|$3|$CLAUDE_LOT_TACHE|$CLAUDE_LOT_MODELE|$CLAUDE_LOT_EFFORT|"
            f"$CLAUDE_LOT_MODELE_CHOISI|$CLAUDE_LOT_EFFORT_CHOISI|$CLAUDE_LOT_CONF\" >> {self.appels}\n"
            f"exit $(cat {self.code})\n")
        self.lanceur.chmod(0o755)
        self.file = self.d / "file.txt"
        self.conf = self.d / "claude-lot.conf"
        self.conf.write_text(
            f"cinq_heures=85\nsemaine=90\nsonde={self.sonde}\njournal={self.d}/journal.log\n"
            f"etat={self.d}/etat\nregistre={self.d}/absent.json\nfile={self.file}\n"
            f"file_lanceur={self.lanceur}\nfile_max_par_jour=2\n")

    def tearDown(self):
        self.dossier.cleanup()

    def poser(self, u7, u5, fin7=None, fin5=None):
        self.mesure.write_text(f"{u7} {u5} {fin7 or self.t + 86400} {fin5 or self.t + 3600}\n")

    def regler(self, texte):
        self.conf.write_text(self.conf.read_text() + texte)

    def file_(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = claude_lot.main(["file", "--conf", str(self.conf), *args])
        return code, out.getvalue(), err.getvalue()

    def remplir(self, *lignes):
        self.file.write_text("".join(l + "\n" for l in lignes))

    def appels_faits(self):
        return self.appels.read_text().splitlines() if self.appels.exists() else []

    def contenu(self):
        return self.file.read_text().splitlines()

    def annexe(self, suffixe):
        return Path(str(self.file) + suffixe).read_text()

    # --- file vide, ordre, lancement
    def test_file_vide_ou_absente_ne_lance_rien(self):
        self.assertEqual(self.file_("tourner")[0], 0)
        self.remplir("# un commentaire", "", "   ")
        code, out, _ = self.file_("tourner")
        self.assertEqual((code, out.strip()), (0, "file vide"))
        self.assertEqual(self.appels_faits(), [])

    def test_lance_la_premiere_tache_avec_modele_et_effort_choisis(self):
        self.remplir("# file", "audit_securite", "autre:haiku:low")
        code, out, _ = self.file_("tourner")
        self.assertEqual(code, 0)
        self.assertIn("audit_securite : ok", out)
        # La ligne dit « auto » : le lanceur reçoit auto ; la table (« securite ») donne Opus medium à titre indicatif.
        self.assertEqual(self.appels_faits(), [
            f"audit_securite|auto||audit_securite|auto||claude-opus-5-5|medium|{self.conf}"])
        self.assertEqual(self.contenu(), ["# file", "autre:haiku:low"])
        self.assertIn("audit_securite # ", self.annexe(".fait"))
        self.assertIn("file-lancement", (self.d / "journal.log").read_text())

    def test_modele_et_effort_de_la_ligne_l_emportent(self):
        self.remplir("audit_securite:sonnet:high")
        self.file_("tourner")
        self.assertEqual(self.appels_faits()[0].split("|")[:3], ["audit_securite", "sonnet", "high"])
        self.assertEqual(self.appels_faits()[0].split("|")[6:8], ["claude-sonnet-5-5", "high"])

    # --- quota par jour
    def test_quota_par_jour_atteint(self):
        self.remplir("a", "b", "c")
        self.assertEqual(self.file_("tourner")[0], 0)
        self.assertEqual(self.file_("tourner")[0], 0)
        code, _, err = self.file_("tourner")
        self.assertEqual(code, claude_lot.CODE_REFUS)
        self.assertIn("2/2 lancements aujourd'hui", err)
        self.assertEqual(len(self.appels_faits()), 2)
        self.assertEqual(self.contenu(), ["c"])

    def test_le_compteur_repart_le_lendemain(self):
        self.remplir("a", "b", "c")
        self.file_("tourner")
        self.file_("tourner")
        os.environ["CLAUDE_LOT_MAINTENANT"] = str(self.t + 2 * 86400)
        self.addCleanup(os.environ.pop, "CLAUDE_LOT_MAINTENANT", None)
        self.poser(10, 10, fin7=self.t + 5 * 86400, fin5=self.t + 2 * 86400 + 3600)
        self.assertEqual(self.file_("tourner")[0], 0)
        self.assertEqual(len(self.appels_faits()), 3)

    # --- garde : plafond commun, ligne régulière, contrôle externe
    def test_plafond_commun_refuse(self):
        self.remplir("a")
        self.poser(10, 90)
        code, _, err = self.file_("tourner")
        self.assertEqual(code, claude_lot.CODE_REFUS)
        self.assertIn("plafond commun atteint sur la fenêtre de 5 h", err)
        self.assertEqual(self.appels_faits(), [])
        self.assertEqual(self.contenu(), ["a"])
        self.assertFalse(Path(str(self.file) + ".lancements").exists())

    def test_ligne_reguliere_refuse_par_defaut_pour_la_file(self):
        self.remplir("a")
        # mi-semaine : ligne = 50 x 90 / 100 + 5 = 50 ; usage 60 % sous les plafonds mais au-dessus
        self.poser(60, 10, fin7=self.t + 302400)
        code, _, err = self.file_("tourner")
        self.assertEqual(code, claude_lot.CODE_REFUS)
        self.assertIn("ligne régulière", err)
        self.assertEqual(self.appels_faits(), [])
        # sous la ligne : lancé
        self.poser(49, 10, fin7=self.t + 302400)
        self.assertEqual(self.file_("tourner")[0], 0)

    def test_ligne_reguliere_desactivable(self):
        self.regler("file_rythme=0\n")
        self.remplir("a")
        self.poser(60, 10, fin7=self.t + 302400)
        self.assertEqual(self.file_("tourner")[0], 0)

    def test_sans_mesure_la_file_s_abstient_par_defaut(self):
        self.remplir("a")
        self.mesure.write_text("rien\n")
        self.assertEqual(self.file_("tourner")[0], claude_lot.CODE_REFUS)
        self.regler("file_mesure_impossible=lancer\n")
        self.assertEqual(self.file_("tourner")[0], 0)

    def test_garde_externe_refuse_puis_autorise(self):
        garde = self.d / "garde.sh"
        garde.write_text("#!/bin/sh\n[ -f " + str(self.d / "ok") + " ] && exit 0\necho 'serveur occupé'\nexit 3\n")
        garde.chmod(0o755)
        self.regler(f"file_garde={garde}\n")
        self.remplir("a")
        code, _, err = self.file_("tourner")
        self.assertEqual(code, claude_lot.CODE_REFUS)
        self.assertIn("serveur occupé", err)
        self.assertEqual(self.contenu(), ["a"])
        (self.d / "ok").write_text("")
        self.assertEqual(self.file_("tourner")[0], 0)

    def test_garde_externe_introuvable_fait_s_abstenir(self):
        self.regler(f"file_garde={self.d}/inexistant\n")
        self.remplir("a")
        self.assertEqual(self.file_("tourner")[0], claude_lot.CODE_REFUS)
        self.assertEqual(self.appels_faits(), [])

    # --- arrêt sur limite d'usage
    def test_limite_d_usage_remet_la_tache_en_tete(self):
        self.code.write_text("75")
        self.remplir("# tête", "a", "b")
        code, _, err = self.file_("tourner")
        self.assertEqual(code, claude_lot.CODE_REFUS)
        self.assertIn("remise en tête", err)
        self.assertEqual(self.contenu(), ["a", "# tête", "b"])
        self.assertFalse(Path(str(self.file) + ".fait").exists())
        self.assertIn("file-remise-en-tete", (self.d / "journal.log").read_text())
        # la tâche repart ensuite normalement
        self.code.write_text("0")
        self.assertEqual(self.file_("tourner")[0], 0)
        self.assertEqual([l.split("|")[0] for l in self.appels_faits()], ["a", "a"])

    def test_echec_du_lanceur_n_est_pas_rejoue(self):
        self.code.write_text("3")
        self.remplir("a", "b")
        code, out, _ = self.file_("tourner")
        self.assertEqual(code, 1)
        self.assertIn("échec code 3", out)
        self.assertEqual(self.contenu(), ["b"])
        self.assertIn("échec code 3", self.annexe(".fait"))

    def test_delai_depasse_arrete_le_lanceur(self):
        self.lanceur.write_text("#!/bin/sh\nsleep 30\n")
        self.regler("file_delai=1\n")
        self.remplir("a")
        debut = time.time()
        code, out, _ = self.file_("tourner")
        self.assertLess(time.time() - debut, 15)
        self.assertEqual(code, 1)
        self.assertIn("délai dépassé", out)

    # --- lignes invalides
    def test_lignes_invalides_ignorees_et_rangees_avec_la_raison(self):
        self.remplir("Mauvais Nom", "a;rm -rf x", "../evasion", "ok_1:modele inconnu", "ok_2:opus:ultra",
                     "ok_3:opus:high:en_trop", "bon_nom")
        code, _, _ = self.file_("tourner")
        self.assertEqual(code, 0)
        self.assertEqual([l.split("|")[0] for l in self.appels_faits()], ["bon_nom"])
        fait = self.annexe(".fait")
        for brut in ("Mauvais Nom", "a;rm -rf x", "../evasion", "ok_1:modele inconnu", "ok_2:opus:ultra", "plus de trois champs"):
            self.assertIn(brut, fait)
        self.assertEqual(fait.count("# ignorée"), 6)
        self.assertEqual(self.contenu(), [])
        self.assertIn("file-ignoree", (self.d / "journal.log").read_text())

    def test_injection_par_le_nom_de_tache_impossible(self):
        for mauvais in ("a b", "a$(id)", "a`id`", "a;b", "A", "a-b", "a/b", "", "a\tb"):
            with self.subTest(nom=mauvais):
                with self.assertRaises(ValueError):
                    claude_lot.analyser_ligne_file(mauvais)

    def test_lanceur_recoit_les_champs_comme_arguments_pas_comme_shell(self):
        self.remplir("tache_x:claude-sonnet-5-5:low")
        self.file_("tourner")
        self.assertEqual(self.appels_faits()[0].split("|")[:3], ["tache_x", "claude-sonnet-5-5", "low"])

    # --- ajouter, lister, retirer, à blanc
    def test_ajouter_lister_retirer(self):
        self.assertEqual(self.file_("ajouter", "audit_x", "opus", "high")[0], 0)
        self.assertEqual(self.file_("ajouter", "mesure_y")[0], 0)
        self.assertEqual(self.file_("ajouter", "premiere", "--tete")[0], 0)
        self.assertEqual(self.contenu(), ["premiere", "audit_x:opus:high", "mesure_y"])
        code, out, _ = self.file_("lister")
        self.assertEqual(code, 0)
        self.assertIn("audit_x  modèle=opus  effort=high", out)
        self.assertIn("aujourd'hui : 0/2 lancements", out)
        self.assertEqual(self.file_("retirer", "audit_x")[0], 0)
        self.assertEqual(self.contenu(), ["premiere", "mesure_y"])
        self.assertEqual(self.file_("retirer", "absente")[0], 1)

    def test_ajouter_refuse_une_ligne_invalide(self):
        code, _, err = self.file_("ajouter", "Mauvais Nom")
        self.assertEqual(code, claude_lot.CODE_USAGE)
        self.assertIn("nom de tâche invalide", err)
        self.assertEqual(self.file_("ajouter", "ok", "pasunmodele")[0], claude_lot.CODE_USAGE)
        self.assertEqual(self.file_("ajouter", "ok", "opus", "ultra")[0], claude_lot.CODE_USAGE)
        self.assertFalse(self.file.exists())

    def test_lister_signale_les_lignes_invalides(self):
        self.remplir("bonne", "Mauvaise")
        _, out, _ = self.file_("lister")
        self.assertIn("INVALIDE", out)
        self.assertEqual(self.contenu(), ["bonne", "Mauvaise"])

    def test_a_blanc_ne_change_rien(self):
        self.remplir("a")
        code, out, _ = self.file_("tourner", "--a-blanc")
        self.assertEqual(code, 0)
        self.assertIn("à blanc : lancerait a ", out)
        self.assertEqual(self.contenu(), ["a"])
        self.assertEqual(self.appels_faits(), [])
        self.assertFalse(Path(str(self.file) + ".lancements").exists())

    def test_lanceur_manquant_ou_absent_du_reglage(self):
        self.remplir("a")
        self.conf.write_text(self.conf.read_text().replace(f"file_lanceur={self.lanceur}", "file_lanceur="))
        self.assertEqual(self.file_("tourner")[0], claude_lot.CODE_USAGE)
        self.regler(f"file_lanceur={self.d}/inexistant\n")
        self.assertEqual(self.file_("tourner")[0], claude_lot.CODE_USAGE)
        self.assertEqual(self.contenu(), ["a"])

    def test_reglage_numerique_invalide_sort_en_64(self):
        for reglage in ("file_max_par_jour=beaucoup", "file_delai=6h", "file_delai=-1"):
            with self.subTest(reglage=reglage):
                conf = self.conf.read_text()
                self.regler(reglage + "\n")
                self.remplir("a")
                code, _, err = self.file_("tourner")
                self.assertEqual(code, claude_lot.CODE_USAGE)
                self.assertIn("invalide", err)
                self.assertEqual(self.contenu(), ["a"])
                self.conf.write_text(conf)

    def test_a_blanc_ne_purge_pas_les_lignes_invalides(self):
        self.remplir("Mauvaise ligne", "bonne")
        self.assertEqual(self.file_("tourner", "--a-blanc")[0], 0)
        self.assertEqual(self.contenu(), ["Mauvaise ligne", "bonne"])
        self.assertFalse(Path(str(self.file) + ".fait").exists())

    def test_conf_avant_file_ne_lance_jamais_claude(self):
        faux = self.d / "faux-claude"
        faux.write_text(f"#!/bin/sh\necho claude-lance >> {self.d}/claude.txt\n")
        faux.chmod(0o755)
        self.regler(f"commande={faux}\n")
        self.remplir("a")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = claude_lot.main(["--conf", str(self.conf), "file", "lister"])
        self.assertEqual(code, 0)
        self.assertIn("a  modèle=auto", out.getvalue())
        self.assertFalse((self.d / "claude.txt").exists())

    def test_ajouter_ne_peut_pas_ecrire_deux_lignes(self):
        for args in (("a", "sonnet", "\nhigh"), ("a\n",), ("a\nb",), ("a", "opus\nb"), ("a b",), ("a", "", "high\n")):
            with self.subTest(args=args):
                code, _, _ = self.file_("ajouter", *args)
                if code == 0:  # tolérés seulement s'ils donnent une seule ligne valide
                    self.assertEqual(len(self.contenu()), 1)
                    claude_lot.analyser_ligne_file(self.contenu()[0])
                self.file.unlink(missing_ok=True)

    def test_conf_transmise_au_lanceur(self):
        self.remplir("a")
        self.file_("tourner")
        self.assertTrue(self.appels_faits()[0].endswith("|" + str(self.conf)))

    def test_lanceur_impossible_a_demarrer_n_est_pas_compte(self):
        self.lanceur.write_text("#!/nexiste/pas/interpreteur\n")
        self.remplir("a")
        code, _, err = self.file_("tourner")
        self.assertEqual(code, claude_lot.CODE_USAGE)
        self.assertIn("remise en tête", err)
        self.assertEqual(self.contenu(), ["a"])
        self.assertEqual(Path(str(self.file) + ".lancements").read_text(), "")

    def test_tache_retiree_pendant_les_controles_ne_part_pas(self):
        garde = self.d / "garde-lente.sh"
        garde.write_text("#!/bin/sh\nsleep 2\nexit 0\n")
        garde.chmod(0o755)
        self.regler(f"file_garde={garde}\n")
        self.remplir("x")
        proc = subprocess.Popen([sys.executable, str(RACINE / "scripts" / "claude_lot.py"), "file",
                                 "--conf", str(self.conf), "tourner"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.8)
        self.assertEqual(self.file_("retirer", "x")[0], 0)
        _, err = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("a quitté la file", err)
        self.assertEqual(self.appels_faits(), [])

    def test_sigterm_arrete_la_tache_et_la_remet_en_tete(self):
        pidfile = self.d / "tache.pid"
        self.lanceur.write_text(f"#!/bin/sh\necho $$ > {pidfile}\nsleep 60\n")
        self.remplir("longue", "suivante")
        proc = subprocess.Popen([sys.executable, str(RACINE / "scripts" / "claude_lot.py"), "file",
                                 "--conf", str(self.conf), "tourner"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(50):
            if pidfile.exists() and pidfile.read_text().strip():
                break
            time.sleep(0.1)
        pid = int(pidfile.read_text())
        proc.terminate()
        _, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, claude_lot.CODE_REFUS)
        self.assertIn("remise en tête", err)
        with self.assertRaises(ProcessLookupError):
            time.sleep(0.3)
            os.kill(pid, 0)
        self.assertEqual(self.contenu(), ["longue", "suivante"])
        # le verrou est libre : une autre exécution peut repartir
        self.lanceur.write_text("#!/bin/sh\nexit 0\n")
        self.assertEqual(self.file_("tourner")[0], 0)

    def test_delai_depasse_tue_aussi_les_descendants_qui_ignorent_term(self):
        pidfile = self.d / "enfant.pid"
        self.lanceur.write_text(f"#!/bin/sh\n(trap '' TERM; echo $$ > {pidfile}; sleep 60) &\nwait\n")
        self.regler("file_delai=1\n")
        self.remplir("a")
        ancien, claude_lot.DELAI_GRACE = claude_lot.DELAI_GRACE, 1
        self.addCleanup(setattr, claude_lot, "DELAI_GRACE", ancien)
        code, out, _ = self.file_("tourner")
        self.assertEqual((code, "délai dépassé" in out), (1, True))
        pid = int(pidfile.read_text())
        with self.assertRaises(ProcessLookupError):
            time.sleep(0.3)
            os.kill(pid, 0)

    def test_un_lanceur_qui_sort_en_124_n_est_pas_un_delai_depasse(self):
        self.code.write_text("124")
        self.remplir("a")
        _, out, _ = self.file_("tourner")
        self.assertIn("échec code 124", out)

    # --- verrou
    def test_une_execution_deja_en_cours_fait_s_abstenir(self):
        self.remplir("a")
        with claude_lot.verrou(Path(str(self.file) + ".lock"), True):
            code, _, err = self.file_("tourner")
        self.assertEqual(code, claude_lot.CODE_REFUS)
        self.assertIn("autre exécution", err)
        self.assertEqual(self.appels_faits(), [])

    def test_ajouter_reste_possible_pendant_qu_une_tache_tourne(self):
        self.remplir("longue")
        self.lanceur.write_text(f"#!/bin/sh\nsleep 2\n")
        proc = subprocess.Popen([sys.executable, str(RACINE / "scripts" / "claude_lot.py"), "file",
                                 "--conf", str(self.conf), "tourner"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(0.7)
        debut = time.time()
        self.assertEqual(self.file_("ajouter", "suivante")[0], 0)
        self.assertLess(time.time() - debut, 1.5)
        proc.communicate(timeout=20)
        self.assertEqual(self.contenu(), ["suivante"])


class Exemples(unittest.TestCase):
    """Le lanceur d'exemple, bout en bout avec un faux claude-lot et un faux dossier de briefs."""

    def test_lanceur_exemple_traduit_la_limite_d_usage_en_code_75(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            briefs = d / "briefs"
            briefs.mkdir()
            (briefs / "ma_tache.md").write_text("# Ma tâche\nFais quelque chose.\n")
            faux = d / "claude-lot"
            sortie = d / "reponse.json"
            faux.write_text(f"#!/bin/sh\ncat {sortie}\nexit 0\n")
            faux.chmod(faux.stat().st_mode | stat.S_IEXEC)
            lanceur = RACINE / "examples" / "lanceur-exemple.sh"
            env = {**os.environ, "CLAUDE_LOT_BRIEFS": str(briefs), "CLAUDE_LOT_SORTIES": str(d / "sorties"),
                   "CLAUDE_LOT_BIN": str(faux)}
            sortie.write_text('{"is_error": false, "result": "fait"}')
            r = subprocess.run(["bash", str(lanceur), "ma_tache", "claude-sonnet-5-5", "medium"],
                               env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            sortie.write_text('{"is_error": true, "result": "Claude usage limit reached"}')
            r = subprocess.run(["bash", str(lanceur), "ma_tache", "claude-sonnet-5-5", "medium"],
                               env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 75, r.stderr)
            r = subprocess.run(["bash", str(lanceur), "absente", "auto", "medium"],
                               env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 64)
            sortie.write_text('{"is_error": true, "result": "Prompt too long: context limit"}')
            r = subprocess.run(["bash", str(lanceur), "ma_tache", "auto", ""],
                               env=env, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 75)  # une autre erreur « limit » n'est pas la limite d'usage
            r = subprocess.run(["bash", str(lanceur), "../etc", "auto", "medium"],
                               env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 64)


if __name__ == "__main__":
    unittest.main()
