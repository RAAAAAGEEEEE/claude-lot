#!/usr/bin/env python3
"""claude-lot : lanceur commun des travaux en lot de Claude Code (`claude -p`).

Deux rôles, pour tous les projets d'une même machine :

1. Plafond commun. Avant de lancer quoi que ce soit, lit l'utilisation réelle de
   l'abonnement (fenêtre glissante de 5 h et semaine) par une sonde, et refuse
   de démarrer au-delà du plafond (85 % de la fenêtre de 5 h, 90 % de la
   semaine par défaut). Le refus sort avec le code 75 et laisse une ligne dans
   le journal. Les points restants sont gardés pour le travail prioritaire
   (`--prioritaire`, plafond de réserve à 95 %) et pour les sessions
   interactives, qui ne passent pas par ce lanceur.

2. Choix du modèle et de l'effort selon le type de tâche, par mots-clés du
   sujet, avec un champ explicite (`modele:` dans le brief ou `--modele`) qui
   l'emporte toujours.

Usage :
    claude-lot [options] -- <arguments de claude>   vérifie, choisit, lance
    claude-lot --verifier [options]                 vérifie seulement (0 ou 75)
    claude-lot --choisir [options]                  affiche le modèle choisi

Bibliothèque standard seulement. N'affiche jamais de secret : la sonde est une
commande externe dont seule la ligne de mesure est lue.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

VERSION = "1.0.0"

CODE_REFUS = 75  # EX_TEMPFAIL : réessayer plus tard
CODE_USAGE = 64

CONF_DEFAUT = "/etc/claude-lot.conf"
REGLAGES_DEFAUT = {
    "cinq_heures": "85",
    "semaine": "90",
    "reserve": "95",
    "sonde": "",
    "sonde_delai": "120",
    "journal": "~/.local/state/claude-lot/journal.log",
    "etat": "~/.local/state/claude-lot/derniere-mesure",
    "registre": "~/.claude/modeles.json",
    "commande": "claude",
    "mesure_impossible": "lancer",
}

IDS_DEFAUT = {
    "haiku": "claude-haiku-5-5",
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
    "fable": "claude-fable-5-1",
}
EFFORT_PAR_FAMILLE = {"haiku": "low", "sonnet": "medium", "opus": "medium", "fable": "high"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")

# Table de choix, dans l'ordre de priorité : la première règle qui reconnaît le
# sujet l'emporte. Les motifs portent sur le texte en minuscules et sans accents.
REGLES = [
    ("opus", "medium", "architecture, logique centrale, sécurité, contre-revue ou vérification factuelle", [
        r"\barchitectur", r"logique centrale", r"\bcoeur (du|de la|de l)", r"\bsecurit", r"\bsecurity\b",
        r"\bvulnerab", r"\bfailles?\b", r"\bauthentif", r"\bauth\b", r"\breseau\b(?! social)",
        r"\bnetwork", r"pare-feu", r"\bfirewall", r"contre-revue", r"contre-relecture",
        r"revue de code", r"code review", r"\brefactor", r"\brefonte\b",
        r"verification factuelle", r"verifi\w* (des |les )?faits", r"fact-?check",
    ]),
    ("sonnet", "high", "extraction, analyse de documents ou texte publié factuel", [
        r"\bextraction", r"\bextrai", r"\bextract", r"\bdocuments?\b", r"\bpdf\b",
        r"\banalys\w* (de |des |du |d')?(rapports?|contrats?|fichiers?|sources?)",
        r"\barticles?\b", r"\bbreves?\b", r"texte publie", r"\bpublication", r"\bfactuel",
        r"\bpublished\b",
    ]),
    ("haiku", "low", "gros volume simple ou mesure", [
        r"\bmesur", r"\bmeasur", r"\bcompt(er|age)\b", r"\bcount(ing)?\b", r"\btri\b", r"\btrier\b",
        r"\btriage\b", r"\bclass(er|ement)\b", r"gros volume", r"\ben masse\b", r"\bbulk\b",
        r"\binventaire", r"\blister\b", r"\bformat(er|age)\b",
    ]),
]
# Haiku ne rédige pas et n'écrit pas de code : un sujet qui mêle mesure et
# écriture reste sur Sonnet.
PAS_HAIKU = [r"\bredig", r"\bredact", r"\becri", r"\btextes?\b", r"\bcode\b", r"\bcorrig",
             r"\bimplement", r"\bwrit", r"\bfix\b"]

CHAMP_MODELE = re.compile(r"^\s*(?:modele|modèle|model)\s*:\s*(.+?)\s*$", re.I | re.M)
CHAMP_EFFORT = re.compile(r"^\s*effort\s*:\s*(\S+)\s*$", re.I | re.M)
TITRE = re.compile(r"^#\s+(.+?)\s*$", re.M)


def normaliser(texte: str) -> str:
    sans_accents = unicodedata.normalize("NFKD", texte.replace("œ", "oe").replace("Œ", "OE"))
    sans_accents = "".join(c for c in sans_accents if not unicodedata.combining(c))
    return sans_accents.lower().replace("_", " ")


# ---------------------------------------------------------------- réglages

def lire_reglages(chemin: str | None = None) -> dict:
    reglages = dict(REGLAGES_DEFAUT)
    chemin = chemin or os.environ.get("CLAUDE_LOT_CONF") or CONF_DEFAUT
    try:
        lignes = Path(chemin).read_text(encoding="utf-8").splitlines()
    except OSError:
        lignes = []
    for ligne in lignes:
        ligne = ligne.split("#", 1)[0].strip()
        if "=" in ligne:
            cle, valeur = (s.strip() for s in ligne.split("=", 1))
            if cle in reglages:
                reglages[cle] = valeur
    return reglages


def chemin_local(valeur: str) -> Path:
    return Path(os.path.expanduser(valeur))


def maintenant() -> int:
    return int(os.environ.get("CLAUDE_LOT_MAINTENANT") or time.time())


def journaliser(reglages: dict, projet: str, evenement: str, detail: str) -> None:
    ligne = f"{datetime.now().astimezone().isoformat(timespec='seconds')} projet={projet or '-'} {evenement} {detail}\n"
    try:
        chemin = chemin_local(reglages["journal"])
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with open(chemin, "a", encoding="utf-8") as f:
            f.write(ligne)
    except OSError:
        sys.stderr.write("claude-lot : journal impossible à écrire\n")


# ---------------------------------------------------------------- mesure

MESURE = re.compile(r"^(\d+) (\d+) (\d{10}) (\d{10})$")


def lire_mesure(texte: str):
    """« <% semaine> <% 5 h> <fin semaine epoch> <fin 5 h epoch> » -> tuple d'entiers."""
    for ligne in reversed(texte.strip().splitlines()):
        m = MESURE.match(ligne.strip())
        if m:
            return tuple(int(x) for x in m.groups())
    return None


