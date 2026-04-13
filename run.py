"""
run.py — CosmicWebCrawler pipeline entry point.

Usage:
    python run.py --project <name> --stage <sample|archive|reduce|analyze>
    python run.py --project cosmos-pilot --stage sample --dry-run

The --dry-run flag initializes the DB schema and exits. Stage coordinators are
Claude agents spawned by the harness; this script handles initialization and
state reporting only.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
import db

STAGE_COORDINATORS = {
    "sample": "sample-coordinator",
    "archive": "archive-coordinator",
    "reduce": "reduction-coordinator",
    "analyze": "analysis-coordinator",
}


def main():
    parser = argparse.ArgumentParser(description="CosmicWebCrawler pipeline runner")
    parser.add_argument("--project", required=True, help="Project namespace")
    parser.add_argument(
        "--stage",
        required=True,
        choices=list(STAGE_COORDINATORS.keys()),
        help="Pipeline stage to run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Initialize DB schema and exit without running the stage",
    )
    args = parser.parse_args()

    # Ensure project directory and DB schema exist
    db.ensure_schema(args.project)

    # Load and validate science config if present
    config_path = Path("projects") / args.project / "science_config.json"
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
        print(f"Project : {args.project}")
        print(f"Field   : RA={config['field']['ra']}, Dec={config['field']['dec']}, r={config['field']['radius_deg']} deg")
        print(f"Redshift: z={config['redshift']['z_min']}–{config['redshift']['z_max']}")
        print(f"Science : {config.get('science_goal', '(no goal specified)')}")
    else:
        print(f"Project : {args.project}")
        print(f"Warning : no science_config.json found at {config_path}")

    # Print DB state
    summary = db.get_sample_summary(args.project)
    print(f"\nDB state ({args.project}.db):")
    print(f"  Sources       : {summary['total_sources']}")
    print(f"  By status     : {summary['by_status']}")
    print(f"  Observations  : {summary['total_observations']}")
    print(f"  Bibliography  : {summary['total_bibliography']}")
    print(f"  Queue pending : {summary['reading_queue_pending']}")

    if args.dry_run:
        print(f"\nDry-run complete. DB initialized for stage '{args.stage}'.")
        print(f"Coordinator: {STAGE_COORDINATORS[args.stage]}")
        return 0

    print(f"\nStage '{args.stage}' ready. Spawn coordinator: {STAGE_COORDINATORS[args.stage]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
