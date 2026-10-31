# Dépannage

| Constat | Cause probable | Que faire |
|---|---|---|
| `mesure du quota impossible` dans le journal | sonde absente, `jq` manquant, `claude` non connecté, délai dépassé | lancer la sonde à la main : elle doit afficher une ligne de quatre nombres |
| Tout est refusé alors que le quota est bas | dernière mesure ancienne lue faute de sonde, ou plafond trop bas | `claude-lot --verifier` affiche l'origine (`sonde` ou `dernière mesure`) ; vérifier `cinq_heures` et `semaine` |
| Rien n'est jamais refusé | `sonde` vide dans les réglages et `mesure_impossible=lancer` | renseigner `sonde` avec un chemin absolu |
| Marche à la main, pas en cron | `PATH` réduit de cron, `~` non résolu | chemins absolus dans la crontab et dans `/etc/claude-lot.conf` |
| Mauvais modèle choisi | sujet trop vague, ou mot-clé du corps attendu | `claude-lot --choisir --sujet ... --sujet-fichier ...` ; ajouter `modele: ...` au brief |
| `claude-lot file tourner` sort en 75 sans rien lancer | quota du jour atteint, plafond ou ligne régulière dépassés, `file_garde` qui refuse, ou une autre exécution en cours | lire le message sur la sortie d'erreur et le journal (`file-abstention`) ; `claude-lot file tourner --a-blanc` redonne la raison |
| `claude-lot file tourner` : code 64 | `file_lanceur` vide, introuvable, non exécutable ou impossible à démarrer, ou réglage numérique invalide | corriger la configuration (`file_lanceur` en chemin absolu) |
| Une tâche a disparu de la file sans résultat | elle a été tuée en cours de route (la ligne est retirée avant le lancement) | chercher son nom dans `.lancements` et `.fait`, la remettre avec `file ajouter` |
| Une ligne a disparu de la file | elle était invalide (nom, modèle ou effort) | `.fait` en donne la raison ; `file lister` signale les lignes invalides |
| `rien à lancer` (code 64) | oubli du `--` avant les arguments de `claude` | `claude-lot --projet P -- -p "..."` |
