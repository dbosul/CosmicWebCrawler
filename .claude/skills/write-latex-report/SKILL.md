---
name: write-latex-report
description: Write a scientifically formatted PDF report using the AASTeX 6.3 template. Use this to produce sample summaries, pipeline status reports, or draft science sections ready for journal submission.
argument-hint: <project> <output_name> "<title>"
---

Generate a PDF report using the AASTeX 6.3 template (American Astronomical Society journals: ApJ, AJ, ApJL, ApJS).

## Usage

Write your LaTeX content to a .tex file, then compile:

```bash
python src/compile_latex.py --project <project> --tex <path/to/file.tex> --output <output_name>
```

Or generate from structured content:

```bash
python src/compile_latex.py --project <project> --output <output_name> \
    --title "Sample Selection for the CosmicWebCrawler COSMOS Pilot" \
    --authors "O'Sullivan, D." \
    --abstract "We present..." \
    --content-file <path/to/content.txt>
```

Output PDF is written to `projects/<project>/products/<output_name>.pdf`.

## AASTeX 6.3 document structure

When writing .tex content for this skill, follow this structure:

```latex
\documentclass[twocolumn]{aastex701}

\begin{document}

\title{Your Title Here}
\author{Author Name}
\affiliation{Institution}

\begin{abstract}
Abstract text here.
\end{abstract}

\keywords{keyword1, keyword2}

\section{Introduction} \label{sec:intro}
Text here.

\section{Sample Selection} \label{sec:sample}

\subsection{Catalog Queries}

Use \texttt{deluxetable} for data tables:

\begin{deluxetable}{lrrrrl}
\tablecaption{QSO Sample\label{tab:sample}}
\tablecolumns{6}
\tablehead{
  \colhead{Name} & \colhead{RA} & \colhead{Dec} &
  \colhead{$z$} & \colhead{$m_u$} & \colhead{Notes}
}
\startdata
J100028.60+021221.0 & 150.119 & 2.206 & 2.51 & 20.3 & -- \\
\enddata
\end{deluxetable}

\section{Conclusions} \label{sec:conclusions}

\acknowledgments
Built with CosmicWebCrawler.

\end{document}
```

## Key AASTeX conventions

- Use `\texttt{}` for code/catalog names
- Use `\citet{}` / `\citep{}` for citations (requires .bib file)
- Figures: `\begin{figure}...\includegraphics...\end{figure}`
- Math: standard LaTeX — `$z \sim 2$`, `$L_{\rm UV}$`, etc.
- Journal macros: `\apj`, `\aj`, `\mnras`, `\aap` for reference lists

## Notes

- Requires BasicTeX + AASTeX: `brew install --cask basictex && sudo tlmgr install aastex`
- Compilation runs twice to resolve references
- Intermediate files (.aux, .log) cleaned up automatically
- PDF goes to `projects/<project>/products/`
