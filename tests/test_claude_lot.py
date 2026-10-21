"""Tests de claude-lot : plafond commun, choix du modèle, lancement."""

import io
import json
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

IDS = dict(claude_lot.IDS_DEFAUT)


def choix(sujet="", brief="", modele=None, effort=None):
    ident, eff, _ = claude_lot.choisir(sujet, brief, modele, effort, IDS)
    return ident, eff


class ChoixDuModele(unittest.TestCase):
    def test_defaut_sonnet_medium(self):
        self.assertEqual(choix("ajouter un bouton de partage"), ("claude-sonnet-5-5", "medium"))

    def test_opus_pour_architecture_securite_contre_revue_verification(self):
        for sujet in ("Refonte de l'architecture du worker", "Audit de sécurité de l'API",
                      "Contre-revue du correctif", "Vérification factuelle des définitions",
                      "logique centrale du moteur de jeu", "pare-feu du serveur", "Cœur du moteur"):
            with self.subTest(sujet=sujet):
                self.assertEqual(choix(sujet), ("claude-opus-5-5", "medium"))

    def test_sonnet_high_pour_extraction_documents_et_texte_publie(self):
        for sujet in ("Extraction des prix depuis les PDF", "analyse des rapports annuels",
                      "Rédiger un article sur le salon", "brève sur le lancement",
                      "texte publié factuel"):
            with self.subTest(sujet=sujet):
                self.assertEqual(choix(sujet), ("claude-sonnet-5-5", "high"))

    def test_haiku_pour_mesure_et_gros_volume(self):
        for sujet in ("Mesure du temps de chargement", "tri en masse des fichiers",
                      "compter les fiches sans photo", "inventaire des liens"):
            with self.subTest(sujet=sujet):
                self.assertEqual(choix(sujet), ("claude-haiku-5-5", "low"))

    def test_haiku_ne_redige_pas(self):
        self.assertEqual(choix("mesurer puis rédiger le résumé"), ("claude-sonnet-5-5", "medium"))
        self.assertEqual(choix("compter et corriger les liens"), ("claude-sonnet-5-5", "medium"))

    def test_reseaux_sociaux_ne_sont_pas_du_reseau(self):
        self.assertEqual(choix("réseau social : planning des posts"), ("claude-sonnet-5-5", "medium"))

    def test_documentation_reste_en_medium(self):
        self.assertEqual(choix("mettre à jour la documentation"), ("claude-sonnet-5-5", "medium"))

    def test_seul_le_titre_du_brief_compte(self):
        brief = "Base : abc1234\n\n# Bouton de partage\n\nRègles : sécurité, ne pas toucher au réseau.\n"
        self.assertEqual(choix("partage_v2", brief), ("claude-sonnet-5-5", "medium"))
        brief2 = "Base : abc\n\n# Vérification factuelle des définitions\n"
        self.assertEqual(choix("relecture_v2", brief2), ("claude-opus-5-5", "medium"))

    def test_champ_modele_du_brief_l_emporte(self):
        brief = "# Vérification factuelle\nmodele: sonnet high\n"
        self.assertEqual(choix("x", brief), ("claude-sonnet-5-5", "high"))
        brief = "# Mesure\nmodèle : claude-opus-5-5\neffort: high\n"
        self.assertEqual(choix("x", brief), ("claude-opus-5-5", "high"))

    def test_option_modele_l_emporte_sur_le_brief(self):
        brief = "# Mesure\nmodele: opus\n"
        self.assertEqual(choix("x", brief, modele="haiku"), ("claude-haiku-5-5", "low"))
        self.assertEqual(choix("architecture", modele="claude-sonnet-5-5"), ("claude-sonnet-5-5", "medium"))

    def test_effort_impose(self):
        self.assertEqual(choix("architecture", effort="high"), ("claude-opus-5-5", "high"))

    def test_registre_des_modeles(self):
        with tempfile.TemporaryDirectory() as d:
            reg = Path(d, "modeles.json")
            reg.write_text(json.dumps({"familles": {"opus": {"id": "claude-opus-6-0"}}}))
            ids = claude_lot.lire_registre({"registre": str(reg)})
            self.assertEqual(ids["opus"], "claude-opus-6-0")
            self.assertEqual(ids["sonnet"], "claude-sonnet-5-5")
            reg.write_text("illisible")
            self.assertEqual(claude_lot.lire_registre({"registre": str(reg)}), claude_lot.IDS_DEFAUT)


