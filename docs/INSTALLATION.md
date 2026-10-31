# Installation

## Prérequis

- Claude Code 2.1 ou plus récent, connecté à un abonnement Claude (`claude` dans le `PATH`).
- Python 3.9 ou plus récent (bibliothèque standard seulement).
- Pour la sonde fournie : bash et `jq`.

## Comme skill

```bash
git clone https://github.com/RAAAAAGEEEEE/claude-lot ~/.claude/skills/claude-lot
```

Puis, dans Claude Code : « mets un plafond commun sur mes scripts claude -p » ou `/claude-lot`.

## Le lanceur seul

Pour un utilisateur :

```bash
install -m 755 scripts/claude_lot.py ~/.local/bin/claude-lot
cp examples/claude-lot.conf ~/.config/claude-lot.conf
echo 'export CLAUDE_LOT_CONF=~/.config/claude-lot.conf' >> ~/.profile
```

Pour toute la machine (tous les projets d'un serveur) :

```bash
sudo install -m 755 scripts/claude_lot.py /usr/local/bin/claude-lot
sudo cp examples/claude-lot.conf /etc/claude-lot.conf     # emplacement lu par défaut
```

Dans `/etc/claude-lot.conf`, mettez un chemin absolu pour `sonde`, `journal` et `etat` : cron ne
part pas toujours du même dossier personnel.

## Pour la file de tâches

Aucune installation de plus : `claude-lot file ...` est dans le même fichier. Renseigner
`file_lanceur` et programmer la crontab : [FILE.md](FILE.md).

## Vérifier

```bash
claude-lot --version
claude-lot --verifier ; echo "code $?"     # 0 : autorisé, 75 : plafond atteint
```

Le premier appel de la sonde coûte un court appel Haiku ; les suivants lisent le cache.

## Désinstaller

Supprimer `claude-lot`, le fichier de réglages et `~/.local/state/claude-lot/`, puis rendre aux
lanceurs leur commande d'origine (les sauvegardes horodatées faites au branchement).
