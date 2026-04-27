"""
query_ads.py — Query the NASA ADS API for paper metadata and body-text snippets.

Two modes:

  Metadata mode (default) — batch lookup by bibcode list:
    python src/query_ads.py --bibcodes "2021ApJ...912...54C,2020MNRAS.495.1847S"

  Snippet mode — body-text highlights for a specific source name:
    python src/query_ads.py --bibcodes "2021ApJ...912...54C" \\
        --source-name "J1425+3254" --snippets

Requires ADS_API_TOKEN environment variable. Without it, falls back to the arXiv
API for title+abstract metadata only (no snippet support).

Output: JSON list of paper dicts, one per bibcode.
Each dict: {bibcode, title, authors, year, abstract, citation_count, arxiv_id, snippets}
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path


ADS_SEARCH_URL = "https://api.adsabs.harvard.edu/v1/search/query"
ARXIV_API_URL = "http://export.arxiv.org/api/query"


def _ads_request(params: dict, token: str) -> dict:
    """Make a GET request to ADS search API. Returns parsed JSON or raises."""
    url = ADS_SEARCH_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _arxiv_id_from_identifiers(identifiers: list) -> str | None:
    """Extract arXiv ID from ADS identifier list (e.g. ['arxiv:2103.01234', ...])."""
    for ident in identifiers or []:
        s = str(ident).lower()
        if s.startswith("arxiv:"):
            return s[6:]  # strip "arxiv:" prefix
    return None


def query_metadata(bibcodes: list[str], token: str) -> list[dict]:
    """
    Batch fetch metadata for a list of bibcodes from ADS.
    Returns list of paper dicts in the same order as input (missing bibcodes omitted).
    """
    if not bibcodes:
        return []

    # ADS bibcode query: OR-join with bibcode: prefix
    q = " OR ".join(f"bibcode:{b}" for b in bibcodes)
    params = {
        "q": q,
        "fl": "bibcode,title,author,year,abstract,citation_count,identifier",
        "rows": len(bibcodes),
    }

    data = _ads_request(params, token)
    docs = data.get("response", {}).get("docs", [])

    results = []
    for doc in docs:
        title = doc.get("title", [None])[0] if doc.get("title") else None
        results.append({
            "bibcode": doc.get("bibcode"),
            "title": title,
            "authors": doc.get("author", []),
            "year": doc.get("year"),
            "abstract": doc.get("abstract"),
            "citation_count": doc.get("citation_count", 0),
            "arxiv_id": _arxiv_id_from_identifiers(doc.get("identifier", [])),
            "snippets": [],
        })
    return results


def query_snippets(bibcode: str, source_name: str, token: str) -> list[str]:
    """
    Return body-text highlight snippets for a single bibcode + source name.
    Returns list of snippet strings (may be empty if source not mentioned in body).
    """
    q = f'bibcode:{bibcode} AND full:"{source_name}"'
    params = {
        "q": q,
        "fl": "bibcode",
        "hl": "true",
        "hl.fl": "body",
        "hl.snippets": "3",
        "hl.fragsize": "300",
        "rows": "1",
    }

    data = _ads_request(params, token)
    highlighting = data.get("highlighting", {})
    for _bcode, fields in highlighting.items():
        body_snippets = fields.get("body", [])
        return [s.strip() for s in body_snippets if s.strip()]
    return []


def query_by_source_name(
    source_name: str,
    focus_keywords: list[str],
    token: str,
    max_results: int = 10,
) -> list[str]:
    """
    Search ADS fulltext for papers that mention a source by name AND contain
    at least one focus keyword (e.g. "Lyman-alpha", "nebula", "IFU").

    This supplements the SIMBAD bibcode route, which has poor recall for IFU
    survey papers (Borisova+2016, O'Sullivan+2020, Cai+2019, etc.) that cite
    QSO targets by coordinate name rather than SIMBAD object ID.

    Returns a list of ADS bibcodes (may be empty).
    """
    if not token or not source_name:
        return []
    # Build keyword OR clause (limit to first 4 keywords to keep query compact)
    kw_terms = " OR ".join(f'full:"{kw}"' for kw in focus_keywords[:4])
    q = f'full:"{source_name}" AND ({kw_terms})'
    params = {
        "q": q,
        "fl": "bibcode",
        "rows": str(max_results),
        "sort": "citation_count desc",
    }
    try:
        data = _ads_request(params, token)
        docs = data.get("response", {}).get("docs", [])
        return [d["bibcode"] for d in docs if d.get("bibcode")]
    except Exception:
        return []


def _arxiv_fallback(bibcodes: list[str]) -> list[dict]:
    """
    Minimal fallback using arXiv API when ADS token is absent.
    Only works for bibcodes that are arXiv preprints (starts with 20XX or 19XX arXiv format).
    Returns partial metadata (title + abstract only, no authors/year/citation_count).
    """
    results = []
    for bcode in bibcodes:
        results.append({
            "bibcode": bcode,
            "title": None,
            "authors": [],
            "year": None,
            "abstract": None,
            "citation_count": 0,
            "arxiv_id": None,
            "snippets": [],
            "error": "no_ads_token",
        })
    return results


def run(
    bibcodes: list[str],
    source_name: str | None = None,
    snippets: bool = False,
) -> list[dict]:
    token = os.environ.get("ADS_API_TOKEN", "").strip()

    if not token:
        print(
            json.dumps({"warning": "ADS_API_TOKEN not set; returning stub metadata"}),
            file=sys.stderr,
        )
        return _arxiv_fallback(bibcodes)

    papers = query_metadata(bibcodes, token)

    if snippets and source_name:
        # Attach snippets to each paper
        bcode_to_paper = {p["bibcode"]: p for p in papers}
        for bcode in bibcodes:
            paper = bcode_to_paper.get(bcode)
            if paper is None:
                continue
            try:
                paper["snippets"] = query_snippets(bcode, source_name, token)
            except Exception:
                paper["snippets"] = []

    return papers


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query ADS API for paper metadata")
    parser.add_argument(
        "--bibcodes",
        required=True,
        help="Comma-separated ADS bibcodes",
    )
    parser.add_argument(
        "--source-name",
        default=None,
        help="Source name for snippet highlighting",
    )
    parser.add_argument(
        "--snippets",
        action="store_true",
        help="Fetch body-text highlight snippets (requires --source-name)",
    )
    args = parser.parse_args()

    codes = [b.strip() for b in args.bibcodes.split(",") if b.strip()]
    results = run(codes, source_name=args.source_name, snippets=args.snippets)
    print(json.dumps(results, indent=2))
