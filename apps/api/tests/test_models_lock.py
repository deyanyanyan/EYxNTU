"""scripts/models.py: a base-model lock taken from the Hugging Face Hub listing must match
what `verify` later sees in a local download, without the weights ever being fetched."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import urllib.parse
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
# /srv/scripts in the api image, <repo>/scripts in a checkout
_SCRIPT = next(p for p in (_HERE.parents[2] / "scripts" / "models.py", _HERE.parents[3] / "scripts" / "models.py") if p.is_file())
_spec = importlib.util.spec_from_file_location("models_lock", _SCRIPT)
models = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(models)

REV = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
FILES = {
    "config.json": b'{"model_type": "toy"}\n',
    "tokenizer/vocab.json": b'{"a": 1}\n',
    "model.safetensors": b"\x00\x01" * 64,  # stored in LFS on the Hub
}


class _Response(io.BytesIO):
    def __init__(self, body: bytes, link: str = ""):
        super().__init__(body)
        self.headers = {"Link": link} if link else {}


def _fake_hub():
    """The Hub's tree API split over two pages, plus the resolve endpoint for small files."""
    entries = [{"type": "directory", "path": "tokenizer"}]
    for path, body in FILES.items():
        entry = {"type": "file", "path": path, "size": len(body)}
        if path.endswith(".safetensors"):
            entry["lfs"] = {"oid": hashlib.sha256(body).hexdigest(), "size": len(body)}
        entries.append(entry)
    tree = f"https://huggingface.co/api/models/acme/toy/tree/{REV}?recursive=true"
    requested: list[str] = []

    def opener(url: str):
        requested.append(url)
        if url == tree:
            return _Response(json.dumps(entries[:2]).encode(), link=f'<{tree}&cursor=2>; rel="next"')
        if url == f"{tree}&cursor=2":
            return _Response(json.dumps(entries[2:]).encode())
        path = urllib.parse.unquote(url.split(f"/acme/toy/resolve/{REV}/", 1)[1])
        return _Response(FILES[path])

    return opener, requested


def _download(models_dir: Path) -> Path:
    snapshot = models.snapshot_dir(models_dir, "acme/toy", REV)
    for path, body in FILES.items():
        (snapshot / path).parent.mkdir(parents=True, exist_ok=True)
        (snapshot / path).write_bytes(body)
    return snapshot


def test_hub_listing_matches_a_local_download_without_fetching_weights(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    opener, requested = _fake_hub()
    assert models.describe_hub("acme/toy", REV, opener=opener) == models.describe(_download(tmp_path))
    assert not any(url.endswith(".safetensors") for url in requested)


def test_lock_from_hub_then_verify_the_downloaded_bundle(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.setattr(models, "hub_open", _fake_hub()[0])
    models_dir, lock, env = tmp_path / "models", tmp_path / "models.lock.json", tmp_path / ".env"
    adapter = models_dir / "adapters" / "reviewer-toy"
    adapter.mkdir(parents=True)
    (adapter / "serving.json").write_text(json.dumps({"base_model": "acme/toy", "base_revision": REV}))
    (adapter / "adapter_model.safetensors").write_bytes(b"lora")
    common = ["--models-dir", str(models_dir), "--lock", str(lock)]

    assert models.main([*common, "lock", "--hub", "--base", f"acme/toy@{REV}", "--adapter", "reviewer-toy"]) == 0
    record = json.loads(lock.read_text(encoding="utf-8"))
    assert record["base_models"][0]["checksums_from"] == "hub" and set(record["adapters"][0]["files"]) == {"serving.json", "adapter_model.safetensors"}

    assert models.main([*common, "verify", "--env", str(env)]) == 1  # the base is not downloaded yet
    snapshot = _download(models_dir)
    assert models.main([*common, "verify", "--env", str(env)]) == 0
    (snapshot / "config.json").write_bytes(b'{"model_type": "tampered"}\n')
    assert models.main([*common, "verify", "--env", str(env)]) == 1


def test_verify_names_a_skipped_lfs_file(tmp_path):
    folder = tmp_path / "adapters" / "reviewer-toy"
    folder.mkdir(parents=True)
    pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"0" * 64 + b"\nsize 467062560\n"
    (folder / "adapter_model.safetensors").write_bytes(pointer)
    problems = models.compare(folder, {"adapter_model.safetensors": {"bytes": 467062560, "sha256": "0" * 64}}, "adapter reviewer-toy", quick=False)
    assert len(problems) == 1 and "Git LFS pointer" in problems[0] and "git lfs pull" in problems[0]


def test_hub_lock_refuses_a_moving_revision(tmp_path):
    with pytest.raises(SystemExit, match="commit hash"):
        models.main(["--models-dir", str(tmp_path), "--lock", str(tmp_path / "lock.json"), "lock", "--hub", "--base", "acme/toy@main"])
