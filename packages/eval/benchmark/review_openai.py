"""Run the trained reviewer's prompts (evaltrain.review_batch) against a hosted API.

Same requests, same training templates, same parsing and output format as
`python -m evaltrain.review_batch --backend openai`; this wrapper only adds the API key
and drops the parameters hosted APIs reject (chat_template_kwargs, top_k, max_tokens).

    python review_openai.py --base-url https://api.openai.com/v1 --model gpt-5.5 \
        --key-env OPENAI_API_KEY --env-file .env --requests R.jsonl --out OUT.jsonl
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from evaltrain import infer
from evaltrain.prompts import PROMPT_VERSION
from evaltrain.records import read_jsonl
from evaltrain.review_batch import render


class HostedBackend:
    def __init__(self, base_url, model, key, logprobs, reasoning):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model, self.key, self.logprobs, self.reasoning = model, key, logprobs, reasoning
        self.min_tokens = int(os.environ.get("MIN_TOKENS", "256"))

    def _post(self, body):
        for attempt in range(6):
            req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")[:300]
                if e.code in (429, 500, 502, 503) and attempt < 5:
                    time.sleep(5 * 2 ** attempt)
                    continue
                raise SystemExit(f"HTTP {e.code}: {msg}")

    def generate(self, conversations, max_tokens, want_logprobs):
        gens = []
        for conv in conversations:
            body = {"model": self.model, "messages": conv, "temperature": 0, "max_completion_tokens": max(max_tokens, self.min_tokens)}  # hosted models may wrap JSON in fences
            if self.reasoning:
                body["reasoning_effort"] = self.reasoning
            if want_logprobs and self.logprobs:
                body |= {"logprobs": True, "top_logprobs": min(infer.TOP_LOGPROBS, 20)}
            resp = self._post(body)
            choice = resp["choices"][0]
            content = (choice.get("logprobs") or {}).get("content") or []
            pieces = [c["token"] for c in content]
            top = [[(t["token"], t["logprob"]) for t in c.get("top_logprobs", [])] for c in content]
            usage = resp.get("usage") or {}
            gens.append(infer.Generation(choice["message"].get("content") or "", pieces, top, usage.get("prompt_tokens"), usage.get("completion_tokens")))
        return gens


def read_key(env_file, name):
    if os.environ.get(name):
        return os.environ[name]
    for line in Path(env_file).read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit(f"{name} not found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--key-env", required=True)
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--requests", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-logprobs", action="store_true")
    ap.add_argument("--reasoning", default="none", help="reasoning_effort for reasoning models; '' to omit")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    requests = list(read_jsonl(a.requests))[: a.limit or None]
    examples = [render(r) for r in requests]
    refs = {r["id"]: r.get("ref") for r in requests}
    backend = HostedBackend(a.base_url, a.model, read_key(a.env_file, a.key_env), not a.no_logprobs, a.reasoning or None)
    out = Path(a.out)
    raw = out.with_suffix(".predictions.jsonl")
    stats = infer.run(examples, raw, backend, batch_size=1, thinking=False, extra_think_tokens=0, image_root=None, deadline=None)
    rows = [dict(p, ref=refs.get(p["id"])) for p in read_jsonl(raw)]
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    meta = {
        "reviewer": {"base_model": a.model, "base_revision": None, "adapter": None, "adapter_checkpoint": None, "training_hash": None,
                     "prompt_version": PROMPT_VERSION, "thinking": False, "sampling": {"temperature": 0.0}, "endpoint": a.base_url},
        "requests": len(requests), "valid": sum(r["valid"] for r in rows), "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "inference": stats,
    }
    out.with_suffix(out.suffix + ".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"requests": len(requests), "valid": meta["valid"], "seconds": round(stats["seconds"], 1)}))


if __name__ == "__main__":
    main()
