#!/bin/bash
# Queue the whole 9B milestone as one dependency chain, so it runs back to back without
# anyone watching (the project may run one GPU job at a time; every job here is <= 1 h,
# which keeps it in the priority queue gpu_free_high):
#
#   bootstrap ─┬─> 9B prompted baselines (base, base-thinking)
#              └─> train: stop after 20 steps ─> train: resume ─> resume ─> resume ─> adapter eval
#
# Run from packages/eval/training on the login node. Pass an existing bootstrap job id
# (or "none" once the environment and the 9B model are staged) instead of submitting one:
#   bash pbs/pilot_chain.sh            # submits a bootstrap job first
#   bash pbs/pilot_chain.sh none
set -euo pipefail
cd "$(dirname "$0")/.."
config=configs/pilot_9b.yaml

boot=${1:-}
if [ -z "$boot" ]; then
  boot=$(bash pbs/submit.sh bootstrap)
  echo "bootstrap -> $boot" >&2
fi
after() { [ "$1" = none ] && echo "" || echo "afterok:$1"; }

DEPEND=$(after "$boot") bash pbs/submit.sh eval "$config" base+base-thinking > /dev/null
t1=$(DEPEND=$(after "$boot") STOP_AFTER_STEPS=20 WALLTIME=01:00:00 bash pbs/submit.sh train "$config")
last=$(DEPEND=afterok:$t1 WALLTIME=01:00:00 bash pbs/submit.sh train "$config" 3 | tail -1)
DEPEND=afterok:$last bash pbs/submit.sh eval "$config" adapter > /dev/null
qstat -u "$USER"
