# Confidentialité et sécurité

- `claude-lot` ne lit aucun jeton et n'en écrit aucun. L'authentification reste celle de
  `claude` ; la sonde fournie appelle `claude` sans afficher sa configuration.
- Le journal contient l'heure, le nom de projet donné, les pourcentages, le modèle et les
  60 premiers caractères du sujet. N'y mettez pas de donnée personnelle dans `--sujet`.
- Aucun appel réseau propre : seule la sonde (un court appel Haiku au plus toutes les
  15 minutes) et `claude` lui-même parlent au service.
- Aucune commande n'est passée à un shell : la sonde et `claude` sont lancés avec une liste
  d'arguments (`shlex.split`, puis `exec`), sans interprétation.
- Signaler une faille : voir [SECURITY.md](../SECURITY.md).
