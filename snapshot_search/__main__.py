"""Build, activate, query, and inspect local document generations."""

import argparse
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from . import ActivationConflict, Citation, Document, SearchIndex


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("corpus", type=Path, help="JSON array of doc_id/title/body objects")
    activate = commands.add_parser("activate")
    activate.add_argument("generation", type=int)
    activate.add_argument("--expected", required=True, help="current generation, or none")
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--generation", type=int)
    search.add_argument("--limit", type=int, default=5)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("generation", type=int)
    resolve.add_argument("doc_id")
    resolve.add_argument("digest")
    commands.add_parser("status")
    args = parser.parse_args()
    try:
        index = SearchIndex(args.db)
        if args.command == "build":
            payload = json.loads(args.corpus.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("corpus must be a JSON array")
            result = asdict(index.build(Document(**item) for item in payload))
        elif args.command == "activate":
            expected = None if args.expected == "none" else int(args.expected)
            index.activate(args.generation, expected_active=expected)
            result = {"activated_generation": args.generation}
        elif args.command == "search":
            result = asdict(index.search(args.query, generation=args.generation, limit=args.limit))
        elif args.command == "resolve":
            result = asdict(index.resolve(Citation(args.generation, args.doc_id, args.digest)))
        else:
            result = {"active": index.active_generation(),
                      "generations": [asdict(g) for g in index.generations()]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, TypeError, LookupError, ActivationConflict, OSError, sqlite3.Error) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
