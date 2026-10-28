"""Command line for the batch review round trip (run inside the api container).

    python -m app.core.review export --project <id> --out /data/artifacts/review/<id>/requests.jsonl
    python -m app.core.review import --project <id> --results /data/artifacts/review/<id>/results.jsonl

``export`` also writes ``<out>.manifest.json`` (plan and asset versions); ``import`` reads
it from beside the requests file to mark findings stale for assets edited since export.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.review.export import build_requests
from app.core.review.importer import import_results
from app.db.session import session_scope


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="write review requests for a project's course")
    ex.add_argument("--project", required=True)
    ex.add_argument("--out", required=True)
    im = sub.add_parser("import", help="attach reviewer results to the reviewed assets")
    im.add_argument("--project", required=True)
    im.add_argument("--results", required=True)
    im.add_argument("--manifest", help="requests manifest (default: requests.jsonl.manifest.json beside the results)")
    args = ap.parse_args(argv)

    with session_scope() as db:
        if args.cmd == "export":
            requests, manifest = build_requests(db, args.project)
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requests), encoding="utf-8")
            out.with_suffix(out.suffix + ".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            kinds = {k: sum(r["ref"]["kind"] == k for r in requests) for k in ("slide", "rubric", "question")}
            print(json.dumps({"out": str(out), "requests": len(requests), **kinds}))
        else:
            results = Path(args.results)
            manifest = Path(args.manifest) if args.manifest else results.with_name("requests.jsonl.manifest.json")
            print(json.dumps(import_results(db, args.project, results, manifest=manifest)))


if __name__ == "__main__":
    main()
