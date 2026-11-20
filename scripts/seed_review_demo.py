"""Create or recreate the reviewer demo course (the API also creates it at startup).

    docker compose ... exec api python /srv/scripts/seed_review_demo.py ["Project name"]

Replaces the project of the same name; pass a name to seed a separate copy. The course and
the import of the trained reviewer's recorded findings live in app/core/review/demo.py.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

for candidate in (Path("/srv/api"), Path(__file__).resolve().parents[1] / "apps" / "api"):
    if (candidate / "app").is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.core.review.demo import DEFAULT_PROJECT_NAME, seed_review_demo  # noqa: E402

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"seeded project {seed_review_demo(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROJECT_NAME)}")
