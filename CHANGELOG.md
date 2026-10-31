# Changelog

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Versions selon [SemVer](https://semver.org/lang/fr/).

## [1.1.0] - 2026-11-01

### Ajouté
- `claude-lot file ajouter|lister|retirer|tourner` : file de tâches générique (`tache[:modele[:effort]]`),
  au plus `file_max_par_jour` lancements par jour, une tâche à la fois sous verrou, plafond commun et
  ligne régulière de la semaine vérifiés avant chaque lancement, tâche remise en tête quand le lanceur
  sort en code 75 (limite d'usage), lignes invalides rangées dans `.fait`, journal, code 75 à
  l'abstention. `tourner --a-blanc` décide sans rien lancer ni modifier la file. Ctrl-C et SIGTERM
  arrêtent le groupe de processus de la tâche et la remettent en tête.
- Réglages `file`, `file_max_par_jour`, `file_lanceur` (programme qui exécute une tâche), `file_garde`
  (contrôle externe facultatif), `file_delai`, `file_rythme`, `file_mesure_impossible`.
- `examples/lanceur-exemple.sh`, `examples/crontab-file.txt`, `docs/FILE.md`.

### Compatibilité
- Aucune option existante ne change. Seule différence : un argument littéral `file` donné à
  `claude-lot` **sans** `--` ouvre désormais la file au lieu d'être transmis à `claude` ; la forme
  documentée (`claude-lot ... -- <args de claude>`) n'est pas touchée. D'où une version mineure.

### Corrigé
- Commentaire de `claude_lot.py` qui nommait un projet privé (sans effet sur le comportement).

## [1.0.0] - 2026-10-20

### Ajouté
- `scripts/claude_lot.py` : plafond commun (fenêtre de 5 h et semaine, réserve pour
  `--prioritaire`), refus en code 75 avec journal, reprise de la dernière mesure si la sonde se
  tait, choix du modèle et de l'effort par table de mots-clés avec champ `modele:` explicite,
  lancement de `claude` par `exec`.
- `scripts/sonde-quota.sh` : mesure de l'utilisation réelle de l'abonnement, cache de 15 minutes.
- `SKILL.md` : cadrage, inventaire des lanceurs, installation, branchement avec sauvegardes, preuve.
- Documentation (`docs/`), exemple de réglages, tests sans réseau.
