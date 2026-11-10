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
data/models/                                        mounted into the container
  hf/hub/models--Qwen--Qwen3.8-27B/snapshots/<rev>/   base weights (Hugging Face cache, read offline); git-ignored
  adapters/reviewer-main-27b-v1/                     the released reviewer; committed, weights through Git LFS
  adapters/reviewer-pilot-9b-v1/                     the 9B pilot; each holds adapter_model.safetensors,
                                                     adapter_config.json, serving.json, PROMOTED.json, reference/
infra/models.lock.json                               committed: every file of the 27B bundle with its SHA-256
infra/models.pilot-9b.lock.json                      the same for the 9B pilot bundle
```

The models and how they compare with their base models are described in [docs/MODELS.md](../../docs/MODELS.md). Images contain code only; models are versioned data. Changing or rolling back a model means pointing `.env` at a different adapter directory, never rebuilding an image.

At start-up, [`infra/inference/serve.sh`](../../infra/inference/serve.sh) checks every adapter:

- **Wrong base:** it refuses an adapter whose `serving.json` names a different base model or revision. Without that check, vLLM applies such an adapter anyway and answers with fluent nonsense.
- **Missing weights:** it refuses an adapter whose weights are still a Git LFS pointer.

The vLLM image is pinned to the release the reviewer adapter was evaluated with on GaaS (0.32.0). Move the digest only together with a passing served check (below).

### Configuration

```sh
COMPOSE_PROFILES=cpu,gpu                               # gpu alone stops Ollama; see generation below
VLLM_MODEL=Qwen/Qwen3.8-27B
VLLM_REVISION=1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0
VLLM_LORA_MODULES="reviewer=reviewer-main-27b-v1"     # later: "generator=generator-v1 reviewer=reviewer-main-27b-v1"
REVIEWER_ENABLED=true                                  # only after the served check passes
REVIEWER_MODEL=reviewer
```

The `VLLM_*` values are the defaults in `.env.example`.

Generation keeps using `LLM_BASE_URL` and `LLM_MODEL`:

- **Now:** Ollama, under the `cpu` profile.
- **Later:** the served base (`LLM_BASE_URL=http://inference:8000/v1`, `LLM_MODEL=Qwen/Qwen3.8-27B`), once the generation client switches thinking off. Qwen3.5/3.8 models think by default. The reviewer client switches thinking off per request, as the adapter was trained. The generation client does not yet, so add the same request option before pointing `LLM_MODEL` at a hybrid-thinking base.

### Run the released reviewer

1. **Fetch the adapter.** Plain clones skip the adapters' weights (`.lfsconfig`). With Git LFS installed (`git lfs install`, once per machine), run `git lfs pull --include="data/models/adapters/reviewer-main-27b-v1/**" --exclude=""` (467 MB).
2. **Download the pinned base** into the bundle, on a machine with internet access: `HF_HOME=data/models/hf hf download Qwen/Qwen3.8-27B --revision 1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`. It is 55.6 GB; `hf` comes with `pip install huggingface_hub`.
3. **Configure `.env`** as above, with `REVIEWER_ENABLED=false` for now.
4. **Verify and start:** `make models-verify && make up`.
   - `models-verify` checks every base and adapter file by SHA-256 against `infra/models.lock.json`, and checks the `.env` serving settings against the lock.
   - Missing, changed and unexpected files fail it, and so does an adapter weight file that is still an LFS pointer.
5. **Gate the release:** `make served-check ADAPTER=reviewer-main-27b-v1 MODEL=reviewer`.
   - It replays 50 reference items per task from the adapter's cluster evaluation against the running server, and fails if any metric moves by more than 0.05.
   - It needs the evaluation package on the host: `pip install -r packages/eval/training/requirements/data.txt -e packages/eval/training`.
6. **Enable the reviewer:** set `REVIEWER_ENABLED=true` and run `make up` again.

**The 9B pilot instead:**

- Base: `Qwen/Qwen3.5-9B` at `c202236235762e1c871ad0ccb60c8ee5ba337b9a`, about 19 GB of weights.
- Settings: `reviewer=reviewer-pilot-9b-v1`, and `LOCK=infra/models.pilot-9b.lock.json` with `make models-verify`.
- Limitation: it scores every quiz question 1, so it is not fit to review quizzes.

To ship to an offline site, transfer the images (`docker save`, or a private registry), the `data/models` tree (base snapshot and adapter) and `.env`. On the target, run `make models-verify`, then `make up`.

### Release a new adapter

1. **Train and evaluate** on GaaS ([training README](../../packages/eval/training/README.md)).
2. **Promote the run.** Copy the run directory off the cluster, then run `python -m evaltrain.promote --run <run dir> --name <name> --dest data/models/adapters`.
   - It refuses a run that has not finished, has not been evaluated, or whose adapter was not applied during evaluation.
   - It names the base by hub id and revision in `adapter_config.json`, and records the SHA-256 of the evaluated files in `PROMOTED.json`.
3. **Lock the bundle:** `make models-lock ARGS="--hub --base <hub id>@<commit> --adapter <name>"`.
   - `--hub` takes the base model's checksums from the Hugging Face Hub, so its weights need not be downloaded. Without it, the lock hashes a local snapshot in `data/models/hf`.
   - Add `LOCK=infra/models.<name>.lock.json` to keep a second bundle beside the released one.
4. **Commit** the adapter directory and the lock. `.gitattributes` stores the weights through Git LFS and keeps every other bundle file byte-for-byte.
5. **Deploy and gate** it as above.

### Sizing on one 80 GB H100

| Configuration | Fits |
|---|---|
| Qwen3.5-9B + generator and reviewer adapters, BF16 | Comfortably (~19 GB of weights) |
| Qwen3.8-27B + adapters, BF16 | Yes, with ~15 GB left for the KV cache |
| 27B generator and 9B reviewer, both BF16 | No (~75 GB of weights); use the FP8 27B (~28 GB) for the generator |

The default API/worker images use CPU embeddings even when vLLM uses a GPU. Accelerating embeddings requires a separate CUDA image and GPU device configuration.

On the `cpu` profile, a custom model must be merged into its base and converted to GGUF for Ollama. llama.cpp support for the Gated DeltaNet layers of Qwen3.5/3.8 is unverified, and quantization must be re-checked with the served check. Until then, custom models are GPU-only. Record the image digest, model lock, quantization, context length, hardware and timings before comparing workflows.