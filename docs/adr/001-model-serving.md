# ADR-001: Serve open models behind an OpenAI-compatible API

**Status**: revised · 2026-09-11

## Context
The system must run without external model APIs. Laptops support day-to-day work;
school GPU access remains to be confirmed. The revised scope evaluates pretrained
models and agent workflows without training or fine-tuning.

## Decision
- All LLM traffic goes through the OpenAI Python SDK pointed at `LLM_BASE_URL`.
- **GPU profile**: experimental vLLM serving a locally prepared Qwen model, selected after hardware and model compatibility checks.
- **CPU profile**: Ollama serving `qwen2.5:7b-instruct` by default; measure memory and latency on the team's actual laptops.
- Embeddings run in-process with sentence-transformers (`BAAI/bge-m3`), not via the LLM server.
- Structured output uses JSON mode plus schema-in-prompt and validation retries; vLLM guided decoding is an opt-in optimisation.

## Consequences
- Swapping models is an env change; the evaluation harness can iterate configurations without code changes.
- Two profiles mean two sets of numbers; the evaluation report must state which profile produced each figure.
- Validate structured output and tool calling on the selected model/server pair. The retry loop handles malformed JSON but does not establish agent compatibility or content quality.
