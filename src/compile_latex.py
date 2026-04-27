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

# ---------------------------------------------------------------------------
# Helpers for mosaic figure generation
# ---------------------------------------------------------------------------

def _sanitize_name(name: str) -> str:
    """Mirror of fetch_cutouts.sanitize_name — must stay in sync."""
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    return safe[:50]


def _latex_escape(s: str) -> str:
    """Escape the LaTeX special characters most likely to appear in source names."""
    return (
        s.replace("\\", r"\textbackslash{}")
         .replace("_", r"\_")
         .replace("&", r"\&")
         .replace("%", r"\%")
         .replace("#", r"\#")
    )


def build_mosaic_figure(project: str, cutout_dir: Path, cols: int = 4) -> str:
    """
    Build a LaTeX figure* block — a cols-column grid of cutout thumbnails.

    Images are discovered by globbing cutout_dir/*/source_<id>_*.jpg and
    matched to accepted sources by source_id. Missing thumbnails get a
    placeholder fbox.

    Returns an empty string if there are no accepted sources (graceful
    degradation — the report still compiles without images).
    """
    sources = db.get_sources_by_status(project, "accepted")
    if not sources:
        return ""

    # Discover available cutout files, keyed by source_id.
    # cutout_dir layout: cutout_dir/<survey>/source_<id>_<name>.jpg
    available: dict[int, Path] = {}
    for img in sorted(cutout_dir.glob("*/source_*.jpg")):
        stem_parts = img.stem.split("_")
        # stem is "source_<id>_<rest…>" — parts[0]="source", parts[1]=id
        if len(stem_parts) >= 2:
            try:
                sid = int(stem_parts[1])
                available[sid] = img
            except ValueError:
                pass

    if not available:
        return ""

    # Each image cell is 0.23\textwidth; 4 cols × 0.23 + 3 gaps ≈ 0.95\textwidth
    cell_width = f"{(0.97 / cols):.2f}\\textwidth"
    col_spec = "c" * cols

    rows: list[str] = []
    row_imgs: list[str] = []
    row_labels: list[str] = []

    for i, src in enumerate(sources):
        img_path = available.get(src["id"])
        if img_path:
            # Use absolute path so pdflatex finds it regardless of cwd
            abs_path = str(img_path.resolve()).replace("\\", "/")
            cell_img = f"\\includegraphics[width={cell_width}]{{{abs_path}}}"
        else:
            cell_img = (
                f"\\fbox{{\\parbox[c][2.5cm][c]{{{cell_width}}}"
                r"{\centering\tiny No image}}}"
            )

        short_name = _latex_escape(src["name"][:18]) if src["name"] else "?"
        z_str = f"{src['z']:.2f}" if src.get("z") is not None else "?"
        cell_label = f"{{\\tiny {short_name}, $z={z_str}$}}"

        row_imgs.append(cell_img)
        row_labels.append(cell_label)

        is_last = (i == len(sources) - 1)
        if (i + 1) % cols == 0 or is_last:
            # Pad incomplete last row with empty cells
            while len(row_imgs) < cols:
                row_imgs.append("")
                row_labels.append("")
            rows.append(" & ".join(row_imgs) + r" \\[-2pt]")
            rows.append(" & ".join(row_labels) + r" \\[4pt]")
            row_imgs = []
            row_labels = []

    n_accepted = len(sources)
    n_shown = len(available)
    survey_label = "PS1 $gri$"

    tabular_body = "\n".join(rows)
    return (
        "\\begin{figure*}\n"
        "\\centering\n"
        "\\setlength{\\tabcolsep}{2pt}\n"
        f"\\begin{{tabular}}{{{col_spec}}}\n"
        f"{tabular_body}\n"
        "\\end{tabular}\n"
        "\\caption{\n"
        f"  {survey_label} color image cutouts ($60'' \\times 60''$) of accepted KCWI\n"
        f"  targets ({n_shown} of {n_accepted} with available imaging), ordered by\n"
        "  source ID. North is up, East is left.\n"
        "}\n"
        "\\label{fig:mosaic}\n"
        "\\end{figure*}\n"
    )

