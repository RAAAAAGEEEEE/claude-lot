# Utilisation

## Trois modes

| Commande | Effet | Code |
|---|---|---|
| `claude-lot [options] -- <args de claude>` | vérifie le plafond, choisit le modèle, lance `claude` | celui de `claude`, ou 75 |
| `claude-lot --verifier [options]` | vérifie seulement | 0 ou 75 |
| `claude-lot --choisir [options]` | affiche `modèle effort (raison)`, ne mesure rien | 0 |

Options : `--projet NOM` (journal), `--sujet "..."`, `--sujet-fichier brief.md`, `--modele`,
`--effort low|medium|high|xhigh|max`, `--prioritaire`, `--conf fichier`.

Codes : 0 succès, 64 erreur d'usage (brief illisible, rien à lancer), 75 plafond atteint.

## Plafond

La sonde rend l'utilisation de la semaine et de la fenêtre de 5 h, avec leurs heures de fin.
Le lancement est refusé si l'une atteint son plafond (`cinq_heures`, `semaine`, ou `reserve` avec
`--prioritaire`). Une fenêtre dont l'heure de fin est passée compte pour 0 %. Si la sonde ne
répond pas, la dernière mesure sert tant que sa fenêtre de 5 h court ; sans aucune mesure,
le réglage `mesure_impossible` décide.

Le contrôle a lieu **au démarrage** seulement. Un lot long qui démarre à 84 % peut finir au-delà
du plafond : découpez les gros lots en tâches successives, chacune repassant par le lanceur.

## Choix du modèle

Ordre de priorité :

1. `--modele` (alias `haiku`, `sonnet`, `opus`, `fable` ou identifiant complet) et `--effort` ;
2. dans le brief, une ligne `modele: opus high` (ou `modèle :`, `model:`) et une ligne `effort: high` ;
3. un `--model` déjà présent dans les arguments de `claude` (le lanceur n'ajoute alors pas le sien) ;
4. la table, sur le sujet et le titre du brief, en minuscules et sans accents.

| Règle | Modèle | Effort | Pourquoi |
|---|---|---|---|
| architecture, logique centrale, sécurité, réseau (pas « réseau social »), authentification, refonte, refactor, contre-revue, revue de code, vérification factuelle | Opus | medium | une erreur de conception ou un fait faux coûte plus cher que l'écart de prix |
| extraction, documents, PDF, analyse de rapports ou de contrats, article, brève, publication, factuel | Sonnet | high | lecture longue ou texte publié : l'effort compte plus que le modèle |
| mesure, comptage, tri, classement, inventaire, gros volume, en masse, formatage | Haiku | low | travail simple et répétitif ; jamais si le sujet parle aussi de rédiger, d'écrire, de texte, de code ou de corriger |
| le reste | Sonnet | medium | exécution courante |

Les identifiants viennent du registre facultatif (`registre`, voir
[CONFIGURATION.md](CONFIGURATION.md)), sinon de la génération 5.5 / 5.1.

Exemples :

```text
$ claude-lot --choisir --sujet "Mesure du temps de chargement"
claude-haiku-5-5 low (gros volume simple ou mesure)
$ claude-lot --choisir --sujet "Extraction des prix des PDF"
claude-sonnet-5-5 high (extraction, analyse de documents ou texte publié factuel)
$ claude-lot --choisir --sujet "Contre-revue du paiement"
claude-opus-5-5 medium (architecture, logique centrale, sécurité, contre-revue ou vérification factuelle)
```

## Journal

Une ligne par lancement ou refus :

```text
2026-10-20T07:51:12+02:00 projet=jeu refus 5h=86%/85% semaine=21%/90% (sonde) sujet='relecture'
2026-10-20T07:51:18+02:00 projet=jeu lancement 5h=64%/85% semaine=21%/90% (sonde) modele=claude-opus-5-5 effort=medium (...) sujet='relecture'
```

`--verifier` n'écrit que les refus ; `--choisir` n'écrit rien.
