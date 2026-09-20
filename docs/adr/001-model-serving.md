# ADR-001: Serve open models behind an OpenAI-compatible API

**Status**: revised · 2026-09-21

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
- The served context window is set explicitly on both sides: `OLLAMA_CONTEXT_LENGTH` / vLLM `--max-model-len` on the server, `LLM_CONTEXT_TOKENS` on the client. The client estimates prompt size and raises `ContextOverflowError` rather than allowing a call the server would truncate.

## Consequences
- Swapping models is an env change; the evaluation harness can iterate configurations without code changes.
- Two profiles mean two sets of numbers; the evaluation report must state which profile produced each figure.
- Tool calling was validated on 20 September 2026 against `qwen2.5:7b-instruct` via Ollama: correct function selection, well-formed arguments, and a successful tool-result round trip. Agent orchestration on the CPU profile is viable; content quality remains unestablished.
- Context windows must be configured deliberately. Ollama defaults to 4096 tokens and discards the oldest tokens above it **without an error**, which removes retrieved evidence from the prompt and yields a confident, ungrounded answer. Raising the window costs memory (~5.1 GB at 4k, ~5.9 GB at 16k for a 7B model) and latency (~177 s for a 13.5k-token prompt on a 20-CPU laptop).
- Per-request overrides do not work on Ollama's OpenAI-compatible endpoint; `extra_body.options.num_ctx` is ignored. The window is server configuration.
