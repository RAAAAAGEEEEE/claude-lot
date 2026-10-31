# File de tâches

`claude-lot file` répartit les gros chantiers de `claude -p` sur la semaine au lieu de tout lancer
d'un coup. On range les tâches dans une file ; une entrée de cron tente d'en lancer une toutes les
quelques heures. Chaque tentative passe par les mêmes barrières que le reste de `claude-lot` :
aucune tâche ne démarre au-delà du plafond commun ni au-dessus de la ligne régulière de la semaine.
Le contrôle a lieu au démarrage seulement ([LIMITATIONS.md](LIMITATIONS.md)) : une tâche longue peut
encore dépasser le plafond.

Voir aussi : [USAGE.md](USAGE.md) (plafond, modèle), [CONFIGURATION.md](CONFIGURATION.md)
(réglages `file_*`), [LIMITATIONS.md](LIMITATIONS.md).

## La file

Un fichier texte (réglage `file`), une tâche par ligne :

```text
# Les lignes vides et celles qui commencent par # sont ignorées.
audit_securite_api
refonte_moteur:opus:high
inventaire_liens:haiku
```

Format : `tache[:modele[:effort]]`.

| Champ | Valeurs | Défaut |
|---|---|---|
| `tache` | `^[a-z0-9_]+$` : minuscules, chiffres, `_` | obligatoire |
| `modele` | `auto`, `haiku`, `sonnet`, `opus`, `fable` ou un identifiant `claude-...` | `auto` : la table de [USAGE.md](USAGE.md) choisit d'après le nom de la tâche (`audit_securite_api` donne Opus) |
| `effort` | `low`, `medium`, `high`, `xhigh`, `max` | celui du modèle choisi |

Une ligne qui ne respecte pas ce format n'est jamais exécutée : elle est retirée de la file,
rangée dans le fichier `.fait` avec la raison, et notée au journal. Le nom de tâche contraint est
la protection contre l'injection : il ne peut contenir ni espace, ni `;`, ni `/`, ni `$`, et il
n'est de toute façon jamais passé à un shell.

## Les commandes

```bash
claude-lot file ajouter refonte_moteur opus high     # ajoute à la fin (--tete : en tête)
claude-lot file lister                               # file + lancements du jour
claude-lot file retirer refonte_moteur               # première ligne de la tâche (--toutes : toutes)
claude-lot file tourner --a-blanc                    # décide et affiche, ne lance rien et ne touche pas à la file
claude-lot file tourner                              # lance au plus UNE tâche si tout l'autorise
```

Chaque commande accepte `--conf fichier`, avant ou après `file` (comme `claude-lot`). Le mode
`--a-blanc` peut quand même mettre à jour le journal et la dernière mesure de quota. Exemple de sortie :

```text
$ claude-lot file lister
  1  audit_securite_api  modèle=auto  effort=auto
  2  refonte_moteur  modèle=opus  effort=high
aujourd'hui : 0/2 lancements
$ claude-lot file tourner --a-blanc
à blanc : lancerait audit_securite_api (ligne : modèle auto, effort auto ; choix de la table : claude-opus-5-5 medium, architecture, logique centrale, sécurité, contre-revue ou vérification factuelle) ; 5h=10%/85% semaine=10%/34% (ligne régulière) (sonde) ; 1/2 aujourd'hui
```

## Ce que fait `tourner`

Dans l'ordre, et il s'arrête au premier obstacle :

