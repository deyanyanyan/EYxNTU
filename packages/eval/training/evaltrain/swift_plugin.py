"""MS-SWIFT plugin: registers the walltime callback (``--callbacks evaltrain_walltime``).

Loaded by ``swift sft --external_plugins <this file>``, which ``train.py`` passes. The
budget and expectations arrive through environment variables set by ``train.py``:

* ``EVALTRAIN_DEADLINE_EPOCH`` / ``_RESERVE_SECONDS`` / ``_SAVE_EVERY_SECONDS``;
* ``EVALTRAIN_STATUS_DIR``: where ``job_status.json`` is written;
* ``EVALTRAIN_EXPECTED_ROWS``: number of rows in the mixture. MS-SWIFT drops (eager
  encoding) or silently substitutes (lazy encoding, ``strict=False``) samples it cannot
  encode, so training stops at once if its dataset size differs from the mixture.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from swift.callbacks import callbacks_map

from evaltrain.callbacks import ENV_EXPECTED_ROWS, ENV_STATUS_DIR, WalltimeBudget, WalltimeCheckpointCallback


class SwiftWalltimeCallback(WalltimeCheckpointCallback):
    def __init__(self, args, trainer):
        budget = WalltimeBudget.from_env()
        if budget is None:
            raise RuntimeError("EVALTRAIN_DEADLINE_EPOCH is not set: launch training through `python -m evaltrain.train`")
        super().__init__(budget, status_dir=os.environ.get(ENV_STATUS_DIR))
        self.args, self.trainer = args, trainer

    def on_train_begin(self, args, state, control, **kwargs):
        expected = os.environ.get(ENV_EXPECTED_ROWS)
        dataset = getattr(self.trainer, "train_dataset", None)
        if expected and dataset is not None and hasattr(dataset, "__len__") and len(dataset) != int(expected):
            raise RuntimeError(
                f"MS-SWIFT train dataset has {len(dataset)} rows but the mixture has {expected}: "
                "samples were dropped or replaced during encoding. Re-run `evaltrain lengths` with this template."
            )
        params = list(self.trainer.model.named_parameters())
        trainable = [(n, p.numel()) for n, p in params if p.requires_grad]
        if state.is_world_process_zero:
            bad = [n for n, _ in trainable if ".visual." in n or "lora_" not in n]
            audit = {
                "trainable_tensors": len(trainable), "trainable_params": sum(c for _, c in trainable), "total_params": sum(p.numel() for _, p in params),
                "unexpected": bad, "names": [n for n, _ in trainable],
            }
            out = Path(os.environ.get(ENV_STATUS_DIR) or args.output_dir) / "trainable_params.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(audit, indent=2), encoding="utf-8")
            print(f"[evaltrain] trainable tensors={audit['trainable_tensors']} params={audit['trainable_params']:,} of {audit['total_params']:,}; unexpected={len(bad)}")
            if bad:
                raise RuntimeError(f"unexpected trainable parameters (vision tower or non-LoRA): {bad[:5]}")
        return super().on_train_begin(args, state, control, **kwargs)


callbacks_map["evaltrain_walltime"] = SwiftWalltimeCallback
