"""
db_insert_paper.py — Insert a paper into bibliography and link to sources.

Usage:
    python src/db_insert_paper.py --project <name> --arxiv-id 2001.12345 \
        --title "..." --authors "Smith, Jones" --year 2020 \
        --relevance-notes "detected Lya nebula" --source-ids 1,3
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
    parser.add_argument("--arxiv-id", default=None)
    parser.add_argument("--doi", default=None)
    parser.add_argument("--title", default=None)
    parser.add_argument("--authors", default=None, help="Comma-separated author list")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--journal", default=None)
    parser.add_argument("--abstract", default=None)
    parser.add_argument("--relevance-notes", default=None)
    parser.add_argument("--source-ids", default=None, help="Comma-separated source IDs to link")
    args = parser.parse_args()

    authors = [a.strip() for a in args.authors.split(",")] if args.authors else None

    bib_id = db.insert_paper(
        project=args.project,
        arxiv_id=args.arxiv_id,
        doi=args.doi,
        title=args.title,
        authors=authors,
        year=args.year,
        journal=args.journal,
        abstract=args.abstract,
        relevance_notes=args.relevance_notes,
    )

    if args.source_ids:
        for sid in args.source_ids.split(","):
            db.link_source_paper(args.project, int(sid.strip()), bib_id, args.relevance_notes)

    print(json.dumps({"bib_id": bib_id, "linked_sources": args.source_ids}))
