#!/usr/bin/env python3
"""garde-scopes-lot : zéro token, arrête tout scope de lot (tache-claude-*.scope) sans processus
`claude` depuis plus de 2 h, et l'écrit dans la section « Incidents » de la boîte du pilote.

Filet de secours de `claude-lot` (qui nettoie déjà le scope à la fin du lot) : couvre un lot dont
le lanceur est mort sans nettoyer. Ne touche qu'aux unités `tache-claude-<n>.scope` de la slice
`tachesclaude.slice`, jamais un service ni un autre scope.

Usage : garde-scopes-lot.py [--essai]   (--essai : n'arrête rien, n'écrit rien, affiche)
Réglages par variables d'environnement (tests) : GARDE_ETAT, GARDE_INBOX, GARDE_CGROUP, GARDE_DELAI.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ETAT = Path(os.environ.get("GARDE_ETAT", "/var/lib/claude-lot/garde-scopes.json"))
INBOX = Path(os.environ.get("GARDE_INBOX", "/root/handoff/pilote_inbox/maitre.md"))
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
        depuis = etat.get(unite, maintenant)
        nouveau[unite] = depuis
        if maintenant - depuis < DELAI:
            continue
        resume = " ".join(f"{p}:{cmdline(p)!r}" for p in membres[:5])
        if essai:
            print(f"A ARRETER {unite} sans claude depuis {(maintenant - depuis) // 60} min : {resume}")
            continue
        r = subprocess.run(["systemctl", "stop", unite], capture_output=True, text=True, timeout=120)
        incident(f"scope {unite} arrêté (aucun processus claude depuis {(maintenant - depuis) // 3600} h, "
                 f"{len(membres)} processus : {resume}) code={r.returncode}")
        nouveau.pop(unite, None)
    if not essai:
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        ETAT.write_text(json.dumps(nouveau))
    return 0


if __name__ == "__main__":
    sys.exit(main())
