# Changelog

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Versions selon [SemVer](https://semver.org/lang/fr/).

## [1.0.0] - 2026-10-20

### Ajouté
- `scripts/claude_lot.py` : plafond commun (fenêtre de 5 h et semaine, réserve pour
  `--prioritaire`), refus en code 75 avec journal, reprise de la dernière mesure si la sonde se
  tait, choix du modèle et de l'effort par table de mots-clés avec champ `modele:` explicite,
  lancement de `claude` par `exec`.
- `scripts/sonde-quota.sh` : mesure de l'utilisation réelle de l'abonnement, cache de 15 minutes.
- `SKILL.md` : cadrage, inventaire des lanceurs, installation, branchement avec sauvegardes, preuve.
- Documentation (`docs/`), exemple de réglages, tests sans réseau.