def mesurer(reglages: dict):
    """Renvoie (mesure, origine) ; mesure vaut None si aucune n'est utilisable."""
    sonde = reglages["sonde"]
    etat = chemin_local(reglages["etat"])
    if sonde:
        try:
            commande = shlex.split(sonde)
            commande[0] = os.path.expanduser(commande[0])
            r = subprocess.run(commande, capture_output=True, text=True,
                               timeout=int(reglages["sonde_delai"]))
            mesure = lire_mesure(r.stdout) if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            mesure = None
        if mesure:
            try:
                etat.parent.mkdir(parents=True, exist_ok=True)
                etat.write_text(" ".join(map(str, mesure)) + "\n", encoding="utf-8")
            except OSError:
                pass
            return mesure, "sonde"
    # Sonde muette : la dernière mesure sert tant que ses deux fenêtres courent.
    try:
        mesure = lire_mesure(etat.read_text(encoding="utf-8"))
    except OSError:
        mesure = None
    if mesure and maintenant() < mesure[3]:
        return mesure, "dernière mesure"
    return None, "aucune"


def verifier(reglages: dict, prioritaire: bool, projet: str, sujet: str):
    """Renvoie (autorisé, message)."""
    mesure, origine = mesurer(reglages)
    if mesure is None:
        if reglages["mesure_impossible"] == "refuser":
            msg = "mesure du quota impossible, réglage mesure_impossible=refuser"
            journaliser(reglages, projet, "refus", f"{msg} sujet={sujet[:60]!r}")
            return False, msg
        journaliser(reglages, projet, "lancement-sans-mesure", f"sujet={sujet[:60]!r}")
        return True, "mesure du quota impossible, lancement autorisé (mesure_impossible=lancer)"
    u7, u5, fin7, fin5 = mesure
    t = maintenant()
    if t >= fin5:
        u5 = 0
    if t >= fin7:
        u7 = 0
    if prioritaire:
        p5 = p7 = int(reglages["reserve"])
    else:
        p5, p7 = int(reglages["cinq_heures"]), int(reglages["semaine"])
    etat = f"5h={u5}%/{p5}% semaine={u7}%/{p7}% ({origine})"
    if u5 >= p5 or u7 >= p7:
        fin = fin5 if u5 >= p5 else fin7
        reprise = datetime.fromtimestamp(fin).astimezone().strftime("%d/%m %H:%M")
        quoi = "la fenêtre de 5 h" if u5 >= p5 else "la semaine"
        journaliser(reglages, projet, "refus", f"{etat} sujet={sujet[:60]!r}")
        return False, (f"plafond commun atteint sur {quoi} ({etat}), rien lancé ; "
                       f"reprise possible après le {reprise}")
    return True, etat


# ---------------------------------------------------------------- modèle

def lire_registre(reglages: dict) -> dict:
    ids = dict(IDS_DEFAUT)
    try:
        familles = json.loads(chemin_local(reglages["registre"]).read_text(encoding="utf-8"))["familles"]
        for famille in ids:
            ident = (familles.get(famille) or {}).get("id")
            if isinstance(ident, str) and ident.startswith("claude-"):
                ids[famille] = ident
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return ids


def famille_de(modele: str) -> str | None:
    m = normaliser(modele)
    for famille in IDS_DEFAUT:
        if famille in m:
            return famille
    return None


