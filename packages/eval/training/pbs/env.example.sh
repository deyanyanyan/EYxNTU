# Site settings for NTU GaaS. Copy to pbs/env.sh (git-ignored) and check every value
# against the live account. Sourced by pbs/submit.sh on the login node and by every
# job script on the compute or data-mover node.
#
# Checked on 27 Oct 2026 (account dtan167):
#   project code   fs_ccds_tianwei.zhang (checkmember; expires 2026-11-15)
#   gpu_free       routes to gpu_free_high (1 GPU, <= 1 h, priority 100) and
#                  gpu_free_normal (<= 4 GPUs, <= 6 h); one running job per user each
#   gpu_datamover  no GPU, <= 4 CPUs, <= 120 h, two running jobs per user
#   storage        /home quota 932 GB, NFS, four rotating weekly snapshots only;
#                  /scratch and /projects_vol have no directory for this project
#   rule           do not run work on the login node (processes are terminated)

# --- scheduler -----------------------------------------------------------------
export EVALTRAIN_PROJECT="REPLACE_WITH_ASSIGNED_PROJECT_CODE"   # e.g. fs_ccds_tianwei.zhang
export EVALTRAIN_QUEUE="gpu_free"

# --- storage: persistent, shared by all nodes ------------------------------------
export EVALTRAIN_ROOT="REPLACE_WITH_PERSISTENT_PATH/evaltrain"   # e.g. $HOME/evaltrain
export HF_HOME="$EVALTRAIN_ROOT/hf"

# --- software: python module + pinned venv (pbs/setup.pbs creates it) ---------------
# The anaconda/2025 module prepends its Python 3.11 libraries to LD_LIBRARY_PATH,
# which can shadow the CUDA wheels' own libraries; the plain python module does not.
if command -v module >/dev/null 2>&1; then
  module purge
  module load python/3.12.13
fi
export EVALTRAIN_ENV="$EVALTRAIN_ROOT/envs/evaltrain"
if [ -f "$EVALTRAIN_ENV/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$EVALTRAIN_ENV/bin/activate"
elif [ -n "${PBS_JOBID:-}" ] && [ "${EVALTRAIN_SETUP:-0}" != 1 ]; then
  echo "environment $EVALTRAIN_ENV missing: submit pbs/setup.pbs first" >&2
  exit 1
fi

# --- runtime -------------------------------------------------------------------
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1
# PBS may list GPUs by UUID; vLLM and MS-SWIFT expect integer indices (site template fix).
if echo "${CUDA_VISIBLE_DEVICES:-}" | grep -q "GPU-"; then
  CUDA_VISIBLE_DEVICES=$(seq -s, 0 $(( $(echo "$CUDA_VISIBLE_DEVICES" | tr ',' '\n' | wc -l) - 1 )))
  export CUDA_VISIBLE_DEVICES
fi
# GPU jobs read only staged files; the data-mover setup job downloads them.
if [ -n "${PBS_JOBID:-}" ] && [ "${EVALTRAIN_SETUP:-0}" != 1 ]; then export HF_HUB_OFFLINE=1; fi
