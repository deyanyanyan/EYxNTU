#!/usr/bin/env bash
# Fails if any denylisted term (identifiers, secrets, or personal data from the
# reference project) appears anywhere in the tree. Runs as a pre-commit hook.
set -euo pipefail
cd "$(dirname "$0")/.."
git rev-parse --show-toplevel >/dev/null

# whole-word, case-insensitive
WORDS=(cpf ccu glide soar csa medisave mandis wenjieb2 cpfsimulator schemes-img)
# substring, case-insensitive
SUBSTR=("central provident" ccutrainingsimulator 471112806622 "rds.amazonaws" "ap-southeast-1" "cpf.gov.sg" "sk-proj-" AKIA)

FILES=()
while IFS= read -r -d '' file; do
  case "$file" in *scrub-check*|*.docx|*.pdf|*.png|*.jpg|*.woff2) continue ;; esac
  [ -f "$file" ] && FILES+=("$file")
done < <(git ls-files --cached --others --exclude-standard -z)
fail=0
for w in "${WORDS[@]}"; do
  hits=$(grep -Iniw -- "$w" "${FILES[@]}" 2>/dev/null || true)
  if [ -n "$hits" ]; then echo "DENYLIST HIT (word): $w"; echo "$hits"; fail=1; fi
done
for s in "${SUBSTR[@]}"; do
  hits=$(grep -IniF -- "$s" "${FILES[@]}" 2>/dev/null || true)
  if [ -n "$hits" ]; then echo "DENYLIST HIT (substring): $s"; echo "$hits"; fail=1; fi
done
[ $fail -eq 0 ] && echo "scrub-check: clean"
exit $fail
