# ADR-001: Serve open models behind an OpenAI-compatible API

**Status**: accepted · 2026-09-06

## Context
The system must run without external model APIs. The team has one H100 80GB for
development and deployment, laptops for day-to-day work, and plans to QLoRA-tune a
~30B Qwen model.

## Decision
- All LLM traffic goes through the OpenAI Python SDK pointed at `LLM_BASE_URL`.
- **GPU profile**: vLLM serving `Qwen/Qwen3-32B-AWQ` (fallback `Qwen2.5-32B-Instruct-AWQ`), prefix caching on, LoRA modules enabled so a QLoRA adapter can be A/B tested without merging.
- **CPU profile**: Ollama serving `qwen2.5:7b-instruct` so every laptop runs the full pipeline end to end.
- Embeddings run in-process with sentence-transformers (`BAAI/bge-m3`), not via the LLM server.
- Structured output uses JSON mode plus schema-in-prompt and validation retries; vLLM guided decoding is an opt-in optimisation.

## Consequences
- Swapping models is an env change; the evaluation harness can iterate configurations without code changes.
- Two profiles mean two sets of numbers; the evaluation report must state which profile produced each figure.
- Ollama and vLLM differ in JSON-mode strictness; the retry loop in `core/llm/client.py` absorbs that.
