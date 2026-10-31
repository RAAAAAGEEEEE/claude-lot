# Confidentialité et sécurité

- `claude-lot` ne lit aucun jeton et n'en écrit aucun. L'authentification reste celle de
  `claude` ; la sonde fournie appelle `claude` sans afficher sa configuration.
- Le journal contient l'heure, le nom de projet donné, les pourcentages, le modèle et les
  60 premiers caractères du sujet. N'y mettez pas de donnée personnelle dans `--sujet`.
- Aucun appel réseau propre : seule la sonde (un court appel Haiku au plus toutes les
  15 minutes) et `claude` lui-même parlent au service.
- Aucune commande n'est passée à un shell : la sonde et `claude` sont lancés avec une liste
  d'arguments (`shlex.split`, puis `exec`), sans interprétation.
- File de tâches : un nom de tâche (`^[a-z0-9_]+$`), un modèle (alias ou `claude-...`) et un effort
  connus sont les seules choses qu'une ligne de file peut contenir ; elles sont passées en arguments
  au lanceur, jamais à un shell. Le lanceur est choisi par l'administrateur dans la configuration :
  protégez le fichier de configuration et le fichier de file en écriture. Les fichiers annexes
  (`.lancements`, `.fait`) contiennent seulement noms de tâches et dates.
- Signaler une faille : voir [SECURITY.md](../SECURITY.md).
