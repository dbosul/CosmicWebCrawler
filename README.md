# CosmicWebCrawler

> **How much of my PhD can Claude Code do?**

This is an experiment in autonomous scientific research. CosmicWebCrawler is my attempt to replicate my PhD research pipeline (or similar) with a team of Claude agents. Essentially I'm building the assistant I wish I had for my PhD.

AI agents are (reasonably) not believed to be capable of 'doing science' autonomously - but ask any observer how much of their time is spent on conceptually simple but tedious tasks (sample selection, data reduction, data analysis, figure editing) and you start to see how AI can be used to dramatically accelerate scientific work. My gut feeling is that if I had a smart agentic platform, I could at least have cut my PhD timeline in half and still written a better thesis, by automating a lot of this work and focusing more of my time on the real science. (Less time writing grad-school code, more time reading the literature.)


**Work in progress.** The sampling and archive search stages are functional; data reduction and
emission-line analysis are stubs.

---

## The science problem

At z ≈ 2–3, luminous quasars sit inside massive dark matter haloes. The quasar's UV radiation
can illuminate the surrounding circumgalactic medium and produce extended Lyman-alpha emission
(rest-frame 1216 Å, redshifted into the optical). These "Lyman-alpha nebulae" trace cosmic
web filaments and constrain models of gas accretion and feedback.

Detecting them systematically requires:

1. A complete, unbiased QSO sample at the right redshift and sky coverage
2. A literature check to flag sources with prior detections
3. A cross-match against existing integral-field spectroscopy in public archives
4. Reduction and analysis of IFU data cubes


---

## Approach

The pipeline is a chain of collaborating Claude agents built on the
[Claude Code Agent SDK](https://docs.anthropic.com/en/docs/claude-code/sdk).

Each pipeline stage is owned by a **coordinator agent** with persistent context. Coordinators
delegate atomic work to **leaf agents** (ephemeral, single-purpose) and **skills** (Python
scripts that write directly to a SQLite database). The top-level orchestrator manages stage
transitions and human checkpoints.

```
research-assistant              top-level orchestrator
└── sample-coordinator          builds the target sample
    ├── query-agent             catalog queries (SDSS, SIMBAD, NED, VizieR)
    └── literature-agent ×N     arXiv search per source, citation-depth budget

archive-coordinator             KOA TAP search, calibration matching
reduction-coordinator           kcwidrp wrapper                          [stub]
analysis-coordinator            cube stacking, moment maps, Lyα detection [stub]
```

All state lives in a per-project SQLite database. Coordinators are persistent;
leaf agents are ephemeral and never spawn sub-agents. The dedup layer (`query_history`)
makes every catalog query idempotent — interrupted runs resume safely.

---

## Current status

| Stage | Status | Notes |
|---|---|---|
| Sample | Working | SDSS DR17Q, SIMBAD, NED, VizieR; quality checks; FoV vetting; literature review |
| Archive | Working | KOA TAP search; calibration matching; archive manifest |
| Reduction | Stub | kcwidrp integration planned |
| Analysis | Stub | cube stacking, moment maps, Lyα detection planned |

---

## Tech stack

- [Claude Code Agent SDK](https://docs.anthropic.com/en/docs/claude-code/sdk) — multi-agent harness
- [astroquery](https://astroquery.readthedocs.io/) — SDSS, SIMBAD, NED, VizieR
- [astropy](https://www.astropy.org/) — coordinates, units, FITS
- SQLite — all project state, via `src/db.py`
- KOA TAP — Keck Observatory Archive
