"""GPU stack smoke test for the allocated node (runs in seconds, no downloads).

    python -m evaltrain.gpu_smoke

Checks CUDA and a BF16 matmul, the Gated DeltaNet Triton kernel (forward and backward)
from flash-linear-attention, then the exact Qwen3.5 code path: a tiny random
``Qwen3_5ForCausalLM`` with the 3:1 linear/full-attention layout trained for one step
on a 2,048-token sequence. transformers falls back to slow PyTorch kernels without
announcing it in results, so the test fails if that fallback warning appears.
Finally it imports MS-SWIFT and vLLM. Exit code 0 means every check passed.
"""
from __future__ import annotations

import importlib.metadata as md
import json
import logging
import sys
import time
import warnings


def main() -> None:
    import torch

    report: dict = {"torch": torch.__version__, "torch_cuda": torch.version.cuda, "cuda_available": torch.cuda.is_available()}
    if not torch.cuda.is_available():
        print(json.dumps(report))
        raise SystemExit("CUDA not available")
    dev = torch.device("cuda")
    report["device"] = torch.cuda.get_device_name(0)
    report["memory_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1)

    a = torch.randn(8192, 8192, device=dev, dtype=torch.bfloat16)
    torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(20):
        a @ a
    torch.cuda.synchronize()
    report["bf16_matmul_tflops"] = round(20 * 2 * 8192**3 / (time.time() - t0) / 1e12, 1)

    failures = []
    try:
        from fla.ops.gated_delta_rule import chunk_gated_delta_rule

        b, t, h, k = 1, 2048, 4, 128
        q, kk, v = (torch.randn(b, t, h, k, device=dev, dtype=torch.bfloat16, requires_grad=True) for _ in range(3))
        g = torch.nn.functional.logsigmoid(torch.randn(b, t, h, device=dev, dtype=torch.float32)).requires_grad_()
        beta = torch.rand(b, t, h, device=dev, dtype=torch.bfloat16).requires_grad_()
        o, _ = chunk_gated_delta_rule(q, kk, v, g, beta, use_qk_l2norm_in_kernel=True)
        o.float().sum().backward()
        report["fla_kernel"] = "ok"
    except Exception as exc:  # report and continue: the tiny-model check below is decisive
        report["fla_kernel"] = f"error: {type(exc).__name__}: {exc}"[:300]

    from transformers import Qwen3_5ForCausalLM, Qwen3_5TextConfig

    cfg = Qwen3_5TextConfig(
        vocab_size=1024, hidden_size=256, intermediate_size=512, num_hidden_layers=4, num_attention_heads=4, num_key_value_heads=2, head_dim=64,
        linear_num_key_heads=2, linear_num_value_heads=4, linear_key_head_dim=64, linear_value_head_dim=64, max_position_embeddings=4096,
    )
    model = Qwen3_5ForCausalLM(cfg).to(dev, torch.bfloat16)
    ids = torch.randint(0, 1024, (1, 2048), device=dev)

    class _Capture(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.messages: list[str] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.messages.append(record.getMessage())

    # transformers reports the fallback through logger.warning_once, not the warnings module
    capture = _Capture()
    logging.getLogger("transformers").addHandler(capture)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        loss = model(input_ids=ids, labels=ids).loss
        loss.backward()
    logging.getLogger("transformers").removeHandler(capture)
    messages = capture.messages + [str(w.message) for w in caught]
    fallback = [m[:200] for m in messages if "falling back" in m.lower()]
    report["qwen3_5_layer_types"] = sorted(set(cfg.layer_types))
    report["qwen3_5_train_step"] = "ok" if loss.isfinite() else "non-finite loss"
    report["slow_fallback_warnings"] = fallback
    # The gated-delta-rule fallback is the expensive one (>10x slower); the causal_conv1d
    # fallback is a width-4 depthwise convolution and is acceptable without that package.
    if any("gated_delta_rule" in m for m in fallback):
        failures.append("transformers used the slow PyTorch fallback for the Gated DeltaNet kernel")
    if not loss.isfinite():
        failures.append("non-finite loss in tiny Qwen3.5 step")

    for pkg, mod in (("ms_swift", "swift"), ("vllm", "vllm"), ("flash-linear-attention", "fla"), ("transformers", "transformers"), ("peft", "peft")):
        try:
            __import__(mod)
            report[pkg] = md.version(pkg)
        except Exception as exc:
            report[pkg] = f"import error: {exc}"[:200]
            failures.append(f"cannot import {mod}")
    report["failures"] = failures
    print(json.dumps(report, indent=2))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
