#!/usr/bin/env bash
# Fails if any denylisted term (identifiers, secrets, or personal data from the
# reference project) appears anywhere in the tree. Runs as a pre-commit hook.
set -uo pipefail
cd "$(dirname "$0")/.."

# whole-word, case-insensitive
WORDS=(cpf ccu glide soar csa medisave mandis wenjieb2 cpfsimulator schemes-img)
# substring, case-insensitive
SUBSTR=("central provident" ccutrainingsimulator 471112806622 "rds.amazonaws" "ap-southeast-1" "cpf.gov.sg" "sk-proj-" AKIA)

EX=(--exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=.venv --exclude-dir=data --exclude=scrub-check.sh --exclude=scrub-check.ps1)
fail=0
for w in "${WORDS[@]}"; do
  hits=$(grep -rIniw "${EX[@]}" -- "$w" . 2>/dev/null || true)
  if [ -n "$hits" ]; then echo "DENYLIST HIT (word): $w"; echo "$hits"; fail=1; fi
done
for s in "${SUBSTR[@]}"; do
  hits=$(grep -rIni "${EX[@]}" -- "$s" . 2>/dev/null || true)
  if [ -n "$hits" ]; then echo "DENYLIST HIT (substring): $s"; echo "$hits"; fail=1; fi
done
[ $fail -eq 0 ] && echo "scrub-check: clean"
exit $fail
