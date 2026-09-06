#!/usr/bin/env python3
"""Create a local .env from .env.example with fresh secrets.

Usage:  python scripts/gen_env.py [--force] [--profile cpu|gpu]
"""
import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"
TARGET = ROOT / ".env"


def set_var(text: str, key: str, value: str) -> str:
    lines = []
    found = False
    for line in text.splitlines():
        if line.startswith(f"{key}="):
            lines.append(f"{key}={value}")
            found = True
        else:
            lines.append(line)
    if not found:
        print(f"warning: {key} not found in .env.example; appending")
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="overwrite existing .env")
    ap.add_argument("--profile", choices=["cpu", "gpu"], default="cpu")
    args = ap.parse_args()

    if TARGET.exists() and not args.force:
        print(f"{TARGET} already exists. Use --force to overwrite.")
        return 1

    text = EXAMPLE.read_text(encoding="utf-8")
    pg_pw = secrets.token_urlsafe(16)
    admin_pw = secrets.token_urlsafe(12)

    text = set_var(text, "SECRET_KEY", secrets.token_urlsafe(48))
    text = set_var(text, "POSTGRES_PASSWORD", pg_pw)
    text = set_var(text, "DATABASE_URL", f"postgresql+psycopg://lms:{pg_pw}@postgres:5432/lms")
    text = set_var(text, "DEFAULT_ADMIN_PASSWORD", admin_pw)
    text = set_var(text, "COMPOSE_PROFILES", args.profile)

    if args.profile == "gpu":
        text = set_var(text, "LLM_BASE_URL", "http://inference:8000/v1")
        text = set_var(text, "LLM_MODEL", "Qwen/Qwen3-32B-AWQ")
        text = set_var(text, "EMBEDDING_DEVICE", "cuda")
        text = set_var(text, "TTS_ENGINE", "kokoro")
        text = set_var(text, "TTS_VOICE", "af_heart")

    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET} (profile={args.profile})")
    print("admin email:    admin@lms.local")
    print(f"admin password: {admin_pw}   (change it after first login)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