class Plafond(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.d = Path(self.dossier.name)
        self.mesure = self.d / "mesure.txt"
        self.sonde = self.d / "sonde.sh"
        self.sonde.write_text(f"#!/bin/sh\ncat {self.mesure}\n")
        self.sonde.chmod(self.sonde.stat().st_mode | stat.S_IEXEC)
        self.conf = self.d / "claude-lot.conf"
        self.conf.write_text(
            f"cinq_heures=85\nsemaine=90\nreserve=95\nsonde={self.sonde}\n"
            f"journal={self.d}/journal.log\netat={self.d}/etat\nregistre={self.d}/absent.json\n")
        self.t = int(time.time())

    def tearDown(self):
        self.dossier.cleanup()

    def poser(self, u7, u5, fin7=None, fin5=None):
        self.mesure.write_text(f"{u7} {u5} {fin7 or self.t + 86400} {fin5 or self.t + 3600}\n")

    def lancer(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = claude_lot.main(["--conf", str(self.conf), *args])
        return code, out.getvalue(), err.getvalue()

    def journal(self):
        return (self.d / "journal.log").read_text()

    def test_sous_le_plafond(self):
        self.poser(21, 64)
        code, out, _ = self.lancer("--verifier", "--projet", "jeu")
        self.assertEqual(code, 0)
        self.assertIn("5h=64%/85%", out)

    def test_refus_au_dela_de_85_pour_cent_de_la_fenetre_de_5_h(self):
        self.poser(21, 85)
        code, _, err = self.lancer("--verifier", "--projet", "jeu", "--sujet", "relecture")
        self.assertEqual(code, claude_lot.CODE_REFUS)
        self.assertIn("plafond commun atteint sur la fenêtre de 5 h", err)
        self.assertIn("projet=jeu refus 5h=85%/85%", self.journal())

    def test_refus_au_dela_de_90_pour_cent_de_la_semaine(self):
        self.poser(90, 10)
        code, _, err = self.lancer("--verifier")
        self.assertEqual(code, 75)
        self.assertIn("sur la semaine", err)

    def test_prioritaire_garde_la_reserve_jusqu_a_95(self):
        self.poser(92, 88)
        self.assertEqual(self.lancer("--verifier", "--prioritaire")[0], 0)
        self.poser(95, 10)
        self.assertEqual(self.lancer("--verifier", "--prioritaire")[0], 75)

    def regler_rythme(self, avance=5):
        self.conf.write_text(self.conf.read_text() + f"rythme=1\navance={avance}\n")

    def test_rythme_refuse_au_dessus_de_la_ligne_reguliere(self):
        self.regler_rythme()
        # mi-semaine : ligne = 50 x 90 / 100 + 5 = 50
        fin7 = self.t + 302400
        self.poser(50, 10, fin7=fin7)
        code, _, err = self.lancer("--verifier", "--projet", "jeu")
        self.assertEqual(code, claude_lot.CODE_REFUS)
        self.assertIn("ligne régulière", err)
        self.assertIn("semaine=50%/50%", err)
        self.poser(49, 10, fin7=fin7)
        code, out, _ = self.lancer("--verifier")
        self.assertEqual(code, 0)
        self.assertIn("semaine=49%/50%", out)

    def test_rythme_ne_depasse_jamais_le_plafond_de_la_semaine(self):
        self.regler_rythme(avance=50)
        self.poser(89, 10, fin7=self.t + 3600)
        self.assertEqual(self.lancer("--verifier")[0], 0)
        self.poser(90, 10, fin7=self.t + 3600)
        self.assertEqual(self.lancer("--verifier")[0], 75)

    def test_rythme_ne_touche_pas_au_prioritaire(self):
        self.regler_rythme()
        self.poser(60, 10, fin7=self.t + 302400)
        self.assertEqual(self.lancer("--verifier")[0], 75)
        self.assertEqual(self.lancer("--verifier", "--prioritaire")[0], 0)

    def test_rythme_absent_ou_nul_garde_l_ancien_comportement(self):
        self.poser(60, 10, fin7=self.t + 302400)
        self.assertEqual(self.lancer("--verifier")[0], 0)

    def test_rythme_annonce_la_reprise_quand_la_ligne_rattrape(self):
        self.regler_rythme()
        self.poser(60, 10, fin7=self.t + 302400)
        _, _, err = self.lancer("--verifier")
        self.assertIn("reprise possible après le", err)

    def test_fenetre_terminee_repart_a_zero(self):
        self.poser(21, 123, fin5=self.t - 60)
        self.assertEqual(self.lancer("--verifier")[0], 0)

    def test_sonde_muette_reprend_la_derniere_mesure(self):
        self.poser(21, 99)
        self.assertEqual(self.lancer("--verifier")[0], 75)
        self.mesure.write_text("rien\n")
        code, _, err = self.lancer("--verifier")
        self.assertEqual(code, 75)
        self.assertIn("dernière mesure", err)

    def test_sans_aucune_mesure_selon_le_reglage(self):
        self.mesure.write_text("rien\n")
        self.assertEqual(self.lancer("--verifier")[0], 0)
        self.assertIn("lancement-sans-mesure", self.journal())
        self.conf.write_text(self.conf.read_text() + "mesure_impossible=refuser\n")
        self.assertEqual(self.lancer("--verifier")[0], 75)

    def test_choisir_ne_mesure_rien(self):
        self.mesure.write_text("rien\n")
        code, out, _ = self.lancer("--choisir", "--sujet", "Contre-revue du paiement")
        self.assertEqual((code, out.strip()), (0, "claude-opus-5-5 medium (architecture, logique centrale, "
                                                   "sécurité, contre-revue ou vérification factuelle)"))
        self.assertFalse((self.d / "journal.log").exists())


class Lancement(unittest.TestCase):
    """Bout en bout : le script lancé comme commande, avec un faux claude."""

    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.d = Path(self.dossier.name)
        faux = self.d / "faux-claude"
        faux.write_text("#!/bin/sh\necho \"$@\"\n")
        faux.chmod(0o755)
        sonde = self.d / "sonde.sh"
        sonde.write_text(f"#!/bin/sh\necho '21 40 {int(time.time()) + 86400} {int(time.time()) + 3600}'\n")
        sonde.chmod(0o755)
        self.conf = self.d / "conf"
        self.conf.write_text(f"sonde={sonde}\njournal={self.d}/j.log\netat={self.d}/e\n"
                             f"registre={self.d}/absent\ncommande={faux}\n")

    def tearDown(self):
        self.dossier.cleanup()

    def executer(self, *args):
        return subprocess.run([sys.executable, str(RACINE / "scripts" / "claude_lot.py"),
                               "--conf", str(self.conf), *args], capture_output=True, text=True)

    def test_lance_claude_avec_le_modele_choisi(self):
        r = self.executer("--sujet", "mesure des temps", "--", "-p", "Bonjour", "--output-format", "json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "--model claude-haiku-5-5 --effort low -p Bonjour --output-format json")

    def test_modele_de_la_commande_respecte(self):
        r = self.executer("--sujet", "architecture", "--", "-p", "x", "--model", "claude-sonnet-5-5")
        self.assertEqual(r.stdout.strip(), "--effort medium -p x --model claude-sonnet-5-5")

    def test_sans_arguments_rien_a_lancer(self):
        self.assertEqual(self.executer("--sujet", "x").returncode, claude_lot.CODE_USAGE)


if __name__ == "__main__":
    unittest.main()
