# Dépannage

| Constat | Cause probable | Que faire |
|---|---|---|
| `mesure du quota impossible` dans le journal | sonde absente, `jq` manquant, `claude` non connecté, délai dépassé | lancer la sonde à la main : elle doit afficher une ligne de quatre nombres |
| Tout est refusé alors que le quota est bas | dernière mesure ancienne lue faute de sonde, ou plafond trop bas | `claude-lot --verifier` affiche l'origine (`sonde` ou `dernière mesure`) ; vérifier `cinq_heures` et `semaine` |
| Rien n'est jamais refusé | `sonde` vide dans les réglages et `mesure_impossible=lancer` | renseigner `sonde` avec un chemin absolu |
| Marche à la main, pas en cron | `PATH` réduit de cron, `~` non résolu | chemins absolus dans la crontab et dans `/etc/claude-lot.conf` |
| Mauvais modèle choisi | sujet trop vague, ou mot-clé du corps attendu | `claude-lot --choisir --sujet ... --sujet-fichier ...` ; ajouter `modele: ...` au brief |
| `rien à lancer` (code 64) | oubli du `--` avant les arguments de `claude` | `claude-lot --projet P -- -p "..."` |
