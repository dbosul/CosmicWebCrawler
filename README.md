# CosmicWebCrawler

An autonomous multi-agent pipeline for astrophysics research, built with the
[Claude Agent SDK](https://docs.anthropic.com/en/docs/claude-code/sdk).
It replicates the methodology of the
[FLASHES Survey](https://ui.adsabs.harvard.edu/abs/2020ApJ...888...85C/abstract)
— a systematic search for extended Lyman-alpha nebulae around luminous quasars
at cosmic noon (z ≈ 2–3.5).

The pipeline takes a science configuration as input and autonomously builds a
target sample, cross-checks the astronomical literature, searches telescope
archives for existing data, and (once implemented) reduces raw IFU cubes and
detects extended emission.

---

## Science background

At z ≈ 2–3, quasars sit inside massive dark matter haloes whose circumgalactic
medium (CGM) can be illuminated by the quasar's UV flux and observed as
extended Lyman-alpha emission (rest-frame 1216 Å, redshifted into the optical).
These "Lyman-alpha nebulae" trace cosmic web filaments and constrain CGM
physics. Detecting them systematically requires:

1. A complete, unbiased QSO sample covering the right redshift window and
   telescope accessibility constraints.
2. A literature check to exclude sources with prior detections.
3. A cross-match against existing integral-field spectroscopy in public archives
   (primarily Keck/KCWI).
4. Reduction and analysis of new or archival IFU data cubes.

CosmicWebCrawler automates steps 1–4 as a chain of collaborating Claude agents.

---

## Architecture

```
run.py                          initialise DB, report state

research-assistant              top-level orchestrator
└── sample-coordinator          owns the sampling stage
    ├── query_sdss.py           SDSS DR17Q — primary QSO catalog
    ├── query_simbad.py         SIMBAD TAP — named-object completeness
    ├── query_ned.py            NED — RA-tiled broad-sky search
    ├── query_vizier.py         Milliquas VII/290 — compiled QSO catalog
    ├── check_data_quality.py   redshift plausibility, cross-catalog conflicts
    ├── check_field_of_view.py  bright-star contamination (KCWI FoV)
    ├── sample_bias.py          luminosity / spatial bias metrics
    └── literature-agent ×N     arXiv search per source (citation depth budget)

archive-coordinator             KOA TAP search, calibration matching, manifest
reduction-coordinator           kcwidrp DRP wrapper              [stub]
analysis-coordinator            cube stacking, moment maps, Lyα detection  [stub]
```

Each coordinator is a persistent Claude agent. Leaf agents (query-agent,
literature-agent) are ephemeral and never spawn sub-agents. All state lives in
a per-project SQLite database accessed exclusively through `src/db.py`.

---

## Spatial coverage model

Science configs describe sky coverage as a discriminated union, not a hard-coded
field centre:

```json
// Broad search — full SDSS footprint in a Dec band:
"spatial_coverage": { "mode": "rectangle", "dec_min": 5.0, "dec_max": 35.0 }

// Specific scheduled night:
"spatial_coverage": { "mode": "rectangle", "dec_min": 5.0, "dec_max": 35.0,
                      "ra_min": 120.0, "ra_max": 200.0 }

// Single field (backward compatible):
"spatial_coverage": { "mode": "cone", "ra": 185.0, "dec": 20.0, "radius_deg": 2.5 }
```

SDSS and VizieR use native column-filter queries in rectangle mode. SIMBAD uses
TAP ADQL. NED (cone-only API) is automatically tiled with overlapping cones.

---

## Status

| Stage | Status |
|---|---|
| Sample | Implemented — catalog queries, quality checks, FoV vetting, literature review |
| Archive | Implemented — KOA TAP search, calibration matching, manifest |
| Reduction | Stub — kcwidrp integration planned |
| Analysis | Stub — cube stacking, moment maps, Lyα detection planned |

---

## Quick start

```bash
git clone https://github.com/donal-s/CosmicWebCrawler
cd CosmicWebCrawler
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Initialise a project (dry-run — no API calls):
python run.py --project my-pilot --stage sample --dry-run

# Run the smoke tests:
pytest tests/smoke_test_cosmos_pilot.py -v
```

A full sampling run requires a `science_config.json` in `projects/<name>/` and
an active `ANTHROPIC_API_KEY` for the agent layer.

---

## Project layout

```
src/                Python pipeline scripts (db, catalog queries, checks)
.claude/agents/     Claude agent definitions (coordinators, leaf agents)
.claude/skills/     Skill definitions invoked by agents
projects/           Per-project namespaces (DB, products, raw data) — gitignored
tests/              Smoke tests (no external API calls)
run.py              CLI entry point
```

---

## Tech stack

- [Anthropic Claude API](https://docs.anthropic.com/) — agent orchestration
- [Claude Code Agent SDK](https://docs.anthropic.com/en/docs/claude-code/sdk) — multi-agent harness
- [astroquery](https://astroquery.readthedocs.io/) — SDSS, SIMBAD, NED, VizieR
- [astropy](https://www.astropy.org/) — coordinates, units, FITS
- SQLite (via `src/db.py`) — all project state
- KOA TAP — Keck Observatory Archive queries

---

## Background

This project was built as a demonstration of autonomous scientific reasoning
with large language models. The underlying science is real: the methodology
follows the published FLASHES Survey, the catalog queries hit live astronomical
databases, and the archive search runs against the actual Keck Observatory
Archive.

The goal is a system that a practicing astronomer could hand a science
configuration to and receive a vetted, literature-checked target list back
— without writing a single query by hand.
