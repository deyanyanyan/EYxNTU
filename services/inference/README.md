# Inference service

No code here: the LLM is served by an off-the-shelf OpenAI-compatible server
selected by the compose profile. The API and worker only know `LLM_BASE_URL`
and `LLM_MODEL`.

| profile | server | model | where |
|---|---|---|---|
| cpu | Ollama | `qwen2.5:7b-instruct` (Q4_K_M) | laptops, ~5 GB RAM |
| gpu | vLLM | `Qwen/Qwen3-32B-AWQ` (or FP8) | 1x H100 80GB |

## First-time model pull (needs internet once, then air-gapped)
```bash
# cpu
docker compose exec ollama ollama pull qwen2.5:7b-instruct

# gpu: download weights into data/models/hf so vLLM never touches the network
huggingface-cli download Qwen/Qwen3-32B-AWQ --local-dir data/models/hf/Qwen3-32B-AWQ
```

## Serving a QLoRA adapter (M5)
Set in `.env`:
```
VLLM_LORA_MODULES=lms-adapter=/data/models/adapters/lms-qlora
```
and request `model: "lms-adapter"` from the API by setting `LLM_MODEL=lms-adapter`.
vLLM hot-loads the adapter over the base model; no re-quantisation needed for
evaluation. Merge + re-quantise only for the final deployment.

## Sanity check
```bash
curl http://localhost:8000/v1/models   # gpu profile (vLLM)
curl http://localhost:11434/v1/models  # cpu profile (Ollama)
```
