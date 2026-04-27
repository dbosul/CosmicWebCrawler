"""
query_simbad_bibcodes.py — Extract SIMBAD bibliographies for all sources in the DB.

For each non-rejected source, performs a 3-arcsec cone search on SIMBAD TAP and
retrieves all associated bibcodes from the has_ref join. Results are stored in
the source_bibcodes table. Uses query_history for deduplication (skips sources
already queried).

Sources not found in SIMBAD are silently skipped — this is expected (~30% of
SDSS sources) and means they have no prior literature, which is low-risk.

Usage:
    python src/query_simbad_bibcodes.py --project <name>
    python src/query_simbad_bibcodes.py --project <name> --source-ids 1,2,3
"""

import argparse
import csv
import io
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
import db
from query_simbad import SIMBAD_TAP_URL

# 3 arcsec in degrees
_CONE_DEG = 3.0 / 3600.0


def _fetch_bibcodes_for_source(ra: float, dec: float) -> list[str]:
    """
    Query SIMBAD TAP for bibcodes of any object within 3 arcsec of (ra, dec).
    Returns list of bibcode strings (may be empty).

    No otype filter: position-only matching is used. An otype filter would miss sources
    whose primary SIMBAD classification is non-AGN (e.g. X-ray source, radio source,
    emission-line galaxy) even when they have substantial AGN/Lya literature.

    Schema note: has_ref stores oidbibref (internal int), not the bibcode string directly.
    Must JOIN to the ref table on ref.oidbib = has_ref.oidbibref to get bibcode strings.
    """
    adql = f"""
        SELECT r.bibcode
        FROM basic AS b
        JOIN has_ref AS hr ON hr.oidref = b.oid
        JOIN ref AS r ON r.oidbib = hr.oidbibref
        WHERE CONTAINS(
            POINT('ICRS', b.ra, b.dec),
            CIRCLE('ICRS', {ra}, {dec}, {_CONE_DEG})
        ) = 1
    """
    try:
        resp = requests.get(
            SIMBAD_TAP_URL,
            params={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": adql},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return []

    text = resp.text.strip()
    if not text or text.lower().startswith("error") or "bibcode" not in text.lower():
        return []

    rows = list(csv.DictReader(io.StringIO(text)))
    return [r["bibcode"].strip() for r in rows if r.get("bibcode", "").strip()]


def _simbad_tap_reachable(timeout: float = 5.0) -> bool:
    """Quick connectivity probe — avoids 30s-per-source timeouts if TAP is down."""
    try:
        resp = requests.get(
            SIMBAD_TAP_URL,
            params={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv",
                    "QUERY": "SELECT TOP 1 oid FROM basic"},
            timeout=timeout,
        )
        return resp.status_code == 200
    except Exception:
        return False


def run(project: str, source_ids: list[int] | None = None) -> dict:
    db.ensure_schema(project)

    # Probe connectivity before iterating over hundreds of sources
    if not _simbad_tap_reachable():
        out = {
            "sources_checked": 0,
            "sources_matched": 0,
            "total_bibcodes": 0,
            "new_bibcodes": 0,
            "skipped": "SIMBAD TAP unreachable — all sources treated as inconclusive",
        }
        print(json.dumps(out))
        return out

    if source_ids:
        sources = [s for s in db.get_all_sources(project) if s["id"] in source_ids]
    else:
        # All non-rejected sources
        sources = [s for s in db.get_all_sources(project) if s["status"] != "rejected"]

    sources_checked = 0
    sources_matched = 0
    total_bibcodes = 0
    new_bibcodes = 0

    for source in sources:
        sid = source["id"]
        ra = source["ra"]
        dec = source["dec"]

        params = {"database": "simbad_bibcodes", "source_id": sid}
        if db.has_been_queried(project, "simbad_bibcodes", params):
            continue

        sources_checked += 1
        bibcodes = _fetch_bibcodes_for_source(ra, dec)

        if bibcodes:
            sources_matched += 1
            total_bibcodes += len(bibcodes)
            for bcode in bibcodes:
                # Check if this is genuinely new before inserting (for count accuracy)
                existing = db.get_bibcodes_for_project(project)
                already_linked = sid in existing.get(bcode, [])
                db.insert_source_bibcode(project, sid, bcode)
                if not already_linked:
                    new_bibcodes += 1

        db.record_query(project, "simbad_bibcodes", params, result_count=len(bibcodes))

        # Be polite to SIMBAD TAP
        time.sleep(0.2)

    out = {
        "sources_checked": sources_checked,
        "sources_matched": sources_matched,
        "total_bibcodes": total_bibcodes,
        "new_bibcodes": new_bibcodes,
    }
    print(json.dumps(out))
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract SIMBAD bibcodes for sources in the DB"
    )
    parser.add_argument("--project", required=True)
    parser.add_argument(
        "--source-ids",
        default=None,
        help="Comma-separated source IDs (default: all non-rejected)",
    )
    args = parser.parse_args()

    ids = (
        [int(x.strip()) for x in args.source_ids.split(",")]
        if args.source_ids
        else None
    )
    run(args.project, source_ids=ids)
