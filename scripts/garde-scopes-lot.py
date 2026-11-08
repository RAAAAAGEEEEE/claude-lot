#!/usr/bin/env python3
"""garde-scopes-lot : zéro token, nettoie tout scope de lot (tache-claude-*.scope) sans processus
`claude` depuis plus de 2 h, et l'écrit dans la section « Incidents » de la boîte du pilote.

Filet de secours de `claude-lot` (qui nettoie déjà le scope à la fin du lot) : couvre un lot dont
le lanceur est mort sans nettoyer. Ne touche qu'aux unités `tache-claude-<n>.scope` de la slice
`tachesclaude.slice`, jamais un service ni un autre scope.

Les survivants autorisés (scripts/survivants.txt) et leurs descendants sont épargnés : seuls
les autres processus du scope sont arrêtés (TERM puis KILL après 30 s), jamais `systemctl stop`.

Usage : garde-scopes-lot.py [--essai]   (--essai : n'arrête rien, n'écrit rien, affiche)
Réglages par variables d'environnement (tests) : GARDE_ETAT, GARDE_INBOX, GARDE_CGROUP, GARDE_DELAI.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ETAT = Path(os.environ.get("GARDE_ETAT", "/var/lib/claude-lot/garde-scopes.json"))
INBOX = Path(os.environ.get("GARDE_INBOX", str(Path.home() / "handoff" / "pilote_inbox" / "maitre.md")))
CGROUP = Path(os.environ.get("GARDE_CGROUP", "/sys/fs/cgroup/tachesclaude.slice"))
DELAI = int(os.environ.get("GARDE_DELAI", str(2 * 3600)))
NOM = re.compile(r"^tache-claude-\d+\.scope$")


def pids(unite: str) -> list:
    try:
        return [int(p) for p in (CGROUP / unite / "cgroup.procs").read_text().split() if p.isdigit()]
    except OSError:
        return []


def comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return ""


def cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()[:70]
    except OSError:
        return "?"


def unites() -> list:
    try:
        return sorted(u.name for u in CGROUP.iterdir() if u.is_dir() and NOM.match(u.name))
    except OSError:
        return []


SURVIVANTS = os.environ.get("CLAUDE_LOT_SURVIVANTS", str(Path(__file__).resolve().parent / "survivants.txt"))


def epargnes(membres: list) -> set:
    """Pids dont la ligne de commande, ou celle d'un ancêtre, correspond à un survivant autorisé."""
    try:
        motifs = [re.compile(l.strip()) for l in Path(SURVIVANTS).read_text(encoding="utf-8").splitlines()
                  if l.strip() and not l.lstrip().startswith("#")]
    except (OSError, re.error):
        motifs = []

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
    for p in membres:
        q, n = p, 0
        while q > 1 and n < 64:
            if any(m.search(ligne(q)) for m in motifs):
                sauves.add(p)
                break
            q, n = parent(q), n + 1
    return sauves


def incident(texte: str) -> None:
    ligne = f"- {datetime.now().astimezone().strftime('%d/%m/%Y %H:%M')} (Paris) garde-scopes-lot : {texte}\n"
    lignes = INBOX.read_text(encoding="utf-8").splitlines(keepends=True) if INBOX.exists() else ["## Incidents\n"]
    for i, l in enumerate(lignes):
        if l.strip() == "## Incidents":
            lignes.insert(i + 1, ligne)
            break
    else:
        lignes += ["\n", "## Incidents\n", ligne]
    tmp = INBOX.with_suffix(".md.tmp")
    tmp.write_text("".join(lignes), encoding="utf-8")
    os.replace(tmp, INBOX)


def main() -> int:
    essai = "--essai" in sys.argv
    maintenant = int(time.time())
    try:
        etat = json.loads(ETAT.read_text())
    except (OSError, ValueError):
        etat = {}
    nouveau = {}
    for unite in unites():
        membres = pids(unite)
        if not membres or any(comm(p) == "claude" for p in membres):
            continue  # vide (il disparaîtra seul) ou lot vivant
        sauves = epargnes(membres)
        membres = [p for p in membres if p not in sauves]
        if not membres:
            continue  # ne reste que des survivants autorisés
        depuis = etat.get(unite, maintenant)
        nouveau[unite] = depuis
        if maintenant - depuis < DELAI:
            continue
        resume = " ".join(f"{p}:{cmdline(p)!r}" for p in membres[:5])
        if essai:
            print(f"A ARRETER {unite} sans claude depuis {(maintenant - depuis) // 60} min : {resume}")
            continue
        for p in membres:
            try:
                os.kill(p, signal.SIGTERM)
            except OSError:
                pass
        time.sleep(30)
        for p in pids(unite):
            if p in membres:
                try:
                    os.kill(p, signal.SIGKILL)
                except OSError:
                    pass
        incident(f"scope {unite} nettoyé (aucun processus claude depuis {(maintenant - depuis) // 3600} h, "
                 f"{len(membres)} processus arrêtés, survivants autorisés épargnés : {len(sauves)} : {resume})")
        nouveau.pop(unite, None)
    if not essai:
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        ETAT.write_text(json.dumps(nouveau))
    return 0


if __name__ == "__main__":
    sys.exit(main())
