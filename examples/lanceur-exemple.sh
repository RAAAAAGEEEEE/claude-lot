#!/bin/bash
# Lanceur d'exemple pour `claude-lot file tourner` (réglage file_lanceur).
#
# Appelé par la file avec : lanceur-exemple.sh <tache> <modele ou auto> <effort ou vide>
# Il lit le brief $CLAUDE_LOT_BRIEFS/<tache>.md, lance `claude -p` à travers claude-lot (qui
# contrôle encore le plafond, c'est voulu : une seconde barrière, au cas où le quota aurait bougé
# depuis la décision de la file) et traduit le résultat en code de sortie :
#   0   tâche faite
#   75  arrêt sur limite d'usage (ou plafond atteint) : la file remet la tâche en tête
#   64  tâche inconnue ou nom invalide : échec définitif, pas de nouvel essai
#   autre : échec de la tâche, la file la range dans le fichier « .fait » sans la rejouer
#
# Variables : CLAUDE_LOT_BRIEFS (défaut ~/claude-lot-briefs), CLAUDE_LOT_SORTIES (défaut
# ~/.local/state/claude-lot/sorties), CLAUDE_LOT_BIN (défaut claude-lot).
set -u
TACHE="${1:-}"; MODELE="${2:-auto}"; EFFORT="${3:-}"
BRIEFS="${CLAUDE_LOT_BRIEFS:-$HOME/claude-lot-briefs}"
SORTIES="${CLAUDE_LOT_SORTIES:-$HOME/.local/state/claude-lot/sorties}"
LOT="${CLAUDE_LOT_BIN:-claude-lot}"

# La file a déjà validé le nom ; on le revérifie, ce script peut aussi être lancé à la main.
[[ "$TACHE" =~ ^[a-z0-9_]+$ ]] || { echo "nom de tâche invalide" >&2; exit 64; }
BRIEF="$BRIEFS/$TACHE.md"
[ -f "$BRIEF" ] || { echo "brief absent : $BRIEF" >&2; exit 64; }
mkdir -p "$SORTIES"
SORTIE="$SORTIES/$TACHE.json"

# La file transmet ce que dit la ligne : « auto » laisse claude-lot choisir (champ « modele: » du brief,
# puis table de mots-clés) ; un alias ou un identifiant est imposé. Le choix de la table d'après le nom
# de la tâche est aussi dans CLAUDE_LOT_MODELE_CHOISI et CLAUDE_LOT_EFFORT_CHOISI.
OPTIONS=(--projet file --sujet-fichier "$BRIEF")
[ "$MODELE" != auto ] && OPTIONS+=(--modele "$MODELE")
[ -n "$EFFORT" ] && OPTIONS+=(--effort "$EFFORT")

"$LOT" "${OPTIONS[@]}" -- -p "$(cat "$BRIEF")" --output-format json > "$SORTIE"
CODE=$?
[ "$CODE" -eq 75 ] && exit 75     # plafond atteint juste avant le lancement
# Limite d'usage atteinte en cours de route : Claude répond en erreur et le dit dans le résultat.
# Le texte exact est celui de Claude Code ; à vérifier sur votre version et à adapter si besoin.
# Une autre erreur qui contient le mot « limit » (contexte trop long...) n'est PAS une limite d'usage.
if grep -q '"is_error": *true' "$SORTIE" 2>/dev/null \
   && grep -qiE '(usage|rate|5-hour|weekly|session) limit|limit reached' "$SORTIE"; then exit 75; fi
exit "$CODE"
