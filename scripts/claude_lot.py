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

3. File de tâches (`claude-lot file`), version 1.1 : les gros chantiers sont rangés dans
   une file et lancés au fil de la semaine, au plus N par jour, une seule à la fois, chacun
   seulement si le plafond commun et la ligne régulière de la semaine l'autorisent. Le
   programme qui exécute une tâche (le « lanceur ») est un réglage : ce fichier ne connaît
   aucun projet.

4. Fenêtre de 5 h inconnue et refus constatés (1.2) : quand la sonde ne connaît pas la fenêtre
   de 5 h (« inconnu », jamais 0), le plafond de 5 h ne s'applique pas ; à la place, tout refus
   d'usage constaté à la fin d'un lot (événement « rejected », erreur 429, « hit your … limit »)
   est noté avec l'heure de reprise annoncée, et plus aucun lot ne démarre avant cette heure.
   Chaque lot laisse une ligne de fin (durée, code de sortie, coût si la sortie le donne).

Usage :
    claude-lot [options] -- <arguments de claude>   vérifie, choisit, lance
    claude-lot --verifier [options]                 vérifie seulement (0 ou 75)
    claude-lot --choisir [options]                  affiche le modèle choisi
    claude-lot file ajouter|lister|retirer|tourner  file de tâches (voir docs/FILE.md)
    claude-lot refus noter [--fichier F] [--code N]  note un refus d'usage lu dans une sortie de claude
    claude-lot refus etat                           affiche le refus en cours (code 0) ou rien (code 1)

Bibliothèque standard seulement. N'affiche jamais de secret : la sonde est une
commande externe dont seule la ligne de mesure est lue.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

VERSION = "1.2.0"

CODE_REFUS = 75  # EX_TEMPFAIL : réessayer plus tard
CODE_USAGE = 64

CONF_DEFAUT = "/etc/claude-lot.conf"
REGLAGES_DEFAUT = {
    "cinq_heures": "85",
    "semaine": "90",
    "reserve": "95",
    "rythme": "0",
    "avance": "5",
    "sans_rythme": "",
    "presence_projets": "",
    "avance_absent": "",
    "cinq_heures_absent": "",
    "cinq_heures_present": "",
    "presence": "/usr/local/bin/presence-antoine",
    "turbo": "",
    "ligne_horaire": "",
    "sonde": "",
    "sonde_delai": "120",
    "journal": "~/.local/state/claude-lot/journal.log",
    "etat": "~/.local/state/claude-lot/derniere-mesure",
    "registre": "~/.claude/modeles.json",
    "commande": "claude",
    "mesure_impossible": "lancer",
    # Refus d'usage constatés (heure de reprise annoncée), partagés avec la sonde si elle le lit.
    "refus": "~/.local/state/claude-lot/refus.txt",
    # 1 : --strict-mcp-config ajouté à chaque lancement (aucun serveur MCP hors d'un --mcp-config explicite).
    "strict_mcp": "1",
    # Motifs des processus épargnés au nettoyage du scope (vide : survivants.txt à côté du script).
    "survivants": "",
    # File de tâches (`claude-lot file`)
    "file": "~/.local/state/claude-lot/file.txt",
    "file_max_par_jour": "2",
    "file_lanceur": "",
    "file_garde": "",
    "file_delai": "21600",
    "file_rythme": "1",
    "file_mesure_impossible": "refuser",
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

SEMAINE = 604800
MESURE = re.compile(r"^(\d+) (\d+|inconnu) (\d{10}) (\d{10})$")
INCONNU = "inconnu"


def lire_mesure(texte: str):
    """« <% semaine> <% 5 h | inconnu> <fin semaine epoch> <fin 5 h epoch> » -> tuple.

    Le % de la fenêtre de 5 h vaut None quand la sonde ne le connaît pas (« inconnu ») : depuis
    le 06/11/2026, l'événement rate_limit_event de Claude Code peut ne plus porter que la semaine.
    Une absence n'est jamais lue comme 0 %."""
    for ligne in reversed(texte.strip().splitlines()):
        m = MESURE.match(ligne.strip())
        if m:
            u7, u5, fin7, fin5 = m.groups()
            return int(u7), (None if u5 == INCONNU else int(u5)), int(fin7), int(fin5)
    return None


def texte_mesure(mesure) -> str:
    return " ".join(INCONNU if x is None else str(x) for x in mesure)


def mesurer(reglages: dict):
    """Renvoie (mesure, origine) ; mesure vaut None si aucune n'est utilisable."""
    sonde = reglages["sonde"]
    etat = chemin_local(reglages["etat"])
    if sonde:
        try:
            commande = shlex.split(sonde)
            commande[0] = os.path.expanduser(commande[0])
            # QUOTA_FORMAT=etendu : une sonde qui le connaît écrit « inconnu » au lieu d'un 0 de
            # compatibilité quand la fenêtre de 5 h manque ; les autres l'ignorent.
            r = subprocess.run(commande, capture_output=True, text=True,
                               timeout=int(reglages["sonde_delai"]),
                               env={**os.environ, "QUOTA_FORMAT": "etendu"})
            mesure = lire_mesure(r.stdout) if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            mesure = None
        if mesure:
            try:
                etat.parent.mkdir(parents=True, exist_ok=True)
                etat.write_text(texte_mesure(mesure) + "\n", encoding="utf-8")
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


# ---------------------------------------------------------------- refus d'usage constatés

REFUS_DEFAUT = 1800  # heure de reprise illisible : on réessaie dans 30 min (un nouveau refus prolonge)
LIMITE_TEXTE = re.compile(r"hit your (?:[a-z]+ )?limit|usage limit reached|(?:5-hour|session|weekly) limit\b", re.I)
LIMITE_LIGNE = re.compile(r"^(?:error:\s*)?(?:you'?ve hit your|you have hit your|claude ai usage limit reached"
                          r"|api error:\s*429)", re.I)
REPRISE_TEXTE = re.compile(
    r"resets\s+(?:(?P<mois>[A-Za-z]{3,9})\.?\s+(?P<jour>\d{1,2}),?\s+(?:at\s+)?)?"
    r"(?P<h>\d{1,2})(?::(?P<mi>\d{2}))?\s*(?P<ap>am|pm)\b(?:\s*\((?P<tz>[A-Za-z_]+(?:/[A-Za-z_+-]+)*)\))?",
    re.I)
MOIS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun",
                                         "jul", "aug", "sep", "oct", "nov", "dec"))}


