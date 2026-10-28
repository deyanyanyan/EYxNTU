"""Stop/resume equivalence on a tiny CPU model.

An interrupted run (stopped by the walltime callback) followed by a resumed run must
reproduce an uninterrupted run: same per-step losses, same learning-rate schedule,
same final adapter weights. Checking only the global step would not prove that the
optimizer, scheduler, RNG and data order were restored.
"""
from __future__ import annotations

import json

import pytest

torch = pytest.importorskip("torch")
peft = pytest.importorskip("peft")
transformers = pytest.importorskip("transformers")

from transformers import Qwen2Config, Qwen2ForCausalLM, Trainer, TrainerCallback, TrainingArguments  # noqa: E402

from evaltrain.callbacks import (  # noqa: E402
    COMPLETE_MARKER,
    STATUS_FILE,
    TRAINING_DONE_MARKER,
    WalltimeBudget,
    WalltimeCheckpointCallback,
    latest_complete_checkpoint,
)

MAX_STEPS = 12


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class AdvanceClock(TrainerCallback):
    """Each optimizer step 'takes' 100 s. Registered before the walltime callback."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock

    def on_step_end(self, args, state, control, **kwargs):
        self.clock.t += 100.0


class Recorder(TrainerCallback):
    def __init__(self) -> None:
        self.loss: dict[int, float] = {}
        self.lr: dict[int, float] = {}

    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs and "loss" in logs:
            self.loss[state.global_step] = logs["loss"]
            self.lr[state.global_step] = logs["learning_rate"]


class ToyData(torch.utils.data.Dataset):
    def __init__(self, n: int = 40, length: int = 16, vocab: int = 128) -> None:
        g = torch.Generator().manual_seed(7)
        self.x = torch.randint(3, vocab, (n, length), generator=g)

    def __len__(self) -> int:
        return len(self.x)

    def __getitem__(self, i):
        ids = self.x[i]
        return {"input_ids": ids, "attention_mask": torch.ones_like(ids), "labels": ids.clone()}


@pytest.fixture(scope="module")
def base_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp("tiny_base")
    torch.manual_seed(0)
    cfg = Qwen2Config(
        vocab_size=128, hidden_size=32, intermediate_size=64, num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2,
        max_position_embeddings=64, attention_dropout=0.0, tie_word_embeddings=False,
    )
    Qwen2ForCausalLM(cfg).save_pretrained(path)
    return path


def make_trainer(base_dir, out_dir, callbacks):
    model = Qwen2ForCausalLM.from_pretrained(base_dir)
    torch.manual_seed(1234)  # LoRA A is drawn from the global RNG before Trainer seeds it
    lora = peft.LoraConfig(r=4, lora_alpha=8, lora_dropout=0.0, target_modules=["q_proj", "k_proj", "v_proj", "o_proj"], task_type="CAUSAL_LM")
    model = peft.get_peft_model(model, lora)
    args = TrainingArguments(
        output_dir=str(out_dir), max_steps=MAX_STEPS, per_device_train_batch_size=2, gradient_accumulation_steps=2,
        learning_rate=5e-3, lr_scheduler_type="cosine", warmup_steps=2, logging_steps=1, save_strategy="no",
        report_to=[], seed=123, data_seed=123, use_cpu=True, dataloader_num_workers=0, disable_tqdm=True,
    )
    return Trainer(model=model, args=args, train_dataset=ToyData(), callbacks=callbacks)


def lora_state(trainer) -> dict:
    return {k: v.detach().clone() for k, v in trainer.model.state_dict().items() if "lora_" in k}


def test_interrupted_run_resumes_exactly(base_dir, tmp_path):
    # Reference: one uninterrupted run.
    ref_rec = Recorder()
    ref = make_trainer(base_dir, tmp_path / "ref", [ref_rec])
    ref.train()
    ref_weights = lora_state(ref)

    # Job 1: deadline at t=600 s with 100 s steps -> projected overrun after step 5.
    clock = FakeClock()
    budget = WalltimeBudget(deadline=600.0, reserve_s=0.0, save_every_s=1e9)
    rec1 = Recorder()
    out = tmp_path / "run"
    job1 = make_trainer(base_dir, out, [AdvanceClock(clock), WalltimeCheckpointCallback(budget, clock=clock, install_signal_handlers=False), rec1])
    job1.train()

    ckpt = latest_complete_checkpoint(out)
    assert ckpt is not None and ckpt.name == "checkpoint-5"
    for name in ("optimizer.pt", "scheduler.pt", "trainer_state.json", COMPLETE_MARKER):
        assert (ckpt / name).is_file(), name
    assert any(p.name.startswith("rng_state") for p in ckpt.iterdir())
    status = json.loads((out / STATUS_FILE).read_text())
    assert status["status"] == "stopped" and status["stop_reason"] == "walltime" and status["global_step"] == 5
    assert not (out / TRAINING_DONE_MARKER).exists()

    # Job 2: fresh process state, generous budget, resume from the marked checkpoint.
    rec2 = Recorder()
    job2_cb = WalltimeCheckpointCallback(WalltimeBudget(deadline=1e12, reserve_s=0.0, save_every_s=1e9), install_signal_handlers=False)
    job2 = make_trainer(base_dir, out, [job2_cb, rec2])
    job2.train(resume_from_checkpoint=str(ckpt))

    assert job2.state.global_step == MAX_STEPS
    assert min(rec2.loss) == 6, "resumed job must continue at step 6, not restart"
    for step in range(6, MAX_STEPS + 1):
        assert rec2.lr[step] == pytest.approx(ref_rec.lr[step], rel=1e-9), f"lr diverged at step {step}"
        assert rec2.loss[step] == pytest.approx(ref_rec.loss[step], rel=1e-4, abs=1e-6), f"loss diverged at step {step}"
    for step in range(1, 6):
        assert rec1.loss[step] == pytest.approx(ref_rec.loss[step], rel=1e-4, abs=1e-6)

    resumed = lora_state(job2)
    assert resumed.keys() == ref_weights.keys()
    for k in ref_weights:
        assert torch.allclose(resumed[k], ref_weights[k], atol=1e-5), k
    assert json.loads((out / TRAINING_DONE_MARKER).read_text())["global_step"] == MAX_STEPS


def test_latest_checkpoint_skips_incomplete(tmp_path):
    (tmp_path / "checkpoint-3").mkdir()
    (tmp_path / "checkpoint-3" / COMPLETE_MARKER).write_text("{}")
    (tmp_path / "checkpoint-9").mkdir()  # interrupted mid-write: no marker
    nested = tmp_path / "v0-20261027-120000" / "checkpoint-6"
    nested.mkdir(parents=True)
    (nested / COMPLETE_MARKER).write_text("{}")
    assert latest_complete_checkpoint(tmp_path) == nested
    assert latest_complete_checkpoint(tmp_path / "missing") is None


def test_step_limit_counts_steps_in_this_job_only():
    cb = WalltimeCheckpointCallback(WalltimeBudget(deadline=1e12, stop_after_steps=3), install_signal_handlers=False)

    class C:
        should_save = False
        should_training_stop = False

    class S:
        global_step = 10  # resumed job: counting starts here, not at zero

    cb.on_train_begin(None, S(), C())
    for step in (11, 12):
        S.global_step = step
        assert not cb.on_step_end(None, S(), C()).should_training_stop
    S.global_step = 13
    control = cb.on_step_end(None, S(), C())
    assert control.should_save and control.should_training_stop and cb._stop_reason == "step_limit"
    env = WalltimeBudget(deadline=5.0, stop_after_steps=3).to_env()
    assert env["EVALTRAIN_STOP_AFTER_STEPS"] == "3"


def test_signal_requests_save_and_stop():
    import signal

    cb = WalltimeCheckpointCallback(WalltimeBudget(deadline=1e12), install_signal_handlers=False)
    cb._on_signal(signal.SIGTERM, None)

    class C:
        should_save = False
        should_training_stop = False

    class S:
        global_step = 1

    control = cb.on_step_end(None, S(), C())
    assert control.should_save and control.should_training_stop
