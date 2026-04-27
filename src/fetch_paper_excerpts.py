"""
fetch_paper_excerpts.py — Extract source-relevant excerpts from an arXiv paper's HTML.

Fetches the structured HTML version of an arXiv paper (arxiv.org/html/<id>) and
returns the abstract plus all paragraphs that mention the given source name.
Never fetches PDFs or full-text LaTeX. Falls back gracefully if HTML is unavailable.

Usage:
    python src/fetch_paper_excerpts.py --arxiv-id 2103.01234 --source-name "J1425+3254"

Output JSON:
    {
      "arxiv_id": "2103.01234",
      "abstract": "...",
      "excerpts": [
        {"section": "Results", "text": "...J1425+3254..."},
        ...
      ]
    }

    or on failure:
    {"arxiv_id": "...", "error": "no_html_version"}
"""

import argparse
import json
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

MAX_EXCERPTS = 5
ARXIV_HTML_URL = "https://arxiv.org/html/{arxiv_id}"


# ---------------------------------------------------------------------------
# Minimal HTML parser — no external dependencies
# ---------------------------------------------------------------------------

class _ArxivHTMLParser(HTMLParser):
    """
    Extracts abstract and paragraphs from arXiv HTML (ar5iv / LaTeXML format).

    arXiv HTML papers use ltx_ CSS classes:
      - ltx_abstract (div)  → abstract block
      - ltx_section         → section container
      - ltx_title           → section heading
      - ltx_para / ltx_p    → paragraph
    """

    def __init__(self):
        super().__init__()
        self.abstract: str | None = None
        self.paragraphs: list[dict] = []  # [{section, text}]

        self._in_abstract = False
        self._current_section = "Introduction"
        self._in_section_title = False
        self._in_para = False
        self._depth = 0          # nesting depth inside current block
        self._buf: list[str] = []

        self._abstract_depth = 0
        self._para_depth = 0

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "")

        if "ltx_abstract" in classes and tag == "div":
            self._in_abstract = True
            self._abstract_depth = self._depth
            self._buf = []

        if ("ltx_title" in classes) and not self._in_abstract:
            self._in_section_title = True
            self._buf = []

        if ("ltx_para" in classes or "ltx_p" in classes) and not self._in_abstract:
            self._in_para = True
            self._para_depth = self._depth
            self._buf = []

        self._depth += 1

    def handle_endtag(self, tag):
        self._depth -= 1

        if self._in_abstract and self._depth == self._abstract_depth:
            self.abstract = " ".join(self._buf).strip()
            self._in_abstract = False
            self._buf = []

        if self._in_section_title and self._depth < self._depth:
            self._current_section = " ".join(self._buf).strip()
            self._in_section_title = False
            self._buf = []

        if self._in_para and self._depth == self._para_depth:
            text = " ".join(self._buf).strip()
            if text:
                self.paragraphs.append({
                    "section": self._current_section,
                    "text": text,
                })
            self._in_para = False
            self._buf = []

    def handle_data(self, data):
        if self._in_abstract or self._in_para or self._in_section_title:
            stripped = data.strip()
            if stripped:
                self._buf.append(stripped)


def _fetch_html(arxiv_id: str) -> str | None:
    url = ARXIV_HTML_URL.format(arxiv_id=arxiv_id)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "CosmicWebCrawler/1.0 (astrophysics research tool)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                return None
            content_type = resp.headers.get("Content-Type", "")
            if "html" not in content_type.lower():
                return None
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def run(arxiv_id: str, source_name: str) -> dict:
    html = _fetch_html(arxiv_id)

    if html is None or "ltx_" not in html:
        return {"arxiv_id": arxiv_id, "error": "no_html_version"}

    parser = _ArxivHTMLParser()
    parser.feed(html)

    # Filter paragraphs that mention the source name (case-insensitive)
    name_lower = source_name.lower()
    matching = [
        p for p in parser.paragraphs
        if name_lower in p["text"].lower()
    ][:MAX_EXCERPTS]

    return {
        "arxiv_id": arxiv_id,
        "abstract": parser.abstract or "(abstract not found)",
        "excerpts": matching,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract source-relevant excerpts from an arXiv paper HTML"
    )
    parser.add_argument("--arxiv-id", required=True, help="arXiv ID, e.g. 2103.01234")
    parser.add_argument("--source-name", required=True, help="Source name to search for")
    args = parser.parse_args()

    result = run(args.arxiv_id, args.source_name)
    print(json.dumps(result, indent=2))
