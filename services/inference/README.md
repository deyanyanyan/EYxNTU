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

## GPU workstream

The optional vLLM profile needs a Linux NVIDIA host, GPU container support, prepared local model weights, and a verified model/server configuration. It has not been validated on this Windows CPU setup.

Set `COMPOSE_PROFILES=gpu`, `LLM_BASE_URL=http://inference:8000/v1`, and configure `VLLM_MODEL` to the prepared local model directory inside `/data/models/`. Set `LLM_MODEL` to the same served name. The host vLLM port is 8001; port 8000 belongs to the application API.

The default API/worker images use CPU embeddings even when vLLM uses a GPU. Accelerating embeddings requires a separate CUDA image and GPU device configuration.

Use pretrained models. Fine-tuning and adapter serving are outside the revised deliverable. Record the selected image digest, model revision, quantization, context length, hardware and timing results before comparing workflows.