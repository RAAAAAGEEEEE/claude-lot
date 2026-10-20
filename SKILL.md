---
name: claude-lot
description: >
  Lanceur commun des travaux en lot de Claude Code (`claude -p`, cron, files de tâches, scripts de
  nuit) : un plafond de quota partagé par tous les projets d'une machine (85 % de la fenêtre de
  5 h, 90 % de la semaine par défaut, réserve à 95 % pour le travail prioritaire), refus avec un
  code de sortie dédié (75) et un journal, et choix automatique du modèle et de l'effort selon le
  type de tâche (Sonnet medium par défaut, Sonnet high pour l'extraction et le texte publié
  factuel, Opus medium pour l'architecture, la sécurité, la contre-revue et la vérification
  factuelle, Haiku low pour les mesures et le gros volume simple), avec un champ `modele:`
  explicite qui l'emporte. À utiliser quand l'utilisateur dit « mes scripts claude -p épuisent
  mon quota », « un projet a bloqué tous les autres », « plafond commun », « choisir le modèle
  automatiquement pour mes tâches de fond », ou en anglais « shared usage cap for headless
  Claude Code jobs », « pick the model per task automatically ». N'affiche jamais de secret.
license: MIT
compatibility: >
  Claude Code 2.1 ou plus récent, abonnement Claude (sonde observée sur Max). Python 3.9+ (bibliothèque standard
  seulement). Sonde fournie : bash et jq. Linux et macOS ; sous Windows, lancer depuis WSL.
metadata:
  author: Anto1nx
  version: "1.0.0"
  repository: https://github.com/RAAAAAGEEEEE/claude-lot
allowed-tools: Read Edit Bash(python3:*) Bash(crontab -l) Bash(claude-lot:*)
---

# claude-lot

Ce skill installe et branche `claude-lot`, un lanceur placé devant chaque appel `claude -p` fait
par un script. Il sert quand plusieurs projets consomment le même abonnement : sans plafond
commun, le projet le plus gourmand épuise la fenêtre de 5 h et tout s'arrête, sessions
interactives comprises.

## Déroulé

### 0. Cadrage

Avant toute modification, demander à l'utilisateur (une seule fois, deux à trois questions au plus,
avec `AskUserQuestion` si l'outil est disponible) :

1. Les plafonds voulus (défaut : 85 % de la fenêtre de 5 h, 90 % de la semaine, réserve 95 %).
2. Ce qui doit rester prioritaire (travail lancé avec `--prioritaire`, qui va jusqu'à la réserve).
3. Si une mesure impossible doit laisser passer (`lancer`, défaut) ou bloquer (`refuser`).

Ne pas poser une question dont la réponse est déjà dans la conversation ou la configuration.

### 1. Inventaire en lecture seule

Lister ce qui lance Claude sans humain derrière : `crontab -l`, `/etc/cron.d/`, unités systemd
(`systemctl list-timers`), sessions tmux, et une recherche de `claude -p` dans les scripts des
projets. Pour chaque lanceur : projet, fréquence, modèle imposé ou non, ce qui se passe s'il ne
démarre pas (une nuit sautée est-elle sans dommage ?). Montrer ce tableau avant d'aller plus loin.

### 2. Installation

```bash
python3 scripts/claude_lot.py --version
install -m 755 scripts/claude_lot.py /usr/local/bin/claude-lot   # ou ~/.local/bin/claude-lot
cp examples/claude-lot.conf /etc/claude-lot.conf                  # ou CLAUDE_LOT_CONF=...
claude-lot --verifier                                             # code 0 : autorisé
```

La sonde fournie (`scripts/sonde-quota.sh`) lit l'utilisation réelle de l'abonnement ; tout autre
programme qui affiche la même ligne convient. Détail : [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

### 3. Branchement, lanceur par lanceur

Toujours une sauvegarde horodatée avant de modifier (`cp -p f f.bak-$(date -u +%Y%m%dT%H%M%SZ)`,
`crontab -l > crontab.bak-...`), et l'accord de l'utilisateur pour chaque fichier.

- Script qui appelle `claude -p ... --model X` : remplacer `claude` par
  `claude-lot --projet P --sujet "..." --` et retirer `--model` pour laisser le choix au lanceur
  (le garder s'il est voulu : un `--model` passé à claude est respecté).
- Lot dont on ne veut pas toucher le code : préfixer la ligne de crontab par
  `claude-lot --verifier --projet P >/dev/null 2>&1 &&`.
- Script en cours d'exécution : écrire le nouveau fichier à côté puis `mv` (bash lit ses scripts
  au fil de l'eau ; une modification sur place peut casser l'exécution en cours).
- Ne pas brider appel par appel une chaîne qui rédige puis relit : un refus entre les deux ferait
  passer un texte non relu. Brider le lancement du lot entier.

### 4. Preuve

Montrer : les lignes modifiées (diff), un refus provoqué avec un plafond abaissé dans une copie
de la configuration (`--conf`), le choix du modèle sur trois sujets réels (`claude-lot --choisir`),
et la dernière ligne du journal.

## Table de choix du modèle

Première règle reconnue dans le sujet (`--sujet`, plus le titre `# ...` du brief donné par
`--sujet-fichier` ; le corps du brief est ignoré car ses consignes générales fausseraient le choix) :

| Sujet | Modèle | Effort |
|---|---|---|
| architecture, logique centrale, sécurité, réseau, refonte, contre-revue, vérification factuelle | Opus | medium |
| extraction, documents, PDF, article, brève, publication, texte factuel | Sonnet | high |
| mesure, comptage, tri, inventaire, gros volume, formatage (sans rédaction ni code) | Haiku | low |
| tout le reste | Sonnet | medium |

`--modele`, puis une ligne `modele: opus high` du brief, puis la table. Détail et raisons :
[docs/USAGE.md](docs/USAGE.md).

## Interdits

- Ne jamais afficher un jeton, une clé ou le contenu d'un fichier d'identifiants.
- Ne jamais couper un lot déjà lancé : `claude-lot` décide seulement au démarrage.
- Ne pas brancher les sessions interactives : la réserve leur est destinée.
