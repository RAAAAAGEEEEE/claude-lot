# Limites

- **Le plafond n'est vérifié qu'au démarrage.** Plusieurs lots lancés à la même minute sous le
  plafond peuvent ensemble le dépasser ; un lot long aussi.
- **La sonde fournie repose sur un événement non documenté** de Claude Code (`rate_limit_event`
  en `stream-json`), observé en octobre 2026 avec Claude Code 2.1 sur un abonnement Max. S'il
  disparaît, la sonde sort en code 1 et le réglage `mesure_impossible` s'applique.
- **Le cache de 15 minutes** de la sonde retarde un refus d'autant au plus.
- **Le choix par mots-clés est une convention**, pas une mesure de qualité : un sujet mal nommé
  prend le mauvais modèle. Le champ `modele:` est fait pour ces cas.
- **Mots-clés en français et en anglais** seulement.
- **La file ne reprend pas une tâche tuée en cours de route** (redémarrage de la machine, `kill`) :
  la ligne a été retirée avant le lancement. Une tâche qui apparaît dans `.lancements` sans ligne
  correspondante dans `.fait`, et absente de la file, a été interrompue ; la remettre avec
  `claude-lot file ajouter`. (Un Ctrl-C ou un SIGTERM sur `claude-lot file tourner` est géré : la tâche
  est arrêtée et remise en tête. Un SIGKILL, une coupure de courant ou un redémarrage ne le sont pas.)
- **Le quota du jour compte les lancements, pas leur coût** : une tâche arrêtée par la limite d'usage
  puis remise en tête compte pour un lancement à chaque essai.
- **Une tâche par exécution de `tourner`** : la cadence vient de la crontab, pas de la file.
- **Pas de priorités, de dépendances ni de reprises automatiques d'un échec** dans la file : l'ordre est celui du fichier.
- **La file suppose un seul fichier local** (verrou `flock`) : pas de partage par un disque réseau. Linux et macOS.
- Les sessions interactives et les autres machines du même compte consomment le même quota sans
  passer par le lanceur : c'est voulu (la réserve leur est destinée), mais elles peuvent faire
  refuser des lots.
