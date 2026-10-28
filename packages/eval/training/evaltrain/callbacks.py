"""Walltime-aware checkpointing for the four-hour PBS queue.

PBS kills a job at its walltime, so the trainer has to save a complete, resumable
checkpoint and exit on its own before that. Hugging Face ``Trainer`` (which
MS-SWIFT subclasses) already writes adapter, optimizer, scheduler, RNG and trainer
state together whenever ``control.should_save`` is set; this callback only decides
*when* to save and stop:

* every ``save_every_s`` seconds of training (time-based, because throughput is
  unknown until measured, so a fixed ``save_steps`` would be a guess);
* when the projected end of the next optimizer step would eat into ``reserve_s``
  before the deadline, it saves and stops;
* after SIGTERM/SIGUSR1 (``qdel`` or scheduler pre-emption), at the next step boundary.

After each save it writes ``CHECKPOINT_COMPLETE.json`` into the checkpoint directory,
so a resumed job never selects a checkpoint that was interrupted mid-write, and on
exit it writes ``job_status.json`` so the PBS script can tell "finished" from
"stopped for walltime".
"""
from __future__ import annotations

import json
import os
import re
import signal
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from transformers import TrainerCallback

COMPLETE_MARKER = "CHECKPOINT_COMPLETE.json"
STATUS_FILE = "job_status.json"
TRAINING_DONE_MARKER = "TRAINING_COMPLETE.json"
_CHECKPOINT_RE = re.compile(r"^checkpoint-(\d+)$")

ENV_DEADLINE = "EVALTRAIN_DEADLINE_EPOCH"
ENV_RESERVE = "EVALTRAIN_RESERVE_SECONDS"
ENV_SAVE_EVERY = "EVALTRAIN_SAVE_EVERY_SECONDS"
ENV_STOP_AFTER = "EVALTRAIN_STOP_AFTER_STEPS"
ENV_STATUS_DIR = "EVALTRAIN_STATUS_DIR"
ENV_EXPECTED_ROWS = "EVALTRAIN_EXPECTED_ROWS"  # checked by the MS-SWIFT plugin at train start


@dataclass(frozen=True)
class WalltimeBudget:
    deadline: float  # wall-clock epoch seconds by which the process must have exited
    reserve_s: float = 20 * 60  # kept free for the final save and shutdown
    save_every_s: float = 12 * 60  # periodic checkpoint interval
    stop_after_steps: int | None = None  # deterministic stop for the pilot's stop/resume test

    @classmethod
    def from_job(cls, job_start_epoch: float, walltime_s: float, **kw) -> WalltimeBudget:
        return cls(deadline=job_start_epoch + walltime_s, **kw)

    @classmethod
    def from_env(cls) -> WalltimeBudget | None:
        """Read the budget exported by ``train.py`` (used inside the MS-SWIFT plugin)."""
        if ENV_DEADLINE not in os.environ:
            return None
        stop = os.environ.get(ENV_STOP_AFTER)
        return cls(
            deadline=float(os.environ[ENV_DEADLINE]),
            reserve_s=float(os.environ.get(ENV_RESERVE, 20 * 60)),
            save_every_s=float(os.environ.get(ENV_SAVE_EVERY, 12 * 60)),
            stop_after_steps=int(stop) if stop else None,
        )

    def to_env(self) -> dict[str, str]:
        env = {ENV_DEADLINE: repr(self.deadline), ENV_RESERVE: repr(self.reserve_s), ENV_SAVE_EVERY: repr(self.save_every_s)}
        if self.stop_after_steps:
            env[ENV_STOP_AFTER] = str(self.stop_after_steps)
        return env