def heure_de_reprise(texte: str, t: int):
    """Heure de reprise (epoch) annoncée dans un message de limite de Claude Code, ou None.
    Formes reconnues : « …|1793869200 », « resets 9:50pm (Europe/Paris) », « resets 5am »,
    « resets Nov 9, 8pm (Europe/Paris) ». Sans date : la prochaine occurrence de l'heure."""
    m = re.search(r"limit reached\|(\d{10})", texte)
    if m:
        return int(m.group(1))
    m = REPRISE_TEXTE.search(texte)
    if not m:
        return None
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(m["tz"]) if m["tz"] else None
    except Exception:
        tz = None
    tz = tz or datetime.now().astimezone().tzinfo
    h = int(m["h"]) % 12 + (12 if m["ap"].lower() == "pm" else 0)
    mi = int(m["mi"] or 0)
    if h > 23 or mi > 59:
        return None
    ici = datetime.fromtimestamp(t, tz)
    if m["mois"]:
        mois = MOIS.get(m["mois"][:3].lower())
        if not mois:
            return None
        try:
            d = datetime(ici.year, mois, int(m["jour"]), h, mi, tzinfo=tz)
        except ValueError:
            return None
        if d.timestamp() < t - 86400:
            d = d.replace(year=ici.year + 1)
    else:
        d = ici.replace(hour=h, minute=mi, second=0, microsecond=0)
        if d.timestamp() <= t:
            d += timedelta(days=1)
    return int(d.timestamp())


def type_de_limite(texte: str) -> str:
    bas = texte.lower()
    if "session" in bas or "5-hour" in bas or "five_hour" in bas:
        return "five_hour"
    if "weekly" in bas or "seven_day" in bas:
        return "seven_day"
    return "inconnu"


def detecter_refus(texte: str, code, t: int):
    """(fin epoch, type) si la sortie d'un `claude` montre un refus d'usage, sinon None.

    Il faut une preuve d'échec : résultat final en erreur (« is_error »), ou code de sortie non nul
    avec un message de limite sur une des dernières lignes. Un événement rate_limit_event « rejected »
    seul (par exemple une limite propre à un modèle, avec repli) ne suffit pas ; il sert à dater la
    reprise. Le texte produit par le lot lui-même n'est jamais lu comme un refus."""
    rejets, echec, fin_texte, quoi = [], False, None, "inconnu"
    for ligne in texte.splitlines():
        s = ligne.strip()
        if not s.startswith("{"):
            continue
        try:
            ev = json.loads(s)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "rate_limit_event":
            info = ev.get("rate_limit_info") or {}
            if info.get("status") == "rejected" and str(info.get("resetsAt", "")).isdigit():
                rejets.append((int(info["resetsAt"]), str(info.get("rateLimitType") or "inconnu")))
            for nom, fen in (info.get("unifiedWindows") or {}).items():
                if isinstance(fen, dict) and fen.get("status") == "rejected" and str(fen.get("resetsAt", "")).isdigit():
                    rejets.append((int(fen["resetsAt"]), str(nom)))
        elif ev.get("type") == "result" and ev.get("is_error"):
            resultat = str(ev.get("result") or "")
            if ev.get("api_error_status") == 429 or LIMITE_TEXTE.search(resultat):
                echec, fin_texte, quoi = True, heure_de_reprise(resultat, t), type_de_limite(resultat)
    if not echec and code not in (0, None):
        dernieres = [l.strip() for l in texte.splitlines() if l.strip()][-5:]
        for l in dernieres:
            if LIMITE_LIGNE.search(l):
                echec, fin_texte, quoi = True, heure_de_reprise(l, t), type_de_limite(l)
                break
    if not echec:
        return None
    futurs = [r for r in rejets if r[0] > t]
    if futurs:
        fin, nom = max(futurs)
        return fin, (nom if quoi == "inconnu" else quoi)
    if fin_texte and fin_texte > t:
        return fin_texte, quoi
    return t + REFUS_DEFAUT, quoi


def lire_refus(reglages: dict):
    """(fin, type, source) du refus en cours (fin dans le futur), sinon None.
    Fichier : une ligne « <fin epoch> <type> <source> <date> »."""
    chemin = reglages.get("refus", "")
    if not chemin:
        return None
    try:
        champs = chemin_local(chemin).read_text(encoding="utf-8").split()
    except OSError:
        return None
    if len(champs) >= 2 and champs[0].isdigit() and int(champs[0]) > maintenant():
        return int(champs[0]), champs[1], (champs[2] if len(champs) > 2 else "?")
    return None


def noter_refus(reglages: dict, projet: str, fin: int, quoi: str, source: str) -> int:
    """Note un refus ; garde l'heure de reprise la plus lointaine. Rend la fin retenue."""
    chemin = reglages.get("refus", "")
    if not chemin:
        return fin
    actuel = lire_refus(reglages)
    if actuel and actuel[0] >= fin:
        fin, quoi, source = actuel
    f = chemin_local(chemin)
    reprise = datetime.fromtimestamp(fin).astimezone().isoformat(timespec="seconds")
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(f"{fin} {quoi} {re.sub(r'[^A-Za-z0-9_.-]', '_', source) or '?'} {reprise}\n", encoding="utf-8")
        os.chmod(tmp, 0o644)
        os.replace(tmp, f)
    except OSError:
        sys.stderr.write("claude-lot : refus impossible à noter\n")
    journaliser(reglages, projet, "refus-constate", f"type={quoi} reprise={reprise} source={source}")
    return fin


