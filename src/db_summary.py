"""
db_summary.py — Print project DB state summary as JSON.

Usage:
    python src/db_summary.py --project <name>
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
    args = parser.parse_args()

    summary = db.get_sample_summary(args.project)
    print(json.dumps(summary, indent=2))
