#!/bin/bash
# Submit evaltrain jobs to PBS from packages/eval/training on the login node.
#
#   bash pbs/submit.sh bootstrap                          # first GPU job: venv, models, smoke test (<= 1 h)
#   bash pbs/submit.sh setup                              # same staging via gpu_datamover, when that queue works
#   bash pbs/submit.sh train configs/pilot_9b.yaml        # one training job (6 h)
#   bash pbs/submit.sh train configs/pilot_9b.yaml 3      # three jobs chained with afterok
#   STOP_AFTER_STEPS=20 WALLTIME=01:00:00 bash pbs/submit.sh train configs/pilot_9b.yaml   # stop/resume test
#   bash pbs/submit.sh eval  configs/pilot_9b.yaml base+base-thinking   # several arms in one job (1 h)
#   SPLIT=test FINAL=1 bash pbs/submit.sh eval configs/pilot_9b.yaml adapter   # once, after selection on dev
#   DEPEND=afterok:12345.gaas bash pbs/submit.sh ...      # start only after another job succeeded
#
# Job ids go to stdout, one per line; descriptions go to stderr. WALLTIME and MEM override
# the defaults. gpu_free routes a 1-GPU job of at most 1 h to gpu_free_high (priority) and
# longer ones to gpu_free_normal (at most 6 h); the project may run one GPU at a time.
# Chained training jobs resume from the latest complete checkpoint: a job that stops for
# walltime exits 0, so the next one starts; a crash exits non-zero and PBS deletes the rest.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source pbs/env.sh >/dev/null 2>&1

kind=${1:?usage: bash pbs/submit.sh bootstrap | setup | train CONFIG [N] | eval CONFIG [ARM[+ARM...]]}
for var in EVALTRAIN_PROJECT EVALTRAIN_ROOT; do
  case "${!var}" in REPLACE_WITH*|"") echo "set $var in pbs/env.sh before submitting" >&2; exit 2 ;; esac
done
mkdir -p "$EVALTRAIN_ROOT/logs"

seconds() { IFS=: read -r h m s <<<"$1"; echo $((10#$h * 3600 + 10#$m * 60 + 10#$s)); }
dep=()
[ -n "${DEPEND:-}" ] && dep=(-W "depend=$DEPEND")
logs=(-o "$EVALTRAIN_ROOT/logs" -j oe)

case "$kind" in
  setup)
    qsub -P "$EVALTRAIN_PROJECT" -q gpu_datamover "${logs[@]}" "${dep[@]}" -v "STEP=${STEP:-all}" pbs/setup.pbs
    exit 0 ;;
  bootstrap)
    walltime=${WALLTIME:-01:00:00}
    qsub -P "$EVALTRAIN_PROJECT" -q "${EVALTRAIN_QUEUE:-gpu_free}" "${logs[@]}" "${dep[@]}" -l "walltime=$walltime" \
      -v "WALLTIME_S=$(seconds "$walltime")" pbs/bootstrap.pbs
    exit 0 ;;
  train) walltime=${WALLTIME:-06:00:00} ;;
  eval) walltime=${WALLTIME:-01:00:00} ;;
  *) echo "unknown job kind: $kind" >&2; exit 2 ;;
esac

config=${2:?config path required}
[ -f "$config" ] || { echo "no such config: $config" >&2; exit 2; }
common=(-P "$EVALTRAIN_PROJECT" -q "${EVALTRAIN_QUEUE:-gpu_free}" "${logs[@]}"
        -l "walltime=$walltime" -l "select=1:ncpus=12:ngpus=1:mem=${MEM:-128gb}")
vars="CONFIG=$config,WALLTIME_S=$(seconds "$walltime")"

case "$kind" in
  train)
    chain=${3:-1}
    for _ in $(seq 1 "$chain"); do
      id=$(qsub "${common[@]}" "${dep[@]}" -v "$vars${STOP_AFTER_STEPS:+,STOP_AFTER_STEPS=$STOP_AFTER_STEPS}" pbs/train.pbs)
      echo "train $config -> $id${dep:+ (${dep[1]})}" >&2
      echo "$id"
      dep=(-W "depend=afterok:$id")
    done
    ;;
  eval)
    arm=${3:-base}
    id=$(qsub "${common[@]}" "${dep[@]}" -v "$vars,ARM=$arm,SPLIT=${SPLIT:-dev}${FINAL:+,FINAL=1}" pbs/eval.pbs)
    echo "eval $config $arm -> $id${dep:+ (${dep[1]})}" >&2
    echo "$id"
    ;;
esac
