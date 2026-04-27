---
name: query-vizier
description: Query VizieR catalogs for QSO candidates — default is Milliquas (VII/294)
argument-hint: <project> [--dec-min D --dec-max D] | [--ra R --dec D --radius R] [catalog] [z_min z_max]
---

Query VizieR for QSO candidates. Default catalog is Milliquas v8 (VII/294), the most
complete compilation of known QSOs. Two spatial modes:

- **Rectangle** (preferred): uses `query_constraints` with DEC/Z column filters — no RA assumption, one query
- **Cone** (backward compatible): positional `query_region`

## Usage

```bash
# Rectangle mode (broad sky search):
python src/query_vizier.py --project <project> \
    --dec-min <dec_min> --dec-max <dec_max> \
    [--ra-min <ra_min> --ra-max <ra_max>] \
    [--catalog VII/294] [--z-min 2.0] [--z-max 3.5]

# Cone mode (specific field):
python src/query_vizier.py --project <project> \
    --ra <ra_deg> --dec <dec_deg> --radius <radius_deg> \
    [--catalog VII/294] [--z-min 2.0] [--z-max 3.5]
```

## Output (JSON to stdout)

```json
{"cached": false, "new_sources": 5, "raw_count": 18}
```

## Notes

- Default: Milliquas VII/294 — the most complete QSO compilation; use this first
- Rectangle uses VizieR range syntax `"min..max"` for DEC and Z constraints
- Type filter: Q (QSO), A (AGN), B (BL Lac) — excludes narrow-line types (K, N)
- Bmag in Milliquas is heterogeneous (SDSS u / APM B / USNO B) — stored as `b_mag`, NOT `u_mag`
- Position dedup: 3 arcsec cross-match against existing DB entries
- z_source field records `VizieR:<catalog_id>` for provenance
