#!/bin/bash
# Installe claude-lot depuis le DERNIER COMMIT du dépôt (jamais depuis la copie de travail).
#
# Refuse d'installer si la copie installée diffère du commit installé la fois précédente :
# une modification faite directement dans la copie installée serait sinon écrasée en silence
# (08/11/2026 : réglages de présence, turbo et ligne_horaire vivaient seulement dans la copie
# installée, la file 1.1 seulement dans le dépôt). La corriger d'abord dans le dépôt.
#
# Usage : scripts/installer.sh [--adopter]
#   --adopter : première installation suivie, quand aucun commit installé n'est connu ; à n'utiliser
#               qu'après avoir vérifié que la copie installée est entièrement fusionnée dans le dépôt.
# Variables : CLAUDE_LOT_CIBLE (défaut /usr/local/bin/claude-lot), CLAUDE_LOT_INSTALLE (état,
# défaut /var/lib/claude-lot/installe.txt), CLAUDE_LOT_SANS_TESTS=1 (essais de ce script seulement).
# Étapes : contrôle de la copie installée, tests du dépôt, sauvegarde horodatée ISO de la copie
# installée, installation atomique, état « <commit> <sha256> <date> ».
set -euo pipefail
DEPOT="$(cd "$(dirname "$0")/.." && pwd)"
CIBLE="${CLAUDE_LOT_CIBLE:-/usr/local/bin/claude-lot}"
ETAT="${CLAUDE_LOT_INSTALLE:-/var/lib/claude-lot/installe.txt}"
ADOPTER=0
[ "${1:-}" = "--adopter" ] && ADOPTER=1
refuser() { echo "installer.sh : REFUS, $*" >&2; exit 1; }
cd "$DEPOT"

git diff --quiet HEAD -- scripts/claude_lot.py \
  || refuser "scripts/claude_lot.py a des modifications non commitées (on installe le dernier commit)"
COMMIT="$(git rev-parse HEAD)"

if [ -f "$CIBLE" ]; then
  if [ -f "$ETAT" ]; then
    ANCIEN="$(awk '{print $1}' "$ETAT")"
    git cat-file -e "$ANCIEN:scripts/claude_lot.py" 2>/dev/null \
      || refuser "commit installé $ANCIEN introuvable dans le dépôt"
    git show "$ANCIEN:scripts/claude_lot.py" | cmp -s - "$CIBLE" \
      || refuser "$CIBLE diffère du commit installé ${ANCIEN:0:7} : modification hors dépôt. Voir :
  git -C $DEPOT show ${ANCIEN:0:7}:scripts/claude_lot.py | diff - $CIBLE
puis la reporter dans le dépôt, commiter, relancer."
  elif [ "$ADOPTER" != 1 ]; then
    refuser "aucun commit installé connu ($ETAT absent). Vérifier que $CIBLE est entièrement fusionnée
dans le dépôt, puis relancer avec --adopter."
  fi
fi

if [ "${CLAUDE_LOT_SANS_TESTS:-0}" != 1 ]; then
  python3 -m unittest discover -s tests >/dev/null 2>&1 || refuser "tests du dépôt en échec (python3 -m unittest discover -s tests)"
fi

if [ -f "$CIBLE" ]; then
  SAUVE="$CIBLE.bak-$(date -u +%Y%m%dT%H%M%SZ)"
  cp -p "$CIBLE" "$SAUVE"
  echo "sauvegarde : $SAUVE"
fi
git show "HEAD:scripts/claude_lot.py" > "$CIBLE.tmp"
chmod 755 "$CIBLE.tmp"
python3 -c "import sys; compile(open(sys.argv[1], encoding='utf-8').read(), sys.argv[1], 'exec')" "$CIBLE.tmp" \
  || { rm -f "$CIBLE.tmp"; refuser "le fichier du commit ne compile pas"; }
mv "$CIBLE.tmp" "$CIBLE"
mkdir -p "$(dirname "$ETAT")"
echo "$COMMIT $(sha256sum "$CIBLE" | cut -d' ' -f1) $(date -Iseconds)" > "$ETAT"
echo "installé : $("$CIBLE" --version) depuis ${COMMIT:0:7}"
