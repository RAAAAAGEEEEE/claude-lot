# Configuration

Fichier lu : `--conf`, sinon `$CLAUDE_LOT_CONF`, sinon `/etc/claude-lot.conf`. Une ligne
`clé=valeur` par réglage, `#` pour commenter. Clé absente : valeur par défaut.

| Clé | Défaut | Rôle |
|---|---|---|
| `cinq_heures` | 85 | plafond de la fenêtre de 5 h, en % |
| `semaine` | 90 | plafond de la semaine, en % |
| `reserve` | 95 | plafond des lots `--prioritaire`, pour les deux fenêtres |
| `sonde` | (vide) | commande de mesure ; vide = aucune mesure |
| `sonde_delai` | 120 | délai maximal de la sonde, en secondes |
| `mesure_impossible` | `lancer` | `lancer` ou `refuser` quand aucune mesure n'est utilisable |
| `journal` | `~/.local/state/claude-lot/journal.log` | journal des lancements et refus |
| `etat` | `~/.local/state/claude-lot/derniere-mesure` | dernière mesure valable |
| `registre` | `~/.claude/modeles.json` | identifiants des modèles (facultatif) |
| `commande` | `claude` | programme lancé (`$CLAUDE_LOT_COMMANDE` l'emporte, utile en test) |

## Sonde

N'importe quelle commande qui affiche, sur sa dernière ligne :

```text
<% semaine> <% fenêtre de 5 h> <fin de la semaine, epoch> <fin de la fenêtre de 5 h, epoch>
```

par exemple `21 64 1793041200 1792479600`, et sort en code 0. `scripts/sonde-quota.sh` le fait
avec Claude Code lui-même ; ses variables : `CLAUDE_LOT_SONDE_CACHE` (secondes, 900),
`CLAUDE_LOT_SONDE_FICHIER` (cache), `CLAUDE_LOT_SONDE_MODELE` (`claude-haiku-5-5`).

## Registre des modèles

Facultatif. Pour suivre une nouvelle génération sans modifier le lanceur :

```json
{"familles": {"haiku": {"id": "claude-haiku-5-5"}, "sonnet": {"id": "claude-sonnet-5-5"},
              "opus": {"id": "claude-opus-5-5"}, "fable": {"id": "claude-fable-5-1"}}}
```

Un registre absent ou illisible laisse les identifiants intégrés.
