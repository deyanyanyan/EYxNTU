# Local model serving

The default laptop setup uses Ollama. Model calls go through the configured local endpoint. No external API key is required.

From the repository root:

```sh
sh scripts/compose.sh up --wait
sh scripts/compose.sh exec ollama ollama pull qwen2.5:7b-instruct
sh scripts/compose.sh exec -T api python /srv/scripts/smoke.py --llm
```

On Windows replace `sh scripts/compose.sh` with `powershell -ExecutionPolicy Bypass -File scripts/compose.ps1`.

Set `LLM_MODEL` to the exact model you pulled. Weights persist in `data/models/ollama`. The model smoke check validates structured JSON.

## Context window

Ollama serves a 4096-token window unless told otherwise, and prompts above it lose their oldest tokens **with no error and no warning** — retrieved evidence disappears and the model answers confidently from what is left. `OLLAMA_CONTEXT_LENGTH` (Compose) and `LLM_CONTEXT_TOKENS` (client) both default to 16384 and must be changed together. The API refuses a prompt that would not fit rather than letting the server truncate it; call `prompt_token_budget()` when assembling retrieved chunks to stay inside it.

Measured on a 20-CPU / 15.5 GiB laptop with `qwen2.5:7b-instruct`: resident memory 5.1 GB at 4k and 5.9 GB at 16k; a 13.5k-token prompt took 177 s. Budget accordingly before enabling long-context retrieval on laptops. A per-request `num_ctx` override is ignored by the OpenAI-compatible endpoint.

Tool calling was verified on 20 September 2026 (correct function selection, well-formed arguments, working tool-result round trip). Agent behaviour and content quality still require separate benchmarking.

## GPU profile: custom models

The `gpu` profile serves one base model plus the team's custom LoRA adapters from a single vLLM container (`inference`). The app reaches it through the same OpenAI-compatible API it already uses. Each adapter is requested by name as the chat `model`. The course generator and the reviewer can therefore share one GPU and one copy of the base weights; a model built on a different base needs its own inference service.

It needs a Linux host with an NVIDIA GPU and container GPU support. It has not been validated on a GPU host yet. The host vLLM port is 8001; port 8000 belongs to the application API.

### Model bundle

```text
data/models/                                        git-ignored, mounted into the container
  hf/hub/models--Qwen--Qwen3.5-9B/snapshots/<rev>/   base weights (Hugging Face cache, read offline)
  adapters/reviewer-pilot-9b-v1/                     adapter_model.safetensors, adapter_config.json,
                                                     serving.json, PROMOTED.json, reference/
infra/models.lock.json                               committed: every bundle file with its SHA-256
```

Images contain code only; models are versioned data. Changing or rolling back a model means pointing `.env` at a different adapter directory, never rebuilding an image.

At start-up, [`infra/inference/serve.sh`](../../infra/inference/serve.sh) refuses any adapter whose `serving.json` names a different base model or revision. Without that check, vLLM applies such an adapter anyway and answers with fluent nonsense. The vLLM image is pinned to the release the reviewer adapter is evaluated with on GaaS (0.32.0). Move the digest only together with a passing served check (below).

### Configuration

```sh
COMPOSE_PROFILES=gpu
VLLM_MODEL=Qwen/Qwen3.5-9B
VLLM_REVISION=c202236235762e1c871ad0ccb60c8ee5ba337b9a
VLLM_LORA_MODULES="reviewer=reviewer-pilot-9b-v1"     # later: "generator=generator-v1 reviewer=reviewer-pilot-9b-v1"
LLM_BASE_URL=http://inference:8000/v1
LLM_MODEL=Qwen/Qwen3.5-9B                              # or an adapter name, once a generator adapter exists
REVIEWER_ENABLED=true                                  # only after the served check passes
REVIEWER_MODEL=reviewer
```

Qwen3.5/3.8 models think by default. The reviewer client switches thinking off per request, as the adapter was trained. The generation client does not yet, so add the same request option before pointing `LLM_MODEL` at a hybrid-thinking base.

### Release steps

1. Train and evaluate on GaaS ([training README](../../packages/eval/training/README.md)).
2. Promote the adapter. Copy the run directory from the cluster, then run `python -m evaltrain.promote --run <run dir> --name reviewer-pilot-9b-v1 --dest data/models/adapters`. It refuses a run that has not finished, has not been evaluated, or whose adapter was not applied during evaluation.
3. Stage the pinned base revision into `data/models/hf` on a machine with internet access: `HF_HOME=data/models/hf hf download Qwen/Qwen3.5-9B --revision <rev>`.
4. Lock the bundle and commit `infra/models.lock.json`: `make models-lock ARGS="--base Qwen/Qwen3.5-9B@<rev> --adapter reviewer-pilot-9b-v1"`.
5. On the serving host, run `make models-verify && make up`. Verification fails on any missing, changed or unexpected file, and on `.env` serving settings that disagree with the lock.
6. Gate the release with `make served-check ADAPTER=reviewer-pilot-9b-v1 MODEL=reviewer`. It replays part of the adapter's cluster evaluation against the running server and fails if the scores move. Only then set `REVIEWER_ENABLED=true`. The check needs the evaluation package on the host: `pip install -r packages/eval/training/requirements/data.txt -e packages/eval/training`.

To ship to an offline site, transfer the images (`docker save`, or a private registry), the locked `data/models` tree and `.env`. On the target, run `make models-verify`, then `make up`.

### Sizing on one 80 GB H100

| Configuration | Fits |
|---|---|
| Qwen3.5-9B + generator and reviewer adapters, BF16 | Comfortably (~19 GB of weights) |
| Qwen3.8-27B + adapters, BF16 | Yes, with ~15 GB left for the KV cache |
| 27B generator and 9B reviewer, both BF16 | No (~75 GB of weights); use the FP8 27B (~28 GB) for the generator |

The default API/worker images use CPU embeddings even when vLLM uses a GPU. Accelerating embeddings requires a separate CUDA image and GPU device configuration.

On the `cpu` profile, a custom model must be merged into its base and converted to GGUF for Ollama. llama.cpp support for the Gated DeltaNet layers of Qwen3.5/3.8 is unverified, and quantization must be re-checked with the served check. Until then, custom models are GPU-only. Record the image digest, model lock, quantization, context length, hardware and timings before comparing workflows.