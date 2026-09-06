# TTS service

OpenAI-compatible `/v1/audio/speech` wrapper so the worker can call any engine through one URL.

## Voices (download once, then offline)
- **Piper** (cpu profile): place `en_US-lessac-medium.onnx` and `.onnx.json` in `data/models/tts/piper/`.
  Voices: https://github.com/rhasspy/piper/blob/master/VOICES.md
- **Kokoro** (gpu profile): `pip install kokoro soundfile`; weights are fetched to `HF_HOME` on first run.
  Set `TTS_ENGINE=kokoro` and `TTS_VOICE=af_heart`.

## Smoke test
```bash
curl -s -X POST http://localhost:8880/v1/audio/speech \
  -H 'content-type: application/json' \
  -d '{"input":"Welcome to lesson one.","voice":"en_US-lessac-medium"}' -o hello.wav
```
