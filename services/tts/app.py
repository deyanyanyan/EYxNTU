"""Minimal OpenAI-compatible TTS server (`POST /v1/audio/speech`).

Engines:
  piper  - fast CPU neural TTS (default). Voices are .onnx files in /models/piper.
  kokoro - higher quality, GPU recommended. Uses the `kokoro` package.

Both run fully offline once the voice files are present. The worker calls this
service through TTS_BASE_URL and never depends on which engine is behind it.
"""
from __future__ import annotations

import io
import os
import wave
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

ENGINE = os.environ.get("TTS_ENGINE", "piper")
MODEL_DIR = Path(os.environ.get("TTS_MODEL_DIR", "/models"))
DEFAULT_VOICE = os.environ.get("TTS_VOICE", "en_US-lessac-medium")

app = FastAPI(title="lms-tts", version="0.1.0")


class SpeechRequest(BaseModel):
    input: str
    voice: str | None = None
    model: str | None = None  # ignored; kept for OpenAI-client compatibility
    response_format: str = "wav"
    speed: float = 1.0


@app.get("/health")
def health():
    return {"status": "ok", "engine": ENGINE, "default_voice": DEFAULT_VOICE}


@app.post("/v1/audio/speech")
def speech(req: SpeechRequest):
    voice = req.voice or DEFAULT_VOICE
    text = req.input.strip()
    if not text:
        raise HTTPException(status_code=400, detail="input is empty")
    if ENGINE == "piper":
        audio = _piper(text, voice, req.speed)
    elif ENGINE == "kokoro":
        audio = _kokoro(text, voice, req.speed)
    else:
        raise HTTPException(status_code=500, detail=f"unknown TTS_ENGINE {ENGINE}")
    return Response(content=audio, media_type="audio/wav")


def _piper(text: str, voice: str, speed: float) -> bytes:
    try:
        from piper import PiperVoice
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="piper-tts not installed") from exc
    model_path = MODEL_DIR / "piper" / f"{voice}.onnx"
    if not model_path.exists():
        raise HTTPException(status_code=404, detail=f"voice not found: {model_path}")
    v = PiperVoice.load(str(model_path))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        v.synthesize(text, wf, length_scale=1.0 / max(speed, 0.1))
    return buf.getvalue()


def _kokoro(text: str, voice: str, speed: float) -> bytes:
    try:
        import numpy as np
        import soundfile as sf
        from kokoro import KPipeline
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="kokoro not installed") from exc
    pipe = KPipeline(lang_code=voice[0] if voice else "a")
    chunks = [audio for _, _, audio in pipe(text, voice=voice, speed=speed)]
    audio = np.concatenate(chunks) if chunks else np.zeros(1, dtype="float32")
    buf = io.BytesIO()
    sf.write(buf, audio, 24000, format="WAV")
    return buf.getvalue()
