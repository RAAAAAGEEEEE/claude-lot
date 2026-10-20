# claude-lot

**In English.** A shared usage cap and automatic model choice for headless Claude Code jobs
(`claude -p` in cron, task queues, nightly scripts). Put `claude-lot` in front of every batch job on
a machine: before starting, it reads the real subscription usage (5-hour window and week) and
refuses to start above a common cap (85 % / 90 % by default, exit code 75, one log line), keeping
the rest for priority work and interactive sessions. It also picks the model and effort from the
task subject (Sonnet medium by default, Opus for architecture, security, review and fact-checking,
Haiku for measurements and bulk work), with an explicit `modele:` field that always wins. Python
standard library only, no secret ever printed. Documentation is in French.

Lanceur commun des travaux en lot de Claude Code : **un plafond de quota partagé par tous les
projets** d'une machine, et **le bon modèle choisi automatiquement** selon la tâche.

## Le problème

Plusieurs projets lancent `claude -p` sur la même machine et le même abonnement. Chacun surveille
au mieux sa propre consommation, aucun ne voit celle des autres. Il suffit qu'un projet enchaîne
des chantiers sur Opus pendant la nuit pour pousser la fenêtre de 5 h au-delà de 100 % : tout
s'arrête, les autres projets comme les sessions interactives du lendemain matin. Et chaque script
choisit son modèle à la main, souvent le plus cher « par sécurité ».

## Ce qu'il apporte

- **Un plafond commun** : aucun lot ne démarre au-delà de 85 % de la fenêtre de 5 h ou de 90 % de
  la semaine (réglable). Les lots marqués `--prioritaire` vont jusqu'à 95 %. Les sessions
  interactives ne passent pas par le lanceur : la marge leur reste.
- **Un refus net** : code de sortie 75, un message qui dit quelle fenêtre bloque et quand elle se
  libère, une ligne dans le journal.
- **Le choix du modèle et de l'effort** d'après le sujet de la tâche, avec un champ explicite qui
  l'emporte. Un `--model` déjà présent dans la commande est respecté.
- **Une sonde** qui lit l'utilisation réelle de l'abonnement, gardée en cache 15 minutes.
- **Un skill** (`SKILL.md`) : Claude fait l'inventaire des lanceurs, installe, branche avec
  sauvegardes et montre la preuve.

## Comment ça marche

1. **Installer le skill une fois** :
   `git clone https://github.com/RAAAAAGEEEEE/claude-lot ~/.claude/skills/claude-lot`.
2. **Le demander** : dans une session Claude Code, « mets un plafond commun sur mes scripts
   claude -p », ou `/claude-lot`.
3. **Se laisser guider** : Claude pose deux ou trois questions (plafonds, travail prioritaire),
   liste vos lanceurs, puis branche chacun avec votre accord.

Sans Claude, à la main :

```bash
install -m 755 ~/.claude/skills/claude-lot/scripts/claude_lot.py ~/.local/bin/claude-lot
mkdir -p ~/.config && cp ~/.claude/skills/claude-lot/examples/claude-lot.conf ~/.config/claude-lot.conf
export CLAUDE_LOT_CONF=~/.config/claude-lot.conf
claude-lot --verifier                         # autorisé (0) ou plafond atteint (75)
claude-lot --choisir --sujet "Audit de sécurité de l'API"
# claude-opus-5-5 medium (architecture, logique centrale, sécurité, contre-revue ou vérification factuelle)
claude-lot --projet blog --sujet "Rédiger un article sur le salon" -- -p "$(cat brief.md)" --output-format json
```

Dans une crontab, pour un lot dont on ne veut pas modifier le code :

```cron
17 2 * * * claude-lot --verifier --projet site >/dev/null 2>&1 && /chemin/lot_de_nuit.sh
```

## Choix du modèle

| Sujet de la tâche | Modèle | Effort |
|---|---|---|
| architecture, logique centrale, sécurité, réseau, refonte, contre-revue, vérification factuelle | Opus | medium |
| extraction, documents, PDF, article, brève, publication, texte factuel | Sonnet | high |
| mesure, comptage, tri, inventaire, gros volume, formatage (sans rédaction ni code) | Haiku | low |
| tout le reste | Sonnet | medium |

Ordre : `--modele` / `--effort`, puis les lignes `modele:` et `effort:` du brief, puis la table.
Seul le titre `# ...` du brief est lu par la table : son corps contient souvent des consignes
générales (« attention à la sécurité ») qui enverraient tout sur Opus. Raisons de chaque ligne :
[docs/USAGE.md](docs/USAGE.md).

## Documentation

- [Installation](docs/INSTALLATION.md)
- [Utilisation](docs/USAGE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Limites](docs/LIMITATIONS.md)
- [Dépannage](docs/TROUBLESHOOTING.md)
- [Confidentialité et sécurité](docs/PRIVACY_AND_SECURITY.md)

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Aucun appel réseau : la sonde et `claude` sont remplacés par de faux programmes.

## Licence

MIT, voir [LICENSE](LICENSE). Contributions : [CONTRIBUTING.md](CONTRIBUTING.md). Signaler une
faille : [SECURITY.md](SECURITY.md).
