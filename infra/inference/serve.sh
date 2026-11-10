#!/bin/bash
# Start vLLM for the gpu profile: one base model plus optional custom LoRA adapters,
# all behind one OpenAI-compatible endpoint. Compose passes the .env values in as
# SERVE_* (vLLM itself reads VLLM_* variables, so the names are kept apart):
#
#   SERVE_MODEL          base model: a hub id resolved in HF_HOME, or a directory under /data/models
#   SERVE_BASE_ID        hub id of the base when SERVE_MODEL is a directory (for the adapter check)
#   SERVE_REVISION       pinned hub revision of the base
#   SERVE_LORA_MODULES   space-separated name=dir pairs; dirs are relative to /data/models/adapters
#   SERVE_MAX_LORAS, SERVE_MAX_LORA_RANK, SERVE_MAX_MODEL_LEN, SERVE_GPU_MEMORY_UTILIZATION
#   SERVE_EXTRA_ARGS     appended verbatim
#
# Each adapter is requested by its name as the `model` of a chat request. Its directory
# must hold serving.json naming the base model and revision it was trained on: vLLM will
# happily apply an adapter to the wrong base and answer with fluent nonsense, so this
# script refuses to start instead.
set -euo pipefail
: "${SERVE_MODEL:?set VLLM_MODEL in .env}"

args=("$SERVE_MODEL"
  --host 0.0.0.0 --port 8000
  --served-model-name "$SERVE_MODEL" lms-base
  --max-model-len "${SERVE_MAX_MODEL_LEN:-32768}"
  --gpu-memory-utilization "${SERVE_GPU_MEMORY_UTILIZATION:-0.90}"
  --enable-prefix-caching)
if [ -n "${SERVE_REVISION:-}" ]; then
  args+=(--revision "$SERVE_REVISION" --tokenizer-revision "$SERVE_REVISION")
fi

if [ -n "${SERVE_LORA_MODULES:-}" ]; then
  modules=()
  for pair in $SERVE_LORA_MODULES; do
    name=${pair%%=*}
    dir=${pair#*=}
    if [ "$name" = "$pair" ] || [ -z "$name" ] || [ -z "$dir" ]; then
      echo "VLLM_LORA_MODULES entry '$pair' is not name=dir" >&2
      exit 2
    fi
    [[ "$dir" = /* ]] || dir="/data/models/adapters/$dir"
    python3 - "$name" "$dir" "${SERVE_BASE_ID:-$SERVE_MODEL}" "${SERVE_REVISION:-}" <<'PY'
import json
import sys
from pathlib import Path

name, folder, base, revision = sys.argv[1:]
path = Path(folder)
for required in ("adapter_config.json", "adapter_model.safetensors", "serving.json"):
    if not (path / required).is_file():
        sys.exit(f"adapter {name}: {path / required} is missing")
weights = path / "adapter_model.safetensors"
if weights.stat().st_size < 1024 and weights.read_bytes().startswith(b"version https://git-lfs.github.com/spec/"):
    sys.exit(f"adapter {name}: {weights} is a Git LFS pointer, not the weights; fetch them with git lfs pull (docs/MODELS.md)")
serving = json.loads((path / "serving.json").read_text(encoding="utf-8"))
if serving.get("base_model") != base:
    sys.exit(f"adapter {name} was trained on {serving.get('base_model')}, but the server loads {base}")
if revision and serving.get("base_revision") != revision:
    sys.exit(f"adapter {name} was trained on revision {serving.get('base_revision')}, but the server loads {revision}")
print(f"adapter {name}: {path} (base {base}@{serving.get('base_revision')}, rank {serving.get('lora_rank')})")
PY
    modules+=("$name=$dir")
  done
  args+=(--enable-lora --max-loras "${SERVE_MAX_LORAS:-2}" --max-lora-rank "${SERVE_MAX_LORA_RANK:-16}" --lora-modules "${modules[@]}")
fi

if [ -n "${SERVE_EXTRA_ARGS:-}" ]; then
  # shellcheck disable=SC2206  # word splitting is the point: a list of extra flags
  args+=($SERVE_EXTRA_ARGS)
fi
echo "vllm serve ${args[*]}"
exec vllm serve "${args[@]}"
