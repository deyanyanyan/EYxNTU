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
    ap.add_argument("--output", type=Path, default=TARGET, help="alternate output file for configuration-generation checks")
    args = ap.parse_args()
    target = args.output.resolve()

    if target.exists() and not args.force:
        print(f"{target} already exists; keeping its credentials. Continue with the startup command.")
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
        # Only the inference container uses the GPU. API/worker images use CPU torch.
        text = set_var(text, "EMBEDDING_DEVICE", "cpu")

    target.write_text(text, encoding="utf-8")
    print(f"wrote {target} (profile={args.profile})")
    print("Read DEFAULT_ADMIN_EMAIL and DEFAULT_ADMIN_PASSWORD in that file to sign in.")
    print("Keep this file private. Existing database users are not changed by regenerating it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
