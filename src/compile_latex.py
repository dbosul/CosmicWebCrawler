"""
compile_latex.py — Compile a LaTeX file to PDF using AASTeX 6.3.

Runs pdflatex twice (to resolve references), cleans up intermediates,
and writes the final PDF to projects/<project>/products/<output>.pdf.

Usage:
    # Compile an existing .tex file
    python src/compile_latex.py --project cosmos-pilot --tex path/to/file.tex --output report

    # Generate from structured arguments
    python src/compile_latex.py --project cosmos-pilot --output sample_report \
        --title "COSMOS Pilot Sample" --authors "O'Sullivan, D." \
        --abstract "We present..." --body "\\section{Sample}\\nText here."
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

AASTEX_TEMPLATE = r"""
\documentclass[twocolumn]{aastex701}

\begin{document}

\title{%(title)s}
%(authors)s

\begin{abstract}
%(abstract)s
\end{abstract}

%(body)s

\end{document}
""".strip()


def format_authors(authors_str: str) -> str:
    """Convert 'Smith, J.; Jones, A.' into \\author lines."""
    authors = [a.strip() for a in authors_str.split(";") if a.strip()]
    return "\n".join(f"\\author{{{a}}}" for a in authors)


def build_tex(title: str, authors: str, abstract: str, body: str) -> str:
    return AASTEX_TEMPLATE % {
        "title": title,
        "authors": format_authors(authors),
        "abstract": abstract,
        "body": body,
    }


def compile_pdf(tex_content: str, output_name: str, project: str) -> dict:
    """
    Write tex_content to a temp dir, compile twice with pdflatex,
    copy PDF to projects/<project>/products/<output_name>.pdf.
    Returns {"success": bool, "pdf_path": str, "error": str|None}
    """
    products_dir = Path("projects") / project / "products"
    products_dir.mkdir(parents=True, exist_ok=True)

    pdflatex = shutil.which("pdflatex")
    if pdflatex is None:
        # BasicTeX installs to /usr/local/texlive/*/bin/
        for candidate in Path("/usr/local/texlive").glob("*/bin/*/pdflatex"):
            pdflatex = str(candidate)
            break
    if pdflatex is None:
        return {
            "success": False,
            "pdf_path": None,
            "error": "pdflatex not found. Install with: brew install --cask basictex",
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = Path(tmpdir) / f"{output_name}.tex"
        tex_path.write_text(tex_content)

        env = os.environ.copy()
        env["TEXMFHOME"] = str(Path.home() / "Library/texmf")

        for pass_num in range(2):
            result = subprocess.run(
                [pdflatex, "-interaction=nonstopmode", f"{output_name}.tex"],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                env=env,
            )
            if result.returncode != 0 and pass_num == 1:
                # If a PDF was produced despite non-zero exit, treat as success with warning
                pdf_src = Path(tmpdir) / f"{output_name}.pdf"
                if not pdf_src.exists():
                    log_tail = result.stdout[-2000:] if result.stdout else result.stderr[-2000:]
                    return {
                        "success": False,
                        "pdf_path": None,
                        "error": f"pdflatex failed (pass {pass_num + 1}):\n{log_tail}",
                    }

        pdf_src = Path(tmpdir) / f"{output_name}.pdf"
        if not pdf_src.exists():
            return {
                "success": False,
                "pdf_path": None,
                "error": "pdflatex ran but no PDF was produced. Check .tex syntax.",
            }

        pdf_dest = products_dir / f"{output_name}.pdf"
        shutil.copy2(pdf_src, pdf_dest)

    return {
        "success": True,
        "pdf_path": str(pdf_dest),
        "error": None,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", required=True, help="Output filename (no extension)")
    parser.add_argument("--tex", default=None, help="Path to existing .tex file")
    parser.add_argument("--title", default="Report")
    parser.add_argument("--authors", default="CosmicWebCrawler", help="Semicolon-separated authors")
    parser.add_argument("--abstract", default="")
    parser.add_argument("--body", default="", help="LaTeX body content (use \\n for newlines)")
    parser.add_argument("--body-file", default=None, help="Path to file containing body LaTeX")
    args = parser.parse_args()

    db.ensure_schema(args.project)

    if args.tex:
        tex_content = Path(args.tex).read_text()
    else:
        body = args.body.replace("\\n", "\n")
        if args.body_file:
            body = Path(args.body_file).read_text()
        tex_content = build_tex(
            title=args.title,
            authors=args.authors,
            abstract=args.abstract,
            body=body,
        )

    result = compile_pdf(tex_content, args.output, args.project)
    print(json.dumps(result, indent=2))

    if not result["success"]:
        sys.exit(1)
