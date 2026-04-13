"""
db_enqueue.py — Add a paper to the reading queue.

Usage:
    python src/db_enqueue.py --project <name> --ref arxiv:2001.12345 \
        --reason "cites source J1234+5678" --recommended-by "literature-agent" \
        --source-ids 1,3 --citation-depth 1 --priority 0.6
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
    parser.add_argument("--ref", required=True, help="arXiv ID, DOI, or URL")
    parser.add_argument("--reason", default=None)
    parser.add_argument("--recommended-by", default=None)
    parser.add_argument("--source-ids", default=None, help="Comma-separated source IDs")
    parser.add_argument("--citation-depth", type=int, default=0)
    parser.add_argument("--priority", type=float, default=0.5)
    args = parser.parse_args()

    source_ids = [int(x.strip()) for x in args.source_ids.split(",")] if args.source_ids else []

    queue_id = db.enqueue_paper(
        project=args.project,
        ref=args.ref,
        reason=args.reason,
        recommended_by=args.recommended_by,
        source_ids=source_ids,
        citation_depth=args.citation_depth,
        priority=args.priority,
    )

    print(json.dumps({"queue_id": queue_id, "ref": args.ref}))
