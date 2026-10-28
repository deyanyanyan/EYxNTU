"""Batch review inference: prepared examples -> predictions JSONL.

    python -m evaltrain.infer --examples dev.jsonl --out preds.jsonl --backend vllm \
        --model $HF_HOME/models/Qwen3.5-9B --revision <sha> [--adapter runs/<id>/adapter]

Backends:
  vllm    offline engine on the allocated GPU (baselines, adapter evaluation, PBS batches)
  hf      transformers ``generate``, for CPU smoke tests and debugging
  openai  any OpenAI-compatible endpoint (a vLLM server; Ollama for local checks)

Each output line: ``{"id", "task", "raw", "parsed", "valid", "strict", "error",
"score_dist", "n_prompt_tokens", "n_output_tokens", "latency_s"}``. ``parsed`` is the
task-validated JSON object and ``score_dist`` holds digit probabilities per score
key when the backend returns log-probabilities. A sidecar ``<out>.meta.json``
records the model, revision, adapter, prompt version, thinking setting, sampling,
package versions and timing.

Ids already present in ``--out`` are skipped, so an interrupted batch resumes where it
stopped; ``--deadline-epoch`` stops cleanly between batches before PBS walltime.
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import platform
import time
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

from evaltrain import parsing
from evaltrain import tasks as T
from evaltrain.prompts import PROMPT_VERSION
from evaltrain.records import Example, read_examples, read_jsonl

TOP_LOGPROBS = 20


@dataclass
class Generation:
    text: str
    pieces: list[str]
    top: list[list[tuple[str, float]]]
    n_prompt_tokens: int | None
    n_output_tokens: int | None


def _with_images(ex: Example, root: Path | None) -> list[dict]:
    """OpenAI-style content parts: the image(s) precede the user text."""
    if not ex.images:
        return ex.messages
    parts = []
    for rel in ex.images:
        path = (root / rel) if root else Path(rel)
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        data = base64.b64encode(path.read_bytes()).decode()
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
    msgs = [dict(m) for m in ex.messages]
    user = msgs[-1]
    msgs[-1] = {"role": user["role"], "content": [*parts, {"type": "text", "text": user["content"]}]}
    return msgs


# --- backends ----------------------------------------------------------------------


@dataclass(frozen=True)
class Sampling:
    """Greedy by default. The thinking-mode baseline uses Qwen's documented thinking
    sampling instead, because greedy decoding of long reasoning tends to loop."""

    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = -1
    seed: int = 0


class VLLMBackend:
    def __init__(self, model: str, revision: str | None, adapter: str | None, max_model_len: int, thinking: bool, sampling: Sampling, lora_rank: int, multimodal: bool, gpu_mem: float):
        from vllm import LLM
        from vllm.lora.request import LoRARequest

        kw = dict(model=model, revision=revision, tokenizer_revision=revision, dtype="bfloat16", max_model_len=max_model_len, seed=sampling.seed, gpu_memory_utilization=gpu_mem)
        if not multimodal:
            kw["limit_mm_per_prompt"] = {"image": 0, "video": 0}  # text-only: skip vision profiling
        if adapter:
            kw |= dict(enable_lora=True, max_lora_rank=lora_rank, max_loras=1)
        self.llm = LLM(**kw)
        self.lora = LoRARequest("reviewer", 1, adapter) if adapter else None
        self.thinking, self.sampling = thinking, sampling

    def generate(self, conversations: list[list[dict]], max_tokens: int, want_logprobs: bool) -> list[Generation]:
        from vllm import SamplingParams

        s = self.sampling
        sp = SamplingParams(temperature=s.temperature, top_p=s.top_p, top_k=s.top_k, seed=s.seed if s.temperature > 0 else None,
                            max_tokens=max_tokens, logprobs=TOP_LOGPROBS if want_logprobs else None)
        outs = self.llm.chat(conversations, sp, lora_request=self.lora, chat_template_kwargs={"enable_thinking": self.thinking}, use_tqdm=False)
        gens = []
        for o in outs:
            c = o.outputs[0]
            pieces, top = [], []
            if c.logprobs:
                for tid, lp in zip(c.token_ids, c.logprobs, strict=False):
                    pieces.append(lp[tid].decoded_token if tid in lp else "")
                    top.append([(v.decoded_token or "", v.logprob) for v in lp.values()])
            gens.append(Generation(c.text, pieces, top, len(o.prompt_token_ids or []), len(c.token_ids)))
        return gens


class HFBackend:
    def __init__(self, model: str, revision: str | None, adapter: str | None, thinking: bool, multimodal: bool, sampling: Sampling = Sampling()):
        import torch
        from transformers import AutoConfig, AutoModelForCausalLM, AutoModelForImageTextToText, AutoProcessor, AutoTokenizer

        self.torch = torch
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        # Load the checkpoint's own class even for text-only inputs: MS-SWIFT trains the
        # multimodal class, whose language model sits under model.language_model, and an
        # adapter does not attach to the text-only class's module names.
        arch = (AutoConfig.from_pretrained(model, revision=revision).architectures or [""])[0]
        loader = AutoModelForImageTextToText if multimodal or arch.endswith("ForConditionalGeneration") else AutoModelForCausalLM
        self.model = loader.from_pretrained(model, revision=revision, dtype=dtype, device_map="auto" if torch.cuda.is_available() else None)
        if adapter:
            from peft import PeftModel

            self.model = PeftModel.from_pretrained(self.model, adapter)
        self.model.eval()
        self.proc = AutoProcessor.from_pretrained(model, revision=revision) if multimodal else AutoTokenizer.from_pretrained(model, revision=revision)
        self.tok = getattr(self.proc, "tokenizer", self.proc)
        self.thinking, self.sampling = thinking, sampling

    def generate(self, conversations: list[list[dict]], max_tokens: int, want_logprobs: bool) -> list[Generation]:
        torch = self.torch
        s = self.sampling
        sample_kw = dict(do_sample=True, temperature=s.temperature, top_p=s.top_p, top_k=s.top_k if s.top_k > 0 else None) if s.temperature > 0 else dict(do_sample=False)
        gens = []
        for conv in conversations:
            enc = self.proc.apply_chat_template(conv, add_generation_prompt=True, enable_thinking=self.thinking, tokenize=True, return_dict=True, return_tensors="pt")
            enc = {k: v.to(self.model.device) for k, v in enc.items()}
            n_prompt = enc["input_ids"].shape[1]
            if s.temperature > 0:
                torch.manual_seed(s.seed)
            with torch.no_grad():
                out = self.model.generate(**enc, max_new_tokens=max_tokens, output_scores=want_logprobs, return_dict_in_generate=True, **sample_kw)
            ids = out.sequences[0, n_prompt:].tolist()
            pieces, top = [], []
            if want_logprobs:
                for tid, scores in zip(ids, out.scores, strict=False):
                    lp = torch.log_softmax(scores[0].float(), dim=-1)
                    vals, idx = lp.topk(TOP_LOGPROBS)
                    pieces.append(self.tok.decode([tid]))
                    top.append([(self.tok.decode([i]), v) for v, i in zip(vals.tolist(), idx.tolist(), strict=True)])
            gens.append(Generation(self.tok.decode(ids, skip_special_tokens=True), pieces, top, n_prompt, len(ids)))
        return gens


class OpenAIBackend:
    def __init__(self, base_url: str, model: str, thinking: bool, sampling: Sampling = Sampling(), api_key: str | None = None):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model, self.thinking, self.sampling, self.key = model, thinking, sampling, api_key

    def generate(self, conversations: list[list[dict]], max_tokens: int, want_logprobs: bool) -> list[Generation]:
        import urllib.request

        s = self.sampling
        gens = []
        for conv in conversations:
            body = {"model": self.model, "messages": conv, "temperature": s.temperature, "top_p": s.top_p, "max_tokens": max_tokens, "seed": s.seed,
                    "chat_template_kwargs": {"enable_thinking": self.thinking}}
            if s.top_k > 0:
                body["top_k"] = s.top_k
            if want_logprobs:
                body |= {"logprobs": True, "top_logprobs": TOP_LOGPROBS}
            req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {self.key}"} if self.key else {})})
            with urllib.request.urlopen(req, timeout=600) as r:
                resp = json.load(r)
            choice = resp["choices"][0]
            content = (choice.get("logprobs") or {}).get("content") or []
            pieces = [c["token"] for c in content]
            top = [[(t["token"], t["logprob"]) for t in c.get("top_logprobs", [])] for c in content]
            usage = resp.get("usage") or {}
            gens.append(Generation(choice["message"]["content"] or "", pieces, top, usage.get("prompt_tokens"), usage.get("completion_tokens")))
        return gens


# --- driver ------------------------------------------------------------------------


def predict_record(ex: Example, gen: Generation, latency: float) -> dict:
    task = T.get(ex.task)
    obj, strict, error = parsing.extract_json(gen.text)
    parsed = None
    if obj is not None:
        try:
            parsed = task.parse(obj)
        except (ValueError, TypeError, KeyError) as exc:
            error, strict = f"invalid fields: {exc}", False
    dist = parsing.score_distributions(gen.pieces, gen.top, task.score_keys) if task.score_keys and gen.top else {}
    return {
        "id": ex.id, "task": ex.task, "raw": gen.text, "parsed": parsed, "valid": parsed is not None, "strict": bool(strict and parsed is not None),
        "error": error if parsed is None else None, "score_dist": dist, "n_prompt_tokens": gen.n_prompt_tokens, "n_output_tokens": gen.n_output_tokens, "latency_s": latency,
    }


def batched(items: list, n: int) -> Iterator[list]:
    for i in range(0, len(items), n):
        yield items[i : i + n]


def run(examples: Iterable[Example], out: Path, backend, *, batch_size: int, thinking: bool, extra_think_tokens: int, image_root: Path | None, deadline: float | None) -> dict:
    done = {r["id"] for r in read_jsonl(out)} if out.exists() else set()
    todo = [e for e in examples if e.id not in done]
    by_task: dict[str, list[Example]] = {}
    for e in todo:
        by_task.setdefault(e.task, []).append(e)
    stats = {"skipped_existing": len(done), "predicted": 0, "stopped_for_deadline": False, "seconds": 0.0}
    t0 = time.time()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8", newline="\n") as f:
        for name, exs in by_task.items():
            task = T.get(name)
            max_tokens = task.max_new_tokens + (extra_think_tokens if thinking else 0)
            for batch in batched(exs, batch_size):
                if deadline and time.time() > deadline:
                    stats["stopped_for_deadline"] = True
                    break
                start = time.time()
                gens = backend.generate([_with_images(e, image_root) for e in batch], max_tokens, bool(task.score_keys))
                per = (time.time() - start) / len(batch)
                for e, g in zip(batch, gens, strict=True):
                    f.write(json.dumps(predict_record(e, g, per), ensure_ascii=False) + "\n")
                f.flush()
                stats["predicted"] += len(batch)
    stats["seconds"] = time.time() - t0
    return stats


def _versions() -> dict:
    import importlib.metadata as md

    out = {"python": platform.python_version()}
    for pkg in ("torch", "transformers", "peft", "vllm", "ms-swift"):
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            pass
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--examples", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--backend", choices=["vllm", "hf", "openai"], default="vllm")
    ap.add_argument("--model", required=True, help="local path or hub id (vllm/hf); served model name (openai)")
    ap.add_argument("--revision")
    ap.add_argument("--adapter")
    ap.add_argument("--base-url", help="openai backend endpoint, e.g. http://localhost:8000/v1")
    ap.add_argument("--tasks", nargs="*", help="restrict to these tasks")
    ap.add_argument("--limit-per-task", type=int)
    ap.add_argument("--thinking", action="store_true", help="enable the chat template's thinking mode (default: off)")
    ap.add_argument("--extra-think-tokens", type=int, default=4096)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--max-model-len", type=int, default=8192)
    ap.add_argument("--lora-rank", type=int, default=32)
    ap.add_argument("--gpu-mem", type=float, default=0.90)
    ap.add_argument("--image-root", help="directory that example image paths are relative to")
    ap.add_argument("--deadline-epoch", type=float)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--temperature", type=float, default=0.0, help="0 = greedy (default)")
    ap.add_argument("--top-p", type=float, default=1.0)
    ap.add_argument("--top-k", type=int, default=-1)
    args = ap.parse_args(argv)
    sampling = Sampling(args.temperature, args.top_p, args.top_k, args.seed)

    examples = read_examples(args.examples)
    if args.tasks:
        examples = [e for e in examples if e.task in set(args.tasks)]
    if args.limit_per_task:
        seen: dict[str, int] = {}
        kept = []
        for e in examples:
            if seen.get(e.task, 0) < args.limit_per_task:
                kept.append(e)
                seen[e.task] = seen.get(e.task, 0) + 1
        examples = kept
    multimodal = any(T.get(e.task).multimodal for e in examples)

    if args.backend == "vllm":
        backend = VLLMBackend(args.model, args.revision, args.adapter, args.max_model_len, args.thinking, sampling, args.lora_rank, multimodal, args.gpu_mem)
    elif args.backend == "hf":
        backend = HFBackend(args.model, args.revision, args.adapter, args.thinking, multimodal, sampling)
    else:
        backend = OpenAIBackend(args.base_url, args.model, args.thinking, sampling)

    out = Path(args.out)
    stats = run(examples, out, backend, batch_size=args.batch_size if args.backend == "vllm" else 1, thinking=args.thinking,
                extra_think_tokens=args.extra_think_tokens, image_root=Path(args.image_root) if args.image_root else None, deadline=args.deadline_epoch)
    meta = {
        "examples": args.examples, "backend": args.backend, "model": args.model, "revision": args.revision, "adapter": args.adapter,
        "prompt_version": PROMPT_VERSION, "thinking": args.thinking, "sampling": {**asdict(sampling), "top_logprobs": TOP_LOGPROBS},
        "max_model_len": args.max_model_len, "versions": _versions(), "finished_at_epoch": time.time(), **stats,
    }
    meta_path = out.with_suffix(out.suffix + ".meta.json")
    history = json.loads(meta_path.read_text()) if meta_path.exists() else []
    meta_path.write_text(json.dumps([*history, meta], indent=2), encoding="utf-8")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
