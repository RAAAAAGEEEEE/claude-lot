#!/bin/bash
# Sonde de quota pour claude-lot : affiche une ligne
#   « <% semaine> <% fenêtre de 5 h | inconnu> <fin semaine, epoch> <fin fenêtre de 5 h, epoch> »
# ou sort en code 1 sans rien afficher si la mesure est impossible. Fenêtre de 5 h absente de
# l'événement (constaté depuis le 06/11/2026 : seule seven_day reste) : « inconnu », jamais 0, et
# fin de 5 h = fin de semaine. Un refus d'usage sur l'appel de la sonde est noté par
# `claude-lot refus noter` (si claude-lot 1.2 ou plus est dans le PATH).
#
# Méthode : un appel Haiku sans outils en `--output-format stream-json --verbose`. Claude Code
# y émet un événement `rate_limit_event` qui porte l'utilisation des fenêtres de l'abonnement
# (observé avec Claude Code 2.1 en octobre 2026 ; champ non documenté, il peut changer). Le
# résultat est gardé en cache CLAUDE_LOT_SONDE_CACHE secondes (900 par défaut) : un appel par
# quart d'heure au plus, quel que soit le nombre de lots lancés.
#
# Prérequis : claude (connecté à un abonnement), jq. N'affiche aucun jeton.
set -uo pipefail
CACHE="${CLAUDE_LOT_SONDE_FICHIER:-${XDG_STATE_HOME:-$HOME/.local/state}/claude-lot/sonde.txt}"
DUREE="${CLAUDE_LOT_SONDE_CACHE:-900}"
MODELE="${CLAUDE_LOT_SONDE_MODELE:-claude-haiku-5-5}"
valide() { [[ "$1" =~ ^[0-9]+\ ([0-9]+|inconnu)\ [0-9]{10}\ [0-9]{10}$ ]]; }

if [ -f "$CACHE" ] && [ $(( $(date +%s) - $(stat -c %Y "$CACHE" 2>/dev/null || stat -f %m "$CACHE") )) -lt "$DUREE" ]; then
  ligne="$(cat "$CACHE")"
  valide "$ligne" && { echo "$ligne"; exit 0; }
fi

# timeout (GNU) ou gtimeout (coreutils sous macOS) ; sans l'un ni l'autre, pas de délai.
DELAI="$(command -v timeout || command -v gtimeout || true)"
FLUX="$(mktemp)"; trap 'rm -f "$FLUX"' EXIT
(cd "${TMPDIR:-/tmp}" && CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 \
  ${DELAI:+$DELAI 90} claude -p "Réponds OK." --model "$MODELE" --tools "" --strict-mcp-config \
    --output-format stream-json --verbose 2>/dev/null > "$FLUX")
CODE=$?
if [[ "$(claude-lot --version 2>/dev/null)" =~ ^claude-lot\ (1\.([2-9]|[1-9][0-9])|[2-9])\. ]]; then
  claude-lot refus noter --fichier "$FLUX" --code "$CODE" --source sonde >/dev/null 2>&1
fi
ligne="$(jq -R -r 'fromjson? | select(.type == "rate_limit_event") | .rate_limit_info.unifiedWindows
      | select(.seven_day)
      | "\((.seven_day.utilization * 1000 | round) / 10 | floor) \(if .five_hour then ((.five_hour.utilization * 1000 | round) / 10 | floor | tostring) else "inconnu" end) \(.seven_day.resetsAt) \(.five_hour.resetsAt // .seven_day.resetsAt)"' \
      "$FLUX" 2>/dev/null | tail -1)"
valide "$ligne" || exit 1
mkdir -p "$(dirname "$CACHE")"
echo "$ligne" > "$CACHE.tmp" && mv "$CACHE.tmp" "$CACHE"
echo "$ligne"
