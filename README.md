# CosmicWebCrawler

> **How much of my PhD can Claude Code do?**

This is an experiment in autonomous scientific research. I spent five years at Caltech hunting
for Lyman-alpha nebulae around high-redshift quasars — systematically searching for glowing gas
in the cosmic web around massive black holes at the peak of galaxy formation (z ≈ 2–3).

CosmicWebCrawler is my attempt to replicate that research pipeline with a team of Claude agents.
The science is real. The methodology follows the published
[FLASHES Survey](https://ui.adsabs.harvard.edu/abs/2020ApJ...888...85C/abstract).
The catalog queries hit live astronomical databases. The archive search runs against the actual
Keck Observatory Archive.

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

This is exactly the work I did by hand during my PhD. CosmicWebCrawler automates it.

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

## Quick start

```bash
git clone https://github.com/dbosul/CosmicWebCrawler
cd CosmicWebCrawler
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Dry-run (no API calls, no catalog queries):
python run.py --project my-pilot --stage sample --dry-run

# Smoke tests:
pytest tests/smoke_test_cosmos_pilot.py -v
```

A full run requires a `science_config.json` in `projects/<name>/` and an active
`ANTHROPIC_API_KEY` for the agent layer.

---

## Tech stack

- [Claude Code Agent SDK](https://docs.anthropic.com/en/docs/claude-code/sdk) — multi-agent harness
- [astroquery](https://astroquery.readthedocs.io/) — SDSS, SIMBAD, NED, VizieR
- [astropy](https://www.astropy.org/) — coordinates, units, FITS
- SQLite — all project state, via `src/db.py`
- KOA TAP — Keck Observatory Archive
