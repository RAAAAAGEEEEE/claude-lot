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
- Les sessions interactives et les autres machines du même compte consomment le même quota sans
  passer par le lanceur : c'est voulu (la réserve leur est destinée), mais elles peuvent faire
  refuser des lots.
