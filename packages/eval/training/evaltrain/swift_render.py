"""Render training rows through MS-SWIFT's own template and check the loss mask.

    python -m evaltrain.swift_render --config configs/pilot_9b.yaml [--n 3]

Uses ``train.py``'s argument list, so the encoding is the one the trainer sees. For
each row it checks that

* the tokens without loss decode to the Hugging Face chat-template prompt that
  inference uses (``enable_thinking=False``, ending in the empty think block), and
* the loss-bearing tokens decode to exactly the target plus the end-of-turn token,

then writes ``swift_render.md`` in the run directory. Run it once per model/template
before the first training job (no model weights are loaded).
"""
from __future__ import annotations

import argparse
import json

from evaltrain import config as C
from evaltrain.records import read_jsonl
from evaltrain.train import RENDER_OK_MARKER, first_launch, swift_args, verify_resume


def render(cfg: dict, n: int) -> list[dict]:
    from swift.arguments import SftArguments
    from swift.utils import parse_args

    run = C.run_dir(cfg)
    run.mkdir(parents=True, exist_ok=True)
    if (run / "run.json").exists():
        verify_resume(cfg, run)
    else:
        first_launch(cfg, run)
    mixture = run / "data" / "train.jsonl"
    args, _ = parse_args(SftArguments, swift_args(cfg, run, mixture, None))
    processor = args.get_model_processor(load_model=False)[1]
    tok = getattr(processor, "tokenizer", processor)
    template = args.get_template(processor)
    template.set_mode("train")

    results = []
    for i, row in enumerate(read_jsonl(mixture)):
        if i >= n:
            break
        enc = template.encode(json.loads(json.dumps(row)))
        ids, labels = list(enc["input_ids"]), list(enc["labels"])
        first_loss = next(j for j, lab in enumerate(labels) if lab != -100)
        prompt_text = tok.decode(ids[:first_loss])
        loss_text = tok.decode([t for t, lab in zip(ids, labels, strict=True) if lab != -100])
        masked_after = [j for j in range(first_loss, len(ids)) if labels[j] == -100]
        hf_prompt = tok.apply_chat_template(row["messages"][:-1], add_generation_prompt=True, enable_thinking=False, tokenize=False)
        target = row["messages"][-1]["content"]
        results.append({
            "row": i, "tokens": len(ids), "loss_tokens": sum(lab != -100 for lab in labels),
            "prompt_matches_inference_template": prompt_text == hf_prompt,
            "loss_text_is_target_plus_eot": loss_text.rstrip("\n") == target + "<|im_end|>",
            "masked_tokens_after_first_loss_token": len(masked_after), "prompt_tail": prompt_text[-80:], "loss_text": loss_text,
        })
    md = ["# MS-SWIFT render check", "", f"Template `{cfg['model']['template']}`, model `{cfg['model'].get('path') or cfg['model']['id']}`.", ""]
    for r in results:
        md += [f"## Row {r['row']}: {r['tokens']} tokens, {r['loss_tokens']} with loss", "",
               f"- prompt equals inference chat template: **{r['prompt_matches_inference_template']}**",
               f"- loss text equals target + `<|im_end|>`: **{r['loss_text_is_target_plus_eot']}**",
               f"- masked tokens after the first loss token: {r['masked_tokens_after_first_loss_token']}", "",
               "Prompt tail (no loss):", "", f"````text\n{r['prompt_tail']}\n````", "", "Loss-bearing text:", "", f"````text\n{r['loss_text']}\n````", ""]
    (run / "swift_render.md").write_text("\n".join(md), encoding="utf-8")
    return results


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--n", type=int, default=3)
    args = ap.parse_args(argv)
    cfg = C.load(args.config)
    marker = C.run_dir(cfg) / RENDER_OK_MARKER
    marker.unlink(missing_ok=True)
    results = render(cfg, args.n)
    for r in results:
        print({k: v for k, v in r.items() if k not in ("loss_text", "prompt_tail")})
    if not results or not all(r["prompt_matches_inference_template"] and r["loss_text_is_target_plus_eot"] for r in results):
        raise SystemExit("MS-SWIFT rendering differs from the inference template or the target: inspect swift_render.md before training")
    marker.write_text(json.dumps({"checked_rows": len(results)}), encoding="utf-8")


if __name__ == "__main__":
    main()