1. prend le verrou de la file (une seule exécution à la fois) ;
2. écarte les lignes invalides (sauf en mode `--a-blanc`, qui ne modifie pas la file) ;
3. file vide : sort en code 0 ;
4. compte les lancements du jour (`.lancements`) : au plafond `file_max_par_jour`, s'abstient ;
5. lance le contrôle facultatif `file_garde` ;
6. vérifie le plafond commun **et la ligne régulière de la semaine** (même calcul que
   `rythme=1`, activé d'office pour la file par `file_rythme=1`) ;
7. calcule le choix de la table d'après le nom de la tâche (information pour le lanceur) ;
8. **retire la ligne de la file** (si elle a été retirée à la main entre-temps, rien ne part), note
   le lancement, puis exécute le lanceur ;
9. selon le code du lanceur : 0, la ligne va dans `.fait` ; **75, la ligne revient en tête** de
   file ; autre code, la ligne va dans `.fait` avec « échec code N » et n'est pas rejouée.

Si `claude-lot file tourner` reçoit Ctrl-C ou SIGTERM pendant une tâche, il arrête le groupe de
processus du lanceur (TERM, 10 secondes, puis KILL), remet la tâche en tête et sort en 75 : jamais
une tâche qui continue sans verrou.

Codes de sortie de `tourner` : **0** rien à faire ou tâche terminée ; **75** abstention (quota du
jour, garde, plafond, autre exécution en cours, arrêt sur limite d'usage) ; **1** le lanceur a
échoué ; **64** réglage manquant ou invalide (`file_lanceur` introuvable, nombre invalide), ou
lanceur impossible à démarrer (la tâche est alors remise en tête et ne compte pas dans le quota du jour).

## Le lanceur

`file_lanceur` est un programme (sans shell, arguments séparés par des espaces) que la file appelle
avec trois arguments : `<tache> <modele> <effort>`, tels que la ligne les dit (`auto` si le modèle
est omis, chaîne vide si l'effort est omis). Il décide de ce que « exécuter la tâche » veut dire.
Variables d'environnement transmises :

| Variable | Valeur |
|---|---|
| `CLAUDE_LOT_TACHE`, `CLAUDE_LOT_MODELE`, `CLAUDE_LOT_EFFORT` | les trois arguments |
| `CLAUDE_LOT_MODELE_CHOISI`, `CLAUDE_LOT_EFFORT_CHOISI` | le choix de la table d'après le nom de la tâche (ou la ligne, si elle impose un modèle) : à utiliser si votre lanceur n'appelle pas `claude-lot` |
| `CLAUDE_LOT_CONF` | chemin absolu du fichier de réglages utilisé par la file (donné par `--conf` ou déjà dans l'environnement), pour que le `claude-lot` du lanceur lise les mêmes plafonds |

Son code de sortie parle à la file :

| Code | Sens | Effet |
|---|---|---|
| 0 | tâche faite | `.fait` |
| 75 | limite d'usage atteinte (ou plafond refusé) | remise en tête, réessayée plus tard |
| autre | échec | `.fait`, pas de nouvel essai |

[`examples/lanceur-exemple.sh`](../examples/lanceur-exemple.sh) lit un brief
`<dossier>/<tache>.md`, appelle `claude-lot ... -- -p "<brief>" --output-format json` (le champ
`modele:` du brief reste prioritaire quand la ligne dit `auto`) et traduit une réponse en erreur qui
parle de limite d'usage en code 75 (le texte reconnu est celui observé de Claude Code ; à vérifier
sur votre version). Copiez-le et adaptez-le : c'est la seule
partie qui connaît votre travail. Au-delà de `file_delai` secondes, le groupe de processus du
lanceur est arrêté et la tâche est notée « délai dépassé ».

## Fichiers

À côté du fichier de file `F` :

| Fichier | Contenu |
|---|---|
| `F.lancements` | une ligne par lancement (date locale + tâche) : sert au quota du jour |
| `F.fait` | tâches terminées, échouées ou ignorées, avec date et bilan |
| `F.lock`, `F.edit.lock` | verrous : l'un pour toute la durée d'une tâche, l'autre pour les modifications brèves de la file (on peut donc `ajouter` pendant qu'une tâche tourne) |

Les événements (`file-lancement`, `file-termine`, `file-remise-en-tete`, `file-abstention`,
`file-ignoree`, `file-ajout`, `file-retrait`) vont au journal commun, avec `projet=file`.

## Mise en route

1. Réglages : copier les lignes `file_*` de [`examples/claude-lot.conf`](../examples/claude-lot.conf)
   et renseigner `file_lanceur` (obligatoire).
2. Un essai sans risque : `claude-lot file ajouter ma_tache`, puis `claude-lot file tourner --a-blanc`.
3. Cron : [`examples/crontab-file.txt`](../examples/crontab-file.txt), une tentative toutes les deux heures.

Pourquoi toutes les deux heures et pas une fois par jour : un refus de quota est normal, la tentative
suivante prend le relais dès que la ligne régulière a rattrapé l'usage.

## Idées non fournies

- Transformer une boîte de notes (fichier de lignes brutes) en lignes de file par une session
  `claude -p` de tri, avec le même mécanisme de verrou et de garde.
- Un lot de nuit qui ajoute à la file de quoi tenir la semaine selon le quota restant.

Elles dépendent du contenu de chacun ; la file est faite pour s'y brancher via le lanceur.
