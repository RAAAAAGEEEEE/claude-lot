# Configuration

Fichier lu : `--conf`, sinon `$CLAUDE_LOT_CONF`, sinon `/etc/claude-lot.conf`. Une ligne
`clé=valeur` par réglage, `#` pour commenter. Clé absente : valeur par défaut.

| Clé | Défaut | Rôle |
|---|---|---|
| `cinq_heures` | 85 | plafond de la fenêtre de 5 h, en % |
| `semaine` | 90 | plafond de la semaine, en % |
| `reserve` | 95 | plafond des lots `--prioritaire`, pour les deux fenêtres |
| `rythme` | 0 | `1` : hors `--prioritaire`, la semaine ne dépasse pas la ligne régulière (temps écoulé depuis la remise à zéro / 7 jours x `semaine`, plus `avance`, jamais plus que `semaine`) |
| `avance` | 5 | points d'avance sur la ligne régulière (avec `rythme=1`) |
| `sonde` | (vide) | commande de mesure ; vide = aucune mesure |
| `sonde_delai` | 120 | délai maximal de la sonde, en secondes |
| `mesure_impossible` | `lancer` | `lancer` ou `refuser` quand aucune mesure n'est utilisable |
| `journal` | `~/.local/state/claude-lot/journal.log` | journal des lancements et refus |
| `etat` | `~/.local/state/claude-lot/derniere-mesure` | dernière mesure valable |
| `registre` | `~/.claude/modeles.json` | identifiants des modèles (facultatif) |
| `commande` | `claude` | programme lancé (`$CLAUDE_LOT_COMMANDE` l'emporte, utile en test) |

## File de tâches

Réglages de `claude-lot file` (détail : [FILE.md](FILE.md)). Les autres réglages (plafonds,
sonde, journal) s'appliquent aussi à la file.

| Clé | Défaut | Rôle |
|---|---|---|
| `file` | `~/.local/state/claude-lot/file.txt` | fichier de file, une ligne `tache[:modele[:effort]]` |
| `file_max_par_jour` | 2 | lancements au plus par jour local |
| `file_lanceur` | (vide, obligatoire) | programme appelé avec `<tache> <modele ou auto> <effort ou vide>` ; code 0 fait, 75 limite d'usage (remise en tête), autre échec |
| `file_garde` | (vide) | contrôle facultatif appelé avec `<tache>` ; code autre que 0 : la file s'abstient |
| `file_delai` | 21600 | durée maximale d'une tâche en secondes (entier positif ou nul), 0 = illimitée |
| `file_rythme` | 1 | `1` : la ligne régulière de la semaine s'applique à la file, quel que soit `rythme` |
| `file_mesure_impossible` | `refuser` | `refuser` ou `lancer` sans mesure de quota (distinct de `mesure_impossible`) |

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