AASTEX_TEMPLATE = (
    r"\documentclass[twocolumn]{aastex701}" "\n"
    r"\begin{document}" "\n\n"
    r"\title{TITLE_PLACEHOLDER}" "\n"
    "AUTHORS_PLACEHOLDER\n\n"
    r"\begin{abstract}" "\n"
    "ABSTRACT_PLACEHOLDER\n"
    r"\end{abstract}" "\n\n"
    "BODY_PLACEHOLDER\n\n"
    r"\end{document}"
)
# Uses plain string replacement (not %-formatting) so that LaTeX % comments
# in the title/abstract/body do not raise TypeError.

# AASTeX 7.x requires \affiliation and \email for every author.
# Pipeline reports use a placeholder affiliation.


def format_authors(authors_str: str) -> str:
    """Convert 'Smith, J.; Jones, A.' into \\author + \\affiliation + \\email lines.

    AASTeX 7.x requires every author to have both \\affiliation and \\email.
    Pipeline reports use a placeholder for both.
    """
    authors = [a.strip() for a in authors_str.split(";") if a.strip()]
    lines = []
    for a in authors:
        lines.append(f"\\author{{{a}}}")
        lines.append("\\affiliation{CosmicWebCrawler pipeline}")
        lines.append("\\email{pipeline@cosmicwebcrawler}")
    return "\n".join(lines)


def build_tex(title: str, authors: str, abstract: str, body: str) -> str:
    return (
        AASTEX_TEMPLATE
        .replace("TITLE_PLACEHOLDER", title)
        .replace("AUTHORS_PLACEHOLDER", format_authors(authors))
        .replace("ABSTRACT_PLACEHOLDER", abstract)
        .replace("BODY_PLACEHOLDER", body)
    )


def compile_pdf(
    tex_content: str,
    output_name: str,
    project: str,
    cutout_dir: Path | None = None,
) -> dict:
    """
    Write tex_content to a temp dir, compile twice with pdflatex,
    copy PDF to projects/<project>/products/<output_name>.pdf.
    Returns {"success": bool, "pdf_path": str, "error": str|None}
    """
    products_dir = Path("projects") / project / "products"
    products_dir.mkdir(parents=True, exist_ok=True)

    # Inject \graphicspath so pdflatex can find products (bias_figure.pdf) and
    # cutout images regardless of the temp compilation directory.
    graphic_dirs = [str(products_dir.resolve()) + "/"]
    if cutout_dir is not None and cutout_dir.exists():
        for subdir in sorted(cutout_dir.iterdir()):
            if subdir.is_dir():
                graphic_dirs.append(str(subdir.resolve()) + "/")
    graphicspath = (
        "\\graphicspath{{" + "}{".join(graphic_dirs) + "}}\n"
    )
    tex_content = tex_content.replace(
        "\\begin{document}\n",
        "\\begin{document}\n" + graphicspath,
        1,
    )

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
    parser.add_argument(
        "--cutout-dir",
        default=None,
        help="Path to cutouts directory (projects/<project>/cutouts). "
             "Enables mosaic figure injection at the % MOSAIC_FIGURE_HERE sentinel.",
    )
    args = parser.parse_args()

    db.ensure_schema(args.project)

    cutout_dir = Path(args.cutout_dir) if args.cutout_dir else None

    if args.tex:
        tex_content = Path(args.tex).read_text()
    else:
        body = args.body.replace("\\n", "\n")
        if args.body_file:
            body = Path(args.body_file).read_text()

        # Inject mosaic figure at sentinel, or strip sentinel if no cutouts available
        SENTINEL = "% MOSAIC_FIGURE_HERE\n"
        if cutout_dir is not None:
            mosaic_latex = build_mosaic_figure(args.project, cutout_dir)
            body = body.replace(SENTINEL, mosaic_latex)
        body = body.replace(SENTINEL, "")  # strip any remaining sentinel

        tex_content = build_tex(
            title=args.title,
            authors=args.authors,
            abstract=args.abstract,
            body=body,
        )

    result = compile_pdf(tex_content, args.output, args.project, cutout_dir=cutout_dir)
    print(json.dumps(result, indent=2))

    if not result["success"]:
        sys.exit(1)