def resoudre_modele(valeur: str, ids: dict):
    """« opus », « opus high », « claude-opus-5-5 medium » -> (id, effort ou None)."""
    morceaux = valeur.replace(",", " ").split()
    if not morceaux:
        return None, None
    nom, effort = morceaux[0], None
    if len(morceaux) > 1 and morceaux[1].lower() in EFFORTS:
        effort = morceaux[1].lower()
    if nom.lower() in ids:
        return ids[nom.lower()], effort
    return nom, effort


def sujet_du_brief(texte: str) -> str:
    """Titre du brief (première ligne « # ») : le corps contient des consignes
    générales (sécurité, tests...) qui fausseraient le choix."""
    m = TITRE.search(texte)
    return m.group(1) if m else ""


def choisir(sujet: str, brief: str, modele: str | None, effort: str | None, ids: dict):
    """Renvoie (id du modèle, effort, raison)."""
    if not modele and brief:
        m = CHAMP_MODELE.search(brief)
        if m:
            modele = m.group(1)
            if not effort:
                e = CHAMP_EFFORT.search(brief)
                effort = e.group(1).lower() if e else None
    if modele:
        ident, effort_champ = resoudre_modele(modele, ids)
        effort = effort or effort_champ or EFFORT_PAR_FAMILLE.get(famille_de(ident) or "", "medium")
        return ident, effort, "modèle explicite"
    texte = normaliser(" ".join(filter(None, [sujet, sujet_du_brief(brief)])))
    for famille, effort_regle, raison, motifs in REGLES:
        if any(re.search(p, texte) for p in motifs):
            if famille == "haiku" and any(re.search(p, texte) for p in PAS_HAIKU):
                continue
            return ids[famille], effort or effort_regle, raison
    return ids["sonnet"], effort or "medium", "défaut"


# ---------------------------------------------------------------- entrée

def analyser(argv):
    p = argparse.ArgumentParser(prog="claude-lot", description=__doc__.split("\n\n")[0])
    p.add_argument("--verifier", action="store_true", help="vérifier le plafond seulement (code 0 ou 75)")
    p.add_argument("--choisir", action="store_true", help="afficher le modèle et l'effort choisis, sans rien lancer")
    p.add_argument("--sujet", default="", help="sujet de la tâche (sert au choix du modèle et au journal)")
    p.add_argument("--sujet-fichier", help="brief de la tâche : titre « # » et champs modele:/effort:")
    p.add_argument("--modele", help="modèle imposé (alias haiku/sonnet/opus/fable ou identifiant complet)")
    p.add_argument("--effort", choices=EFFORTS, help="effort imposé")
    p.add_argument("--projet", default="", help="nom du projet, pour le journal")
    p.add_argument("--prioritaire", action="store_true", help="travail prioritaire : plafond de réserve")
    p.add_argument("--conf", help=f"fichier de réglages (défaut {CONF_DEFAUT} ou $CLAUDE_LOT_CONF)")
    p.add_argument("--version", action="version", version=f"claude-lot {VERSION}")
    p.add_argument("args", nargs=argparse.REMAINDER, help="-- puis les arguments passés à claude")
    a = p.parse_args(argv)
    if a.args and a.args[0] == "--":
        a.args = a.args[1:]
    return a


def main(argv=None) -> int:
    a = analyser(sys.argv[1:] if argv is None else argv)
    reglages = lire_reglages(a.conf)
    brief = ""
    if a.sujet_fichier:
        try:
            brief = Path(a.sujet_fichier).read_text(encoding="utf-8", errors="replace")
        except OSError:
            sys.stderr.write(f"claude-lot : brief illisible ({a.sujet_fichier})\n")
            return CODE_USAGE
    sujet = a.sujet or sujet_du_brief(brief)
    ids = lire_registre(reglages)
    modele, effort, raison = choisir(a.sujet, brief, a.modele, a.effort, ids)

    if a.choisir:
        print(f"{modele} {effort} ({raison})")
        return 0

    autorise, message = verifier(reglages, a.prioritaire, a.projet, sujet)
    if not autorise:
        sys.stderr.write(f"claude-lot : {message}\n")
        return CODE_REFUS
    if a.verifier:
        print(f"claude-lot : autorisé, {message}")
        return 0
    if not a.args:
        sys.stderr.write("claude-lot : rien à lancer (ajoutez -- puis les arguments de claude)\n")
        return CODE_USAGE

    commande = shlex.split(os.environ.get("CLAUDE_LOT_COMMANDE") or reglages["commande"])
    ajout = []
    if "--model" not in a.args:
        ajout += ["--model", modele]
    else:
        raison = "modèle imposé par la commande"
    if "--effort" not in a.args:
        ajout += ["--effort", effort]
    journaliser(reglages, a.projet, "lancement",
                f"{message} modele={modele if '--model' not in a.args else 'commande'} effort={effort} ({raison}) sujet={sujet[:60]!r}")
    sys.stdout.flush()
    os.execvp(commande[0], commande + ajout + a.args)
    return 0  # jamais atteint


if __name__ == "__main__":
    sys.exit(main())
