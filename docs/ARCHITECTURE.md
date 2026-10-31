# Architecture

Un seul fichier, `scripts/claude_lot.py`, sans dépendance :

1. **Réglages** (`lire_reglages`) : valeurs par défaut, puis le fichier de configuration.
2. **Mesure** (`mesurer`) : lance la sonde, garde la dernière mesure valable dans `etat`, la
   réutilise si la sonde se tait et que sa fenêtre de 5 h court encore.
3. **Décision** (`verifier`) : remet à 0 une fenêtre terminée, compare aux plafonds, journalise
   le refus et rend le code 75.
4. **Choix du modèle** (`choisir`) : option explicite, puis champ du brief, puis table de règles
   ordonnée (Opus, Sonnet high, Haiku, défaut Sonnet medium) sur un texte normalisé.
5. **Lancement** : `os.execvp` remplace le processus par `claude` avec `--model` et `--effort`
   ajoutés devant les arguments. Le code de sortie, la sortie standard et les signaux sont donc
   ceux de `claude`, ce qui garde intacts les scripts qui lisent `--output-format json`.

6. **File de tâches** (`file_tourner` et les fonctions voisines, même fichier) : lit une file texte,
   prend deux verrous `flock` (l'un pour la durée d'une tâche, l'autre pour les modifications
   brèves), réutilise `verifier` (avec `rythme` et `mesure_impossible` propres à la file) et `choisir`,
   retire la ligne avant de lancer le « lanceur » configuré, puis range ou remet en tête selon son
   code de sortie. Détail : [FILE.md](FILE.md).

Choix assumés :

- **Contrôle au démarrage, jamais d'arrêt en cours** : couper un lot au milieu laisse du travail à
  moitié fait (commit non poussé, texte rédigé mais non relu). Le découpage en tâches courtes est
  le bon levier.
- **Sonde externe** : la façon de mesurer dépend du compte et peut changer ; le lanceur ne connaît
  qu'un format de ligne.
- **File : retrait avant lancement.** Un plantage ou un redémarrage en cours de tâche ne la
  relance jamais deux fois ; en contrepartie une tâche tuée n'est pas reprise (voir
  [LIMITATIONS.md](LIMITATIONS.md)).
- **File : le lanceur est un programme, pas du code.** Le dépôt ne connaît aucun projet ; un nom de
  tâche ne devient jamais une commande, il est passé en argument à un programme choisi par l'administrateur.
- **Un seul fichier** : la file vit dans `claude_lot.py` pour que l'installation reste une copie de fichier.
- **Titre du brief seulement** pour la table : mesuré sur de vrais briefs, le corps contient des
  consignes générales qui faisaient tout partir sur Opus.