class WalltimeCheckpointCallback(TrainerCallback):
    def __init__(self, budget: WalltimeBudget, status_dir: str | Path | None = None, clock=time.time, install_signal_handlers: bool = True):
        self.budget = budget
        self.status_dir = Path(status_dir) if status_dir else None
        self.clock = clock
        self._last_save = clock()
        self._step_started: float | None = None
        self._step_ema: float | None = None
        self._save_requested_at: float | None = None
        self._save_reason: str | None = None
        self._stop_reason: str | None = None
        self._signal: str | None = None
        self._first_step: int | None = None
        self.saves: list[dict] = []
        if install_signal_handlers:
            for name in ("SIGTERM", "SIGUSR1"):
                sig = getattr(signal, name, None)
                if sig is not None:
                    signal.signal(sig, self._on_signal)

    def _on_signal(self, signum, _frame) -> None:
        self._signal = signal.Signals(signum).name

    def on_train_begin(self, args, state, control, **kwargs):
        self._first_step = state.global_step
        self._last_save = self.clock()
        if self.clock() + self.budget.reserve_s >= self.budget.deadline:
            print(f"[walltime] WARNING: less than reserve_s={self.budget.reserve_s:.0f}s left at train start; stopping after one step")

    def on_step_begin(self, args, state, control, **kwargs):
        self._step_started = self.clock()

    def on_step_end(self, args, state, control, **kwargs):
        now = self.clock()
        if self._step_started is not None:
            dt = now - self._step_started
            self._step_ema = dt if self._step_ema is None else 0.7 * self._step_ema + 0.3 * dt

        if self._signal:
            self._stop_reason = f"signal:{self._signal}"
        elif now + (self._step_ema or 0.0) + self.budget.reserve_s >= self.budget.deadline:
            self._stop_reason = "walltime"
        elif self.budget.stop_after_steps and state.global_step - (self._first_step or 0) >= self.budget.stop_after_steps:
            self._stop_reason = "step_limit"

        if self._stop_reason:
            control.should_save = True
            control.should_training_stop = True
            self._save_reason = self._stop_reason
        elif now - self._last_save >= self.budget.save_every_s:
            control.should_save = True
            self._save_reason = "interval"
        elif control.should_save:  # set by the trainer's own save_steps strategy
            self._save_reason = "save_steps"

        if control.should_save:
            self._save_requested_at = now
        return control

    def on_save(self, args, state, control, **kwargs):
        now = self.clock()
        save_s = now - self._save_requested_at if self._save_requested_at is not None else None
        self._last_save = now
        record = {
            "global_step": state.global_step,
            "max_steps": state.max_steps,
            "saved_at_epoch": now,
            "save_seconds": save_s,
            "reason": self._save_reason or "unknown",
            "step_seconds_ema": self._step_ema,
            "job_id": os.environ.get("PBS_JOBID"),
        }
        self.saves.append(record)
        ckpt = Path(args.output_dir) / f"checkpoint-{state.global_step}"
        if state.is_world_process_zero and ckpt.is_dir():
            _write_json(ckpt / COMPLETE_MARKER, record)
        self._save_requested_at = None
        self._save_reason = None
        return control

    def on_train_end(self, args, state, control, **kwargs):
        if not state.is_world_process_zero:
            return
        finished = state.max_steps > 0 and state.global_step >= state.max_steps
        status = {
            "status": "completed" if finished else "stopped",
            "stop_reason": None if finished else (self._stop_reason or "unknown"),
            "first_global_step": self._first_step,
            "global_step": state.global_step,
            "max_steps": state.max_steps,
            "step_seconds_ema": self._step_ema,
            "budget": asdict(self.budget),
            "ended_at_epoch": self.clock(),
            "saves": self.saves,
            "job_id": os.environ.get("PBS_JOBID"),
        }
        out_dir = self.status_dir or Path(args.output_dir)
        _write_json(out_dir / STATUS_FILE, status)
        if finished:
            _write_json(out_dir / TRAINING_DONE_MARKER, status)


def latest_complete_checkpoint(root: str | Path) -> Path | None:
    """Highest-step checkpoint under ``root`` (or one level below, for MS-SWIFT's
    versioned output folders) that carries the completion marker."""
    root = Path(root)
    if not root.is_dir():
        return None
    candidates: list[tuple[int, Path]] = []
    for parent in [root, *[p for p in root.iterdir() if p.is_dir()]]:
        for ckpt in parent.iterdir() if parent.is_dir() else ():
            m = _CHECKPOINT_RE.match(ckpt.name)
            if m and ckpt.is_dir() and (ckpt / COMPLETE_MARKER).is_file():
                candidates.append((int(m.group(1)), ckpt))
    return max(candidates, key=lambda c: c[0])[1] if candidates else None


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)
