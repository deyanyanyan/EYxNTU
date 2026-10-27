"""Tiny random-weight Qwen3.5 checkpoint for CPU end-to-end tests.

Built from the real Qwen3.5-9B ``config.json`` with shrunken dimensions, keeping the
architecture class, the 3:1 Gated DeltaNet / full-attention layer pattern, the
attention output gate, M-RoPE and a (one-block) vision tower, plus the real tokenizer,
chat template and processor files. Outputs are noise; the point is to exercise the
real template rendering, loss masking, LoRA targeting and checkpoint/resume path.

    python tests/tiny_qwen35.py <dir with Qwen3.5-9B config/tokenizer files> <out dir>
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

COPY = ("tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt", "chat_template.jinja", "preprocessor_config.json", "video_preprocessor_config.json")


def build(meta_dir: Path, out_dir: Path) -> Path:
    import torch
    from transformers import AutoConfig, Qwen3_5ForConditionalGeneration

    cfg = json.loads((meta_dir / "config.json").read_text(encoding="utf-8"))
    t = cfg["text_config"]
    t.update(
        hidden_size=64, intermediate_size=128, num_hidden_layers=4, num_attention_heads=2, num_key_value_heads=1, head_dim=64,
        linear_num_key_heads=2, linear_num_value_heads=4, linear_key_head_dim=16, linear_value_head_dim=16, mtp_num_hidden_layers=0,
    )
    t["rope_parameters"]["mrope_section"] = [3, 3, 2]  # must sum to head_dim * partial_rotary_factor / 2
    t.pop("layer_types", None)  # recomputed from full_attention_interval=4: three linear layers, one full
    cfg["vision_config"].update(depth=1, hidden_size=32, intermediate_size=64, num_heads=2, out_hidden_size=64)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    torch.manual_seed(0)
    model = Qwen3_5ForConditionalGeneration(AutoConfig.from_pretrained(out_dir)).to(torch.bfloat16)
    model.save_pretrained(out_dir)
    for name in COPY:
        if (meta_dir / name).exists():
            shutil.copy2(meta_dir / name, out_dir / name)
    return out_dir


if __name__ == "__main__":
    out = build(Path(sys.argv[1]), Path(sys.argv[2]))
    print(out)
