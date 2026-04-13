"""
db_query.py — Query DB tables and print results as JSON.

Usage:
    python src/db_query.py --project <name> --table sources --ids 1,2,3
    python src/db_query.py --project <name> --table sources --status candidate
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--table", required=True, choices=["sources", "bibliography", "reading_queue", "observations"])
    parser.add_argument("--ids", type=str, default=None, help="Comma-separated IDs")
    parser.add_argument("--status", type=str, default=None)
    args = parser.parse_args()

    if args.table == "sources":
        if args.ids:
            ids = [int(x) for x in args.ids.split(",")]
            results = [db.get_source(args.project, sid) for sid in ids]
            results = [r for r in results if r is not None]
        elif args.status:
            results = db.get_sources_by_status(args.project, args.status)
        else:
            results = db.get_all_sources(args.project)
    else:
        results = []

    print(json.dumps(results, indent=2))
