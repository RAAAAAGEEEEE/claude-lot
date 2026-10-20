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

Choix assumés :

- **Contrôle au démarrage, jamais d'arrêt en cours** : couper un lot au milieu laisse du travail à
  moitié fait (commit non poussé, texte rédigé mais non relu). Le découpage en tâches courtes est
  le bon levier.
- **Sonde externe** : la façon de mesurer dépend du compte et peut changer ; le lanceur ne connaît
  qu'un format de ligne.
- **Titre du brief seulement** pour la table : mesuré sur de vrais briefs, le corps contient des
  consignes générales qui faisaient tout partir sur Opus.