def presence(reglages: dict) -> str | None:
    """« present », « absent », ou None si l'outil de présence ne répond pas (aucun effet)."""
    try:
        r = subprocess.run(shlex.split(os.path.expanduser(reglages["presence"])), capture_output=True,
                           text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    sortie = r.stdout.strip().split()
    return sortie[0] if sortie and sortie[0] in ("present", "absent") else None


def ecoule_horaire(reglages: dict, debut: int, fin: int, t: int):
    """Part pondérée de la semaine écoulée (0 à 100) selon l'emploi du temps, ou None (ligne droite)."""
    outil = reglages.get("ligne_horaire", "")
    if not outil:
        return None
    try:
        r = subprocess.run(shlex.split(os.path.expanduser(outil)) + ["ligne", str(debut), str(fin), "--a", str(t)],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    v = r.stdout.strip()
    return min(100, int(v) // 10) if r.returncode == 0 and v.isdigit() else None


def turbo_actif(reglages: dict) -> bool:
    """TURBO : seulement sur demande expresse d'Antoine (CLAUDE_LOT_TURBO=1 ou fichier « turbo » présent)."""
    if os.environ.get("CLAUDE_LOT_TURBO") == "1":
        return True
    chemin = reglages.get("turbo", "")
    return bool(chemin) and chemin_local(chemin).exists()


def verifier(reglages: dict, prioritaire: bool, projet: str, sujet: str):
    """Renvoie (autorisé, message)."""
    # Refus d'usage constaté plus tôt (fenêtre de 5 h ou semaine pleine) : plus rien ne part avant
    # l'heure de reprise annoncée, même en --prioritaire (le compte refuserait de toute façon).
    refus = lire_refus(reglages)
    if refus:
        fin, quoi, _source = refus
        reprise = datetime.fromtimestamp(fin).astimezone().strftime("%d/%m %H:%M")
        journaliser(reglages, projet, "refus", f"limite-constatee type={quoi} reprise={reprise} sujet={sujet[:60]!r}")
        return False, (f"limite d'usage constatée ({quoi}), rien lancé ; reprise possible après le {reprise}")
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
    if u5 is not None and t >= fin5:
        u5 = 0
    if t >= fin7:
        u7 = 0
    if prioritaire:
        p5 = p7 = int(reglages["reserve"])
    else:
        p5, p7 = int(reglages["cinq_heures"]), int(reglages["semaine"])
    avance = int(reglages["avance"])
    # Présence d'Antoine (27/10/2026, règle commune à toutes les files) : seulement pour les projets de
    # presence_projets, jamais en --prioritaire ; chaque clé absente est sans effet.
    #   absent  : avance + avance_absent sur la ligne, fenêtre de 5 h à cinq_heures_absent % ;
    #   présent : fenêtre de 5 h à cinq_heures_present % au plus (ses sessions gardent le reste) ;
    #   TURBO   : le plafond « présent » est levé (la fenêtre de 5 h reste à cinq_heures %).
    qui = ""
    suivis = {x.strip() for x in reglages.get("presence_projets", "").split(",") if x.strip()}
    if not prioritaire and projet in suivis:
        qui = presence(reglages) or ""
        turbo = turbo_actif(reglages)
        if qui == "absent":
            if reglages.get("avance_absent", "").isdigit():
                avance += int(reglages["avance_absent"])
            if reglages.get("cinq_heures_absent", "").isdigit():
                p5 = int(reglages["cinq_heures_absent"])
        elif qui == "present" and not turbo and reglages.get("cinq_heures_present", "").isdigit():
            p5 = min(p5, int(reglages["cinq_heures_present"]))
        qui = f" antoine={qui or 'inconnu'}{' TURBO' if turbo else ''}"
    # Rythme (21/10/2026) : la semaine ne se dépense pas plus vite que la ligne régulière
    # (temps écoulé depuis la remise à zéro / 7 jours x plafond, + avance). Même formule
    # que la file Vuntum (quota-part.txt). Sans effet pour --prioritaire.
    ligne = False
    # sans_rythme (27/10/2026) : projets exemptés de la ligne, liste séparée par des virgules (motpop, sur demande
    # d'Antoine) ; les plafonds 5 h et semaine s'appliquent toujours.
    exemptes = {x.strip() for x in reglages.get("sans_rythme", "").split(",") if x.strip()}
    if not prioritaire and reglages["rythme"] == "1" and projet not in exemptes:
        ecoule = min(100, max(0, (t - (fin7 - SEMAINE)) * 100 // SEMAINE))
        # Ligne pondérée par l'emploi du temps (04/11/2026, /etc/emploi-du-temps.conf) : elle monte vite
        # la nuit, le dimanche et le lundi, lentement pendant les heures de travail d'Antoine.
        # Outil absent ou muet : ligne droite.
        pondere = ecoule_horaire(reglages, fin7 - SEMAINE, fin7, t)
        if pondere is not None:
            ecoule = pondere
        p7 = min(p7, ecoule * p7 // 100 + avance)
        ligne = True
    # Fenêtre de 5 h inconnue : pas de plafond de 5 h (les refus constatés le remplacent, voir plus haut).
    plein5 = u5 is not None and u5 >= p5
    etat = (f"5h={INCONNU if u5 is None else f'{u5}%'}/{p5}% semaine={u7}%/{p7}%"
            f"{' (ligne régulière)' if ligne else ''}{qui} ({origine})")
    if plein5 or u7 >= p7:
        fin = fin5 if plein5 else fin7
        quoi = "la fenêtre de 5 h" if plein5 else "la semaine"
        if ligne and not plein5 and u7 < int(reglages["semaine"]):
            # La ligne rattrape l'usage : fraction de semaine à attendre pour que repère > usage.
            quoi = "la ligne régulière de la semaine"
            plafond = int(reglages["semaine"])
            besoin = -(-(u7 - avance + 1) * 100 // plafond)
            fin = fin7 - SEMAINE + -(-besoin * SEMAINE // 100)
        reprise = datetime.fromtimestamp(fin).astimezone().strftime("%d/%m %H:%M")
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


# ---------------------------------------------------------------- file de tâches

NOM_TACHE = re.compile(r"^[a-z0-9_]+$")
NOM_MODELE = re.compile(r"^(?:auto|haiku|sonnet|opus|fable|claude-[a-z0-9][a-z0-9.\-]*)$")
DELAI_GARDE = 120
DELAI_GRACE = 10  # secondes entre TERM et KILL quand une tâche est arrêtée


def analyser_ligne_file(ligne: str):
    """« tache[:modele[:effort]] » -> (tache, modele, effort) ; ValueError(raison) si invalide.

    C'est le seul endroit où une ligne de file devient une commande : le nom de tâche reste
    ^[a-z0-9_]+$, le modèle un alias ou un identifiant claude-..., l'effort une valeur connue.
    Rien de ce qui suit n'est jamais interprété par un shell.
    """
    champs = ligne.strip().split(":")
    if len(champs) > 3:
        raise ValueError("plus de trois champs")
    tache = champs[0]
    modele = (champs[1] if len(champs) > 1 else "") or "auto"
    effort = (champs[2] if len(champs) > 2 else "")
    if not NOM_TACHE.fullmatch(tache):
        raise ValueError("nom de tâche invalide (attendu : lettres minuscules, chiffres, _)")
    if not NOM_MODELE.fullmatch(modele):
        raise ValueError("modèle invalide (auto, haiku, sonnet, opus, fable ou claude-...)")
    if effort and effort not in EFFORTS:
        raise ValueError(f"effort invalide (attendu : {', '.join(EFFORTS)})")
    return tache, modele, effort


def ligne_canonique(tache: str, modele: str, effort: str) -> str:
    """La ligne écrite dans la file est toujours reconstruite depuis les champs validés."""
    if modele == "auto" and not effort:
        return tache
    return ":".join([tache, modele] + ([effort] if effort else []))


def lignes_utiles(lignes):
    """Itère (ligne, résultat) pour chaque ligne de file qui n'est ni vide ni un commentaire ;
    résultat = (tache, modele, effort) ou ValueError."""
    for ligne in lignes:
        brut = ligne.strip()
        if not brut or brut.startswith("#"):
            continue
        try:
            yield brut, analyser_ligne_file(brut)
        except ValueError as e:
            yield brut, e


def chemin_file(reglages: dict) -> Path:
    return chemin_local(reglages["file"])


def annexe(chemin: Path, suffixe: str) -> Path:
    return chemin.with_name(chemin.name + suffixe)


@contextmanager
def verrou(chemin: Path, bloquant: bool):
    """Verrou flock sur un fichier annexe ; rend True si pris, False s'il est tenu ailleurs."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(chemin, os.O_CREAT | os.O_RDWR, 0o600)
    pris = True
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if bloquant else fcntl.LOCK_NB))
        except BlockingIOError:
            pris = False
        yield pris
    finally:
        os.close(fd)  # ferme aussi le verrou


def lire_lignes(chemin: Path) -> list:
    try:
        return chemin.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def ecrire_lignes(chemin: Path, lignes: list) -> None:
    """Écriture atomique : fichier voisin puis remplacement."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = annexe(chemin, ".tmp")
    tmp.write_text("".join(f"{l}\n" for l in lignes), encoding="utf-8")
    os.replace(tmp, chemin)


def horodatage() -> str:
    return datetime.fromtimestamp(maintenant()).astimezone().isoformat(timespec="seconds")


def noter(chemin: Path, texte: str) -> None:
    with open(chemin, "a", encoding="utf-8") as f:
        f.write(texte + "\n")


def lancements_du_jour(file_: Path) -> int:
    jour = datetime.fromtimestamp(maintenant()).astimezone().strftime("%Y-%m-%d")
    return sum(1 for l in lire_lignes(annexe(file_, ".lancements")) if l.startswith(jour))


def entier(reglages: dict, cle: str) -> int:
    try:
        valeur = int(reglages[cle])
    except ValueError:
        valeur = -1
    if valeur < 0:
        raise ValueError(f"réglage {cle} invalide ({reglages[cle]!r}, entier positif ou nul attendu)")
    return valeur


def purger_invalides(reglages: dict, file_: Path, ecrire: bool = True):
    """Sort de la file les lignes invalides (vers `.fait`, avec la raison) et rend les valides.
    À appeler sous le verrou d'édition. `ecrire=False` : ne touche à rien (mode à blanc)."""
    lignes = lire_lignes(file_)
    gardees, valides, retirees = [], [], []
    for ligne in lignes:
        brut = ligne.strip()
        if not brut or brut.startswith("#"):
            gardees.append(ligne)
            continue
        try:
            valides.append((brut, analyser_ligne_file(brut)))
            gardees.append(ligne)
        except ValueError as e:
            retirees.append((brut, str(e)))
    if retirees and ecrire:
        ecrire_lignes(file_, gardees)
        for brut, raison in retirees:
            noter(annexe(file_, ".fait"), f"{brut[:200]} # ignorée {horodatage()} : {raison}")
            journaliser(reglages, "file", "file-ignoree", f"raison={raison!r} ligne={brut[:60]!r}")
    return valides


def inserer(file_: Path, ligne: str, tete: bool) -> None:
    lignes = lire_lignes(file_)
    ecrire_lignes(file_, [ligne] + lignes if tete else lignes + [ligne])


def retirer_ligne(file_: Path, ligne: str) -> bool:
    lignes = lire_lignes(file_)
    for i, l in enumerate(lignes):
        if l.strip() == ligne:
            del lignes[i]
            ecrire_lignes(file_, lignes)
            return True
    return False


def garde_externe(reglages: dict, tache: str):
    """Contrôle facultatif (`file_garde`) : code 0 = autorisé ; sinon abstention, la dernière
    ligne affichée sert de raison. Même un échec de lancement fait s'abstenir (prudence)."""
    try:
        commande = shlex.split(reglages["file_garde"])
    except ValueError:
        return False, "file_garde illisible"
    if not commande:
        return True, ""
    commande[0] = os.path.expanduser(commande[0])
    try:
        r = subprocess.run(commande + [tache], capture_output=True, text=True, timeout=DELAI_GARDE,
                           env={**os.environ, "CLAUDE_LOT_TACHE": tache})
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"contrôle impossible ({type(e).__name__})"
    sortie = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode == 0, (sortie[-1] if sortie else f"code {r.returncode}")


def arreter_groupe(proc) -> None:
    """Arrête le lanceur et tout son groupe de processus : TERM, dix secondes de grâce, puis KILL
    (envoyé même si le lanceur est déjà parti, pour ses descendants restés vivants)."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=DELAI_GRACE)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def lancer_tache(commande: list, env: dict, delai: int):
    """Lance le lanceur dans son propre groupe de processus. Rend (code, délai dépassé).
    Délai dépassé, ou interruption de `claude-lot` (Ctrl-C, SIGTERM) : le groupe est arrêté,
    jamais laissé tourner sans verrou."""
    proc = subprocess.Popen(commande, env=env, start_new_session=True)
    try:
        return proc.wait(timeout=delai or None), False
    except subprocess.TimeoutExpired:
        arreter_groupe(proc)
        return proc.returncode, True
    except BaseException:
        arreter_groupe(proc)
        raise


def file_ajouter(reglages: dict, tache: str, modele: str, effort: str, tete: bool) -> int:
    try:
        champs = analyser_ligne_file(":".join([tache, modele, effort]))
    except ValueError as e:
        sys.stderr.write(f"claude-lot file : ligne refusée, {e}\n")
        return CODE_USAGE
    ligne = ligne_canonique(*champs)
    file_ = chemin_file(reglages)
    with verrou(annexe(file_, ".edit.lock"), True):
        inserer(file_, ligne, tete)
    journaliser(reglages, "file", "file-ajout", f"ligne={ligne!r} tete={tete}")
    print(f"ajouté{' en tête' if tete else ''} : {ligne}")
    return 0


def file_lister(reglages: dict) -> int:
    file_ = chemin_file(reglages)
    n = 0
    for brut, res in lignes_utiles(lire_lignes(file_)):
        n += 1
        if isinstance(res, ValueError):
            print(f"{n:3d}  INVALIDE ({res}) : {brut}")
        else:
            print(f"{n:3d}  {res[0]}  modèle={res[1]}  effort={res[2] or 'auto'}")
    if not n:
        print("file vide")
    print(f"aujourd'hui : {lancements_du_jour(file_)}/{reglages['file_max_par_jour']} lancements")
    return 0


def file_retirer(reglages: dict, tache: str, toutes: bool) -> int:
    file_ = chemin_file(reglages)
    retirees = 0
    with verrou(annexe(file_, ".edit.lock"), True):
        for brut, res in list(lignes_utiles(lire_lignes(file_))):
            if not isinstance(res, ValueError) and res[0] == tache and (toutes or not retirees):
                retirer_ligne(file_, brut)
                retirees += 1
    if not retirees:
        sys.stderr.write(f"claude-lot file : aucune ligne pour {tache!r}\n")
        return 1
    journaliser(reglages, "file", "file-retrait", f"tache={tache} lignes={retirees}")
    print(f"retiré : {retirees} ligne(s) de {tache}")
    return 0


def file_tourner(reglages: dict, a_blanc: bool = False, conf: str | None = None) -> int:
    """Lance au plus une tâche de la file. 0 : rien à faire ou tâche terminée ; 75 : abstention,
    arrêt sur limite d'usage (la tâche est remise en tête) ou interruption ; 1 : le lanceur a
    échoué ; 64 : réglage manquant ou invalide, lanceur impossible à démarrer."""
    file_ = chemin_file(reglages)
    try:
        lanceur = shlex.split(reglages["file_lanceur"])
        maxj, delai = entier(reglages, "file_max_par_jour"), entier(reglages, "file_delai")
    except ValueError as e:
        sys.stderr.write(f"claude-lot file : {e}\n")
        return CODE_USAGE
    if not lanceur:
        sys.stderr.write("claude-lot file : réglage file_lanceur absent (programme qui exécute une tâche)\n")
        return CODE_USAGE
    lanceur[0] = os.path.expanduser(lanceur[0])
    if not (os.access(lanceur[0], os.X_OK) or shutil.which(lanceur[0])):
        sys.stderr.write(f"claude-lot file : lanceur introuvable ou non exécutable ({lanceur[0]})\n")
        return CODE_USAGE

    with verrou(annexe(file_, ".lock"), False) as libre:
        if not libre:
            sys.stderr.write("claude-lot file : une autre exécution est en cours, rien lancé\n")
            return CODE_REFUS
        with verrou(annexe(file_, ".edit.lock"), True):
            valides = purger_invalides(reglages, file_, ecrire=not a_blanc)
        if not valides:
            print("file vide")
            return 0
        ligne, (tache, modele_ligne, effort_ligne) = valides[0]
        faits = lancements_du_jour(file_)
        if faits >= maxj:
            sys.stderr.write(f"claude-lot file : {faits}/{maxj} lancements aujourd'hui, {tache} attend demain\n")
            journaliser(reglages, "file", "file-abstention", f"quota-du-jour {faits}/{maxj} tache={tache}")
            return CODE_REFUS
        ok, raison = garde_externe(reglages, tache)
        if not ok:
            sys.stderr.write(f"claude-lot file : abstention pour {tache} ({raison})\n")
            journaliser(reglages, "file", "file-abstention", f"garde tache={tache} raison={raison!r}")
            return CODE_REFUS
        pour_la_file = dict(reglages, rythme=reglages["file_rythme"],
                            mesure_impossible=reglages["file_mesure_impossible"])
        autorise, message = verifier(pour_la_file, False, "file", tache)
        if not autorise:
            sys.stderr.write(f"claude-lot file : abstention pour {tache} ({message})\n")
            return CODE_REFUS
        # Choix de la table, d'après le nom de la tâche : transmis au lanceur à titre d'information
        # (variables *_CHOISI). Ce que dit la ligne (auto, alias, identifiant) est transmis tel quel,
        # pour que le lanceur puisse encore faire passer un champ « modele: » de son brief.
        modele, effort, pourquoi = choisir(tache, "", None if modele_ligne == "auto" else modele_ligne,
                                           effort_ligne or None, lire_registre(reglages))
        if a_blanc:
            print(f"à blanc : lancerait {tache} (ligne : modèle {modele_ligne}, effort {effort_ligne or 'auto'} ; "
                  f"choix de la table : {modele} {effort}, {pourquoi}) ; {message} ; {faits + 1}/{maxj} aujourd'hui")
            return 0

        # Retrait avant lancement : un plantage ou un redémarrage ne relance jamais deux fois.
        # La ligne a pu être retirée à la main pendant les contrôles : alors rien ne part.
        with verrou(annexe(file_, ".edit.lock"), True):
            if not retirer_ligne(file_, ligne):
                sys.stderr.write(f"claude-lot file : {tache} a quitté la file entre-temps, rien lancé\n")
                return 0
        noter(annexe(file_, ".lancements"), f"{horodatage()} {tache}")
        journaliser(reglages, "file", "file-lancement", f"tache={tache} modele={modele_ligne} effort={effort_ligne or 'auto'} "
                    f"(table : {modele} {effort}, {pourquoi}) {message}")
        env = {**os.environ, "CLAUDE_LOT_TACHE": tache, "CLAUDE_LOT_MODELE": modele_ligne,
               "CLAUDE_LOT_EFFORT": effort_ligne, "CLAUDE_LOT_MODELE_CHOISI": modele, "CLAUDE_LOT_EFFORT_CHOISI": effort}
        if conf:
            env["CLAUDE_LOT_CONF"] = os.path.abspath(conf)
        sys.stdout.flush()

        def interrompre(signum, frame):
            raise KeyboardInterrupt

        anciens = {}
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                anciens[sig] = signal.signal(sig, interrompre)
            except ValueError:  # pas le fil principal
                pass
        remettre, bilan, depasse, code = None, "", False, 0
        try:
            code, depasse = lancer_tache(lanceur + [tache, modele_ligne, effort_ligne], env, delai)
        except KeyboardInterrupt:
            remettre = "interrompue (SIGINT ou SIGTERM), son groupe de processus est arrêté"
        except OSError as e:
            remettre = f"lanceur impossible à démarrer ({type(e).__name__})"
            lignes = lire_lignes(annexe(file_, ".lancements"))[:-1]  # ce lancement n'a pas eu lieu
            ecrire_lignes(annexe(file_, ".lancements"), lignes)
        finally:
            for sig, ancien in anciens.items():
                signal.signal(sig, ancien)

        if remettre is None and code == CODE_REFUS and not depasse:
            remettre = "arrêt sur limite d'usage (code 75)"
        if remettre:
            with verrou(annexe(file_, ".edit.lock"), True):
                inserer(file_, ligne, True)
            journaliser(reglages, "file", "file-remise-en-tete", f"tache={tache} {remettre}")
            sys.stderr.write(f"claude-lot file : {tache} {remettre}, remise en tête\n")
            return CODE_USAGE if remettre.startswith("lanceur impossible") else CODE_REFUS
        bilan = "ok" if code == 0 else ("délai dépassé" if depasse else f"échec code {code}")
        noter(annexe(file_, ".fait"), f"{ligne} # {horodatage()} {bilan}")
        journaliser(reglages, "file", "file-termine", f"tache={tache} {bilan}")
        print(f"{tache} : {bilan}")
        return 0 if code == 0 and not depasse else 1


def analyser_file(argv):
    commun = argparse.ArgumentParser(add_help=False)
    commun.add_argument("--conf", default=argparse.SUPPRESS,
                        help=f"fichier de réglages (défaut {CONF_DEFAUT} ou $CLAUDE_LOT_CONF)")
    p = argparse.ArgumentParser(prog="claude-lot file", parents=[commun],
                                description="File de tâches : des chantiers lancés au fil de la semaine.")
    sous = p.add_subparsers(dest="action", required=True)
    a = sous.add_parser("ajouter", parents=[commun], help="ajoute une ligne tache[:modele[:effort]]")
    a.add_argument("tache")
    a.add_argument("modele", nargs="?", default="")
    a.add_argument("effort", nargs="?", default="")
    a.add_argument("--tete", action="store_true", help="en tête de file")
    sous.add_parser("lister", parents=[commun], help="affiche la file et le compteur du jour")
    r = sous.add_parser("retirer", parents=[commun], help="retire la première ligne d'une tâche")
    r.add_argument("tache")
    r.add_argument("--toutes", action="store_true", help="retire toutes les lignes de la tâche")
    t = sous.add_parser("tourner", parents=[commun], help="lance au plus une tâche, si tout l'autorise")
    t.add_argument("--a-blanc", action="store_true", help="décide et affiche, sans rien lancer ni modifier")
    return p.parse_args(argv)


def main_file(argv) -> int:
    a = analyser_file(argv)
    reglages = lire_reglages(getattr(a, "conf", None))
    if a.action == "ajouter":
        return file_ajouter(reglages, a.tache, a.modele, a.effort, a.tete)
    if a.action == "lister":
        return file_lister(reglages)
    if a.action == "retirer":
        return file_retirer(reglages, a.tache, a.toutes)
    return file_tourner(reglages, a.a_blanc, getattr(a, "conf", None) or os.environ.get("CLAUDE_LOT_CONF"))


# ---------------------------------------------------------------- refus (commande)

def main_refus(argv) -> int:
    """`claude-lot refus noter` : lit une sortie de claude (fichier ou entrée standard) et note le
    refus d'usage qu'elle montre (code 0, affiche « <fin epoch> <type> »), sinon code 1.
    `claude-lot refus etat` : affiche le refus en cours (code 0) ou rien (code 1)."""
    p = argparse.ArgumentParser(prog="claude-lot refus")
    p.add_argument("action", choices=("noter", "etat"))
    p.add_argument("--fichier", help="sortie de claude à lire (défaut : entrée standard)")
    p.add_argument("--code", type=int, default=1, help="code de sortie de claude (défaut 1)")
    p.add_argument("--source", default="externe", help="qui note le refus (journal)")
    p.add_argument("--projet", default="", help="nom du projet, pour le journal")
    p.add_argument("--conf", help=f"fichier de réglages (défaut {CONF_DEFAUT} ou $CLAUDE_LOT_CONF)")
    a = p.parse_args(argv)
    reglages = lire_reglages(a.conf)
    if a.action == "etat":
        refus = lire_refus(reglages)
        if not refus:
            return 1
        print(f"{refus[0]} {refus[1]} {refus[2]}")
        return 0
    try:
        texte = Path(a.fichier).read_text(encoding="utf-8", errors="replace") if a.fichier else sys.stdin.read()
    except OSError:
        sys.stderr.write("claude-lot refus : sortie illisible\n")
        return CODE_USAGE
    refus = detecter_refus(texte, a.code, maintenant())
    if not refus:
        return 1
    fin = noter_refus(reglages, a.projet, refus[0], refus[1], a.source)
    print(f"{fin} {refus[1]}")
    return 0


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


def pause_disque() -> str:
    """Contrôle d'entrée commun (05/11/2026, GO d'Antoine) : /usr/local/bin/pause-disque
    répond 0 quand le disque système dépasse 90 % ou le volume 95 %. Absent ou en échec : pas de pause."""
    try:
        r = subprocess.run(["/usr/local/bin/pause-disque"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


SCOPE_LOT = re.compile(r"^(/.*)?/tachesclaude\.slice/(tache-claude-\d+\.scope)$")


def scope_de(pid: int):
    """Chemin cgroup du scope de lot (tache-plafonnee) où vit ce processus, sinon None.
    Tout autre cgroup (service, session, cron) est ignoré : on ne le touche jamais."""
    try:
        for ligne in Path(f"/proc/{pid}/cgroup").read_text().splitlines():
            if ligne.startswith("0::"):
                chemin = ligne[3:].strip()
                return chemin if SCOPE_LOT.match(chemin) else None
    except OSError:
        pass
    return None


def pids_du_scope(scope: str) -> list:
    racine = os.environ.get("CLAUDE_LOT_CGROUP_RACINE", "/sys/fs/cgroup")
    try:
        texte = Path(racine + scope + "/cgroup.procs").read_text()
    except OSError:
        return []
    return [int(p) for p in texte.split() if p.isdigit() and int(p) != os.getpid()]


def fichier_survivants(reglages: dict | None = None) -> Path:
    """CLAUDE_LOT_SURVIVANTS, sinon le réglage `survivants`, sinon survivants.txt à côté du script."""
    chemin = os.environ.get("CLAUDE_LOT_SURVIVANTS") or (reglages or {}).get("survivants", "")
    return chemin_local(chemin) if chemin else Path(__file__).resolve().parent / "survivants.txt"


def motifs_survivants(reglages: dict | None = None) -> list:
    try:
        return [re.compile(l.strip()) for l in fichier_survivants(reglages).read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.lstrip().startswith("#")]
    except (OSError, re.error):
        return []


def epargnes(pids: list, reglages: dict | None = None) -> set:
    """Pids dont la ligne de commande, ou celle d'un ancêtre, correspond à un survivant autorisé."""
    motifs = motifs_survivants(reglages)

    def ligne(p):
        try:
            return Path(f"/proc/{p}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            return ""

    def parent(p):
        try:
            return int(Path(f"/proc/{p}/stat").read_text().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            return 0
    sauves = set()
    for p in pids:
        q, n = p, 0
        while q > 1 and n < 64:
            if any(m.search(ligne(q)) for m in motifs):
                sauves.add(p)
                break
            q, n = parent(q), n + 1
    return sauves


def nettoyer_scope(reglages: dict, projet: str, scope: str, delai: int = 30) -> None:
    """Fin du processus claude principal : termine ce qui reste dans le scope de CE lot
    (TERM, puis KILL après `delai` s) et journalise. Ne touche à aucun autre cgroup."""
    import signal
    restes = pids_du_scope(scope)
    sauves = epargnes(restes, reglages)
    restes = [p for p in restes if p not in sauves]
    if not restes:
        return

    def cmd(p):
        try:
            return Path(f"/proc/{p}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()[:80]
        except OSError:
            return "?"
    decrit = {p: cmd(p) for p in restes}
    for p in restes:
        try:
            os.kill(p, signal.SIGTERM)
        except OSError:
            pass
    fin = time.time() + delai
    def restants():
        return [p for p in pids_du_scope(scope) if p in decrit]
    while time.time() < fin and restants():
        time.sleep(0.5)
    tues = []
    for p in restants():
        try:
            os.kill(p, signal.SIGKILL)
            tues.append(p)
        except OSError:
            pass
    nom = scope.rsplit("/", 1)[-1]
    journaliser(reglages, projet, "scope-nettoye",
                f"scope={nom} termines={len(restes)} kill={len(tues)} "
                + " ".join(f"{p}:{decrit[p]!r}" for p in restes))


QUEUE_LUE = 1 << 20  # derniers octets gardés de chaque sortie (refus, coût)
COUT = re.compile(r'"total_cost_usd"\s*:\s*([0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?)')


def relayer_sortie(source, cible: int, queue: bytearray) -> None:
    """Recopie une sortie du lot vers la nôtre, sans tampon, en gardant ses derniers octets.
    Si notre lecteur ferme (tube cassé), on ferme aussi la lecture : le lot reçoit SIGPIPE comme
    s'il écrivait directement."""
    fd = source.fileno()
    while True:
        try:
            bloc = os.read(fd, 65536)
        except OSError:
            break
        if not bloc:
            break
        queue += bloc
        if len(queue) > QUEUE_LUE:
            del queue[:-QUEUE_LUE]
        vue = memoryview(bloc)
        try:
            while vue:
                vue = vue[os.write(cible, vue):]
        except OSError:
            break
    try:
        source.close()
    except OSError:
        pass


def executer_lot(reglages: dict, projet: str, commande: list, sujet: str = "") -> int:
    """Lance claude en processus fils (au lieu d'exec), attend sa fin, puis nettoie le scope du lot.

    Les sorties non reliées à un terminal sont recopiées telles quelles et leurs derniers octets lus
    à la fin : refus d'usage (noté, voir detecter_refus) et coût (« total_cost_usd », sorties json et
    stream-json). Une ligne « fin-lot » (durée, code, coût) part dans le journal."""
    import threading
    debut = time.monotonic()
    tuyaux = {fd: not os.isatty(fd) for fd in (1, 2)}
    proc = subprocess.Popen(commande, stdout=subprocess.PIPE if tuyaux[1] else None,
                            stderr=subprocess.PIPE if tuyaux[2] else None)
    queues = {1: bytearray(), 2: bytearray()}
    fils = []
    for fd, flux in ((1, proc.stdout), (2, proc.stderr)):
        if flux is not None:
            th = threading.Thread(target=relayer_sortie, args=(flux, fd, queues[fd]), daemon=True)
            th.start()
            fils.append(th)
    scope = None

    def relayer(signum, _frame):
        try:
            proc.send_signal(signum)
        except OSError:
            pass
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(s, relayer)
        except ValueError:  # pas le fil principal (tests)
            pass
    while True:
        try:
            code = proc.wait(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            pass
        finally:
            if scope is None:
                scope = scope_de(proc.pid)
    code = code if code >= 0 else 128 - code
    if scope is not None:
        try:
            nettoyer_scope(reglages, projet, scope)
        except Exception as e:  # le nettoyage ne doit jamais changer le code de sortie du lot
            journaliser(reglages, projet, "scope-erreur", repr(e)[:200])
    # Après le nettoyage (qui arrête les orphelins du scope) : un descendant détaché qui garde la
    # sortie ouverte ne bloque pas plus de 10 s ; il la perd à notre sortie (survivants.txt : les
    # lancements détachés autorisés redirigent leur sortie vers un fichier).
    for th in fils:
        th.join(timeout=10)
    if any(th.is_alive() for th in fils):
        journaliser(reglages, projet, "sortie-encore-ouverte", "un descendant du lot garde stdout ou stderr ouvert")
    try:
        sortie = queues[1].decode("utf-8", errors="replace")
        texte = sortie + "\n" + queues[2].decode("utf-8", errors="replace")
        couts = COUT.findall(sortie)
        cout = f"{float(couts[-1]):.4f}$" if couts else "inconnu"
        refus = detecter_refus(texte, code, maintenant())
        detail = f"duree={int(time.monotonic() - debut)}s code={code} cout={cout}"
        if refus:
            fin = noter_refus(reglages, projet, refus[0], refus[1], f"lot-{projet or 'sans-projet'}")
            detail += f" refus={refus[1]} reprise={datetime.fromtimestamp(fin).astimezone().isoformat(timespec='seconds')}"
        journaliser(reglages, projet, "fin-lot", f"{detail} sujet={sujet[:60]!r}")
    except Exception as e:  # le bilan ne doit jamais changer le code de sortie du lot
        journaliser(reglages, projet, "fin-lot-erreur", repr(e)[:200])
    return code


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "file":
        return main_file(argv[1:])
    if argv and argv[0] == "refus":
        return main_refus(argv[1:])
    a = analyser(argv)
    if a.args and a.args[0] == "file" and "--" not in argv:
        # « claude-lot --conf X file tourner » : la file, jamais un lancement de claude.
        return main_file((["--conf", a.conf] if a.conf else []) + a.args[1:])
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

    pause = pause_disque()
    if pause:
        journaliser(reglages, a.projet, "refus", f"pause disque : {pause} sujet={sujet[:60]!r}")
        sys.stderr.write(f"claude-lot : disque presque plein ({pause}), aucun nouveau lot\n")
        return CODE_REFUS
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
    else:
        i = a.args.index("--effort")
        if i + 1 < len(a.args):
            effort = a.args[i + 1]
    # Effort des sous-agents (05/11/2026, audit des coûts) : ~/.claude/settings.json fixe
    # CLAUDE_CODE_SUBAGENT_EFFORT=medium pour les sous-agents sans type ; un lot transmet le sien,
    # par l'environnement et par --settings (prioritaire sur les réglages utilisateur).
    # Si le lot impose déjà ses propres --settings, seule la variable d environnement est posée.
    os.environ["CLAUDE_CODE_SUBAGENT_EFFORT"] = effort
    if "--settings" not in a.args:
        ajout += ["--settings", json.dumps({"env": {"CLAUDE_CODE_SUBAGENT_EFFORT": effort}})]
    # Aucun serveur MCP dans un lot (08/11/2026, audit : un serveur global par `claude -p`, ~25 Mo et un
    # processus chacun, définitions d'outils dans le contexte). Un --mcp-config explicite reste servi.
    if reglages.get("strict_mcp", "1") == "1" and "--strict-mcp-config" not in a.args:
        ajout.append("--strict-mcp-config")
    journaliser(reglages, a.projet, "lancement",
                f"{message} modele={modele if '--model' not in a.args else 'commande'} effort={effort} ({raison}) sujet={sujet[:60]!r}")
    sys.stdout.flush()
    return executer_lot(reglages, a.projet, commande + ajout + a.args, sujet)


if __name__ == "__main__":
    sys.exit(main())
