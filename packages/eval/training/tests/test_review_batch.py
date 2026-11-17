"""LMS review requests must reach the reviewer in exactly the prompt format each task was
trained and evaluated with, or the adapter's measured behaviour does not apply."""
from __future__ import annotations

import pytest

from evaltrain.prompts import DISTRACTORS, GROUNDING, RUBRIC, chat
from evaltrain.review_batch import render
from evaltrain.tasks.oak import RUBRIC_TEXT


def test_grounding_request_uses_the_training_template():
    ex = render({"id": "D1|slide|s1", "task": "ragtruth_grounding", "fields": {"context": "Source.", "response": "Slide."}, "ref": {"asset_id": "D1"}})
    assert ex.messages == chat(GROUNDING.format(context="Source.", response="Slide."))
    assert (ex.id, ex.task, ex.target, ex.meta) == ("D1|slide|s1", "ragtruth_grounding", None, {"ref": {"asset_id": "D1"}})


def test_distractor_request_matches_the_oak_rendering():
    ex = render({"id": "Q1|question|0", "task": "oak_distractors", "fields": {"question": " When? ", "answer": "Within 1 hour", "distractors": ["Within 2 hours ", "Within a day"]}})
    expected = DISTRACTORS.format(rubric=RUBRIC_TEXT, question="When?", answer="Within 1 hour", distractors="- Within 2 hours\n- Within a day")
    assert ex.messages == chat(expected)


def test_rubric_request_fills_every_field():
    fields = {"instruction": "I", "response": "R", "reference": "F", "criteria": "C", **{f"score{i}": f"S{i}" for i in range(1, 6)}}
    ex = render({"id": "D1|rubric|depth", "task": "prometheus_rubric", "fields": fields})
    assert ex.messages == chat(RUBRIC.format(**fields))


@pytest.mark.parametrize(
    ("request_", "message"),
    [
        ({"id": "x", "task": "summarise", "fields": {}}, "unknown task"),
        ({"id": "x", "task": "ragtruth_grounding", "fields": {"context": "c"}}, "missing fields"),
        ({"id": "x", "task": "oak_distractors", "fields": {"question": "q", "answer": "a", "distractors": []}}, "missing fields"),
    ],
)
def test_malformed_requests_are_rejected(request_, message):
    with pytest.raises(ValueError, match=message):
        render(request_)


def test_a_released_bundle_names_its_own_base_and_refuses_lfs_pointers(tmp_path):
    import json

    from evaltrain.review_batch import reviewer_model

    bundle = tmp_path / "reviewer-main-27b-v1"
    bundle.mkdir()
    (bundle / "serving.json").write_text(json.dumps({"base_model": "Qwen/Qwen3.8-27B", "base_revision": "1d4bf0f2", "lora_rank": 16}))
    (bundle / "adapter_config.json").write_text("{}")
    (bundle / "adapter_model.safetensors").write_bytes(b"version https://git-lfs.github.com/spec/v1\noid sha256:00\nsize 467062560\n")
    with pytest.raises(SystemExit, match="Git LFS pointer"):
        reviewer_model(None, str(bundle))

    (bundle / "adapter_model.safetensors").write_bytes(b"\0" * 4096)
    assert reviewer_model(None, str(bundle)) == ({"id": "Qwen/Qwen3.8-27B", "revision": "1d4bf0f2"}, str(bundle), "reviewer-main-27b-v1", 16)
    assert reviewer_model(None, str(bundle), no_adapter=True)[1:3] == (None, None)


def test_the_cluster_config_still_selects_the_run_adapter(tmp_path, monkeypatch):
    from evaltrain import config as C
    from evaltrain.review_batch import reviewer_model

    adapter = tmp_path / "runs" / "main-27b-v1" / "adapter"
    adapter.mkdir(parents=True)
    (adapter / "adapter_config.json").write_text("{}")
    cfg = {"run_id": "main-27b-v1", "model": {"id": "Qwen/Qwen3.8-27B", "revision": "1d4bf0f2"}, "lora": {"rank": 16}}
    monkeypatch.setattr(C, "load", lambda path: cfg)
    monkeypatch.setattr(C, "run_dir", lambda c: adapter.parent)
    assert reviewer_model("configs/main_27b.yaml", None) == (cfg["model"], str(adapter), "main-27b-v1", 16)


def test_openai_backend_reviews_through_any_compatible_server(tmp_path, monkeypatch):
    """A stand-in model behind an OpenAI-compatible server (e.g. Ollama) gets the training
    prompts, and its findings are labelled with that model's name and no adapter."""
    import json

    from evaltrain import infer, review_batch

    replies = {"ragtruth_grounding": '{"issues": [{"span": "Slide.", "type": "evident_baseless", "implicit_true": false}]}',
               "prometheus_rubric": '{"feedback": "Covers the source.", "score": 4}', "oak_distractors": '{"score": 2}'}
    seen = []

    def generate(self, conversations, max_tokens, want_logprobs):
        seen.extend(conversations)
        task = "ragtruth_grounding" if "supported by the source" in conversations[0][-1]["content"] else "prometheus_rubric" if "score rubric" in conversations[0][-1]["content"] else "oak_distractors"
        return [infer.Generation(replies[task], [], [], None, None) for _ in conversations]

    monkeypatch.setattr(infer.OpenAIBackend, "generate", generate)
    rubric = {"instruction": "Teach X.", "response": "Slide 1: X", "reference": "X is Y.", "criteria": "Depth?", **{f"score{i}": f"level {i}" for i in range(1, 6)}}
    requests = [
        {"id": "D|slide|s1", "task": "ragtruth_grounding", "fields": {"context": "Source.", "response": "Slide."}, "ref": {"kind": "slide", "block": "s1"}},
        {"id": "D|rubric|depth", "task": "prometheus_rubric", "fields": rubric, "ref": {"kind": "rubric", "block": "depth"}},
        {"id": "Q|question|0", "task": "oak_distractors", "fields": {"question": "Q?", "answer": "A", "distractors": ["B", "C"]}, "ref": {"kind": "question", "block": "0"}},
    ]
    (tmp_path / "requests.jsonl").write_text("".join(json.dumps(r) + "\n" for r in requests), encoding="utf-8")
    out = tmp_path / "results.jsonl"
    review_batch.main(["--backend", "openai", "--base-url", "http://127.0.0.1:11434/v1", "--served-model", "qwen2.5:3b-instruct",
                       "--requests", str(tmp_path / "requests.jsonl"), "--out", str(out)])

    rows = {r["id"]: r for r in map(json.loads, out.read_text(encoding="utf-8").splitlines())}
    assert all(r["valid"] for r in rows.values()) and rows["D|slide|s1"]["ref"] == {"kind": "slide", "block": "s1"}
    assert rows["Q|question|0"]["parsed"] == {"score": 2}
    meta = json.loads((tmp_path / "results.jsonl.meta.json").read_text(encoding="utf-8"))["reviewer"]
    assert (meta["base_model"], meta["adapter"], meta["base_revision"]) == ("qwen2.5:3b-instruct", None, None)
    assert len(seen) == 3


def test_openai_backend_needs_a_server_and_takes_no_adapter_options(capsys):
    from evaltrain import review_batch

    with pytest.raises(SystemExit):
        review_batch.main(["--backend", "openai", "--requests", "r.jsonl", "--out", "o.jsonl"])
    assert "--base-url and --served-model" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        review_batch.main(["--backend", "openai", "--base-url", "http://x/v1", "--served-model", "m", "--adapter-dir", "d", "--requests", "r", "--out", "o"])
    assert "drop --config and --adapter-dir" in capsys.readouterr().err
