"""
compile_reading_list.py — Build a prioritized reading list from SIMBAD bibcodes.

Reads all bibcodes stored in source_bibcodes, fetches metadata from ADS, scores
by relevance to the literature focus keywords, deduplicates, and writes a
human-readable Markdown file for user review.

Usage:
    python src/compile_reading_list.py --project <name> --focus "<keywords>"

Output:
    projects/<project>/reading_queue.md   (written to disk)
    JSON summary printed to stdout: {total_bibcodes, high, medium, low, no_hits, path}
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db
import query_ads


def _priority(paper: dict, focus_keywords: list[str], source_count: int) -> str:
    """Return 'high', 'medium', or 'low' based on focus keyword match."""
    title = (paper.get("title") or "").lower()
    abstract = (paper.get("abstract") or "").lower()

    for kw in focus_keywords:
        if kw in title:
            return "high"

    for kw in focus_keywords:
        if kw in abstract:
            return "medium"

    if source_count >= 2:
        return "medium"

    return "low"


def _format_authors(authors: list) -> str:
    if not authors:
        return "Unknown"
    if len(authors) == 1:
        return authors[0].split(",")[0]
    return authors[0].split(",")[0] + " et al."


def _truncate_abstract(abstract: str | None, max_chars: int = 280) -> str:
    if not abstract:
        return "(no abstract available)"
    abstract = abstract.replace("\n", " ").strip()
    if len(abstract) <= max_chars:
        return abstract
    return abstract[:max_chars].rsplit(" ", 1)[0] + "..."


def _ads_fallback_bibcodes(
    sources: list[dict],
    focus_keywords: list[str],
) -> dict:
    """
    Query ADS fulltext for each source by name + focus keywords.
    Returns {bibcode: [source_id, ...]} for any found papers.
    Falls back silently if ADS_API_TOKEN is not set.
    """
    import os
    token = os.environ.get("ADS_API_TOKEN", "").strip()
    if not token:
        return {}

    bibcode_map: dict = {}
    for source in sources:
        name = source.get("name", "")
        if not name:
            continue
        try:
            bibcodes = query_ads.query_by_source_name(name, focus_keywords, token)
            for bcode in bibcodes:
                bibcode_map.setdefault(bcode, [])
                if source["id"] not in bibcode_map[bcode]:
                    bibcode_map[bcode].append(source["id"])
        except Exception:
            continue
    return bibcode_map


def run(project: str, focus: str) -> dict:
    db.ensure_schema(project)

    focus_keywords = [kw.strip().lower() for kw in focus.split(",") if kw.strip()]

    # {bibcode: [source_id, ...]}
    bibcode_map = db.get_bibcodes_for_project(project)

    # Detect whether SIMBAD bibcode extraction was actually run.
    # query_simbad_bibcodes.py records one entry per source if TAP is reachable;
    # if TAP was unreachable it returns early and records nothing.
    # n_sources > 0 and simbad_query_count == 0 → outage, not genuine "no literature".
    all_sources = {s["id"]: s for s in db.get_all_sources(project)}
    active_sources = [s for s in all_sources.values() if s["status"] != "rejected"]
    simbad_query_count = db.get_query_count(project, "simbad_bibcodes")
    simbad_failed = bool(active_sources) and simbad_query_count == 0

    if not bibcode_map:
        out_path = Path("projects") / project / "reading_queue.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if simbad_failed:
            # SIMBAD TAP was unreachable — attempt ADS name-based fallback
            print(
                json.dumps({"warning": "SIMBAD TAP unreachable; attempting ADS name-query fallback"}),
                file=sys.stderr,
            )
            bibcode_map = _ads_fallback_bibcodes(active_sources, focus_keywords)

        if not bibcode_map:
            simbad_status = (
                "WARNING: SIMBAD TAP was unreachable during bibcode extraction — "
                "literature check is INCOMPLETE. Re-run query_simbad_bibcodes.py when the "
                "service is restored, or ensure ADS_API_TOKEN is set for the ADS fallback."
                if simbad_failed
                else "No SIMBAD bibcodes found. All sources pass through as `inconclusive`."
            )
            out_path.write_text(
                f"# Reading Queue — {project}\nGenerated: {date.today()}\n\n"
                f"{simbad_status}\n"
            )
            result = {"total_bibcodes": 0, "high": 0, "medium": 0, "low": 0, "no_hits": 0,
                      "simbad_failed": simbad_failed, "path": str(out_path)}
            print(json.dumps(result))
            return result

    # Fetch ADS metadata in one batch
    bibcodes = list(bibcode_map.keys())
    papers = query_ads.run(bibcodes)
    paper_by_bcode = {p["bibcode"]: p for p in papers if p.get("bibcode")}

    # Score and group
    high, medium, low = [], [], []
    missing_bibcodes = []

    for bcode, source_ids in bibcode_map.items():
        paper = paper_by_bcode.get(bcode)
        if paper is None:
            missing_bibcodes.append((bcode, source_ids))
            continue

        source_count = len(source_ids)
        priority = _priority(paper, focus_keywords, source_count)

        # Build covers string
        covers_parts = []
        for sid in sorted(source_ids):
            src = all_sources.get(sid)
            if src:
                covers_parts.append(f"{src['name']} (z={src['z']:.2f})")
        covers = ", ".join(covers_parts) if covers_parts else "unknown sources"

        entry = {
            "bibcode": bcode,
            "paper": paper,
            "covers": covers,
            "source_ids": source_ids,
        }

        if priority == "high":
            high.append(entry)
        elif priority == "medium":
            medium.append(entry)
        else:
            low.append(entry)

    # Sort within tiers by citation count descending
    for tier in (high, medium, low):
        tier.sort(key=lambda e: e["paper"].get("citation_count") or 0, reverse=True)

    # Sources with no bibcodes
    sources_with_bibcodes = {sid for sids in bibcode_map.values() for sid in sids}
    no_hit_sources = [
        s for s in all_sources.values()
        if s["status"] != "rejected" and s["id"] not in sources_with_bibcodes
    ]

    # Write markdown
    out_path = Path("projects") / project / "reading_queue.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# Reading Queue — {project}",
        f"Generated: {date.today()}",
        "",
        f"Focus: {focus}",
        "Mark papers to read with [x]. Each paper appears once regardless of how many "
        "sources it covers. Save this file and tell the coordinator to proceed when done.",
        "",
        "---",
        "",
    ]

    def _render_entries(entries: list) -> list[str]:
        out = []
        for e in entries:
            p = e["paper"]
            authors_str = _format_authors(p.get("authors", []))
            year = p.get("year") or "????"
            title = p.get("title") or "(no title)"
            abstract_snippet = _truncate_abstract(p.get("abstract"))
            out.append(f"- [ ] {e['bibcode']} — {authors_str} ({year}) — \"{title}\"")
            out.append(f"  Covers: {e['covers']}")
            out.append(f"  Abstract: {abstract_snippet}")
            out.append("")
        return out

    if high:
        lines.append("## HIGH — focus keywords in title")
        lines.append("")
        lines.extend(_render_entries(high))

    if medium:
        lines.append("## MEDIUM — focus keywords in abstract or covers multiple sources")
        lines.append("")
        lines.extend(_render_entries(medium))

    if low:
        lines.append("## LOW — catalog papers and incidental mentions")
        lines.append("")
        lines.extend(_render_entries(low))

    if no_hit_sources or missing_bibcodes:
        lines.append("---")
        lines.append("")
        lines.append("## Sources with no SIMBAD bibliography")
        lines.append("")
        lines.append(
            "Not found in SIMBAD or had empty bibcode lists. "
            "Pass through with literature status: inconclusive."
        )
        lines.append("")
        for src in no_hit_sources:
            lines.append(f"- {src['name']} (z={src['z']:.2f})")
        if missing_bibcodes:
            lines.append("")
            lines.append("Bibcodes not found in ADS (metadata unavailable):")
            for bcode, sids in missing_bibcodes:
                src_names = ", ".join(
                    all_sources[s]["name"] for s in sids if s in all_sources
                )
                lines.append(f"- {bcode} — covers: {src_names}")

    out_path.write_text("\n".join(lines) + "\n")

    result = {
        "total_bibcodes": len(bibcode_map),
        "high": len(high),
        "medium": len(medium),
        "low": len(low),
        "no_hits": len(no_hit_sources),
        "path": str(out_path),
    }
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compile prioritized reading list from SIMBAD bibcodes"
    )
    parser.add_argument("--project", required=True)
    parser.add_argument(
        "--focus",
        required=True,
        help="Comma-separated focus keywords (e.g. 'extended Lya emission, Lya nebula')",
    )
    args = parser.parse_args()
    run(args.project, args.focus)
