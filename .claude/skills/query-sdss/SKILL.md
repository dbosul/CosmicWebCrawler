---
name: query-sdss
description: Query SDSS DR17 spectroscopic QSO catalog for candidates in a region
argument-hint: <project> [--dec-min D --dec-max D] | [--ra R --dec D --radius R] [z_min z_max]
---

Query SDSS DR17 for spectroscopically confirmed QSOs, filtered by redshift.
Results written directly to the project DB. Two spatial modes:

- **Rectangle** (preferred): full SDSS footprint in a Dec band, no RA assumption
- **Cone** (backward compatible): specific field for a scheduled night

## Usage

```bash
# Rectangle mode (broad sky search):
python src/query_sdss.py --project <project> \
    --dec-min <dec_min> --dec-max <dec_max> \
    [--ra-min <ra_min> --ra-max <ra_max>] \
    [--z-min 2.0] [--z-max 3.5]

# Cone mode (specific field):
python src/query_sdss.py --project <project> \
    --ra <ra_deg> --dec <dec_deg> --radius <radius_deg> \
    [--z-min 2.0] [--z-max 3.5]
```

## Output (JSON to stdout)

```json
{"cached": false, "new_sources": 312, "raw_count": 1847}
```

## Notes

- Rectangle mode uses `WHERE dec BETWEEN` directly on SpecObj — one query, full footprint
- Cone mode uses `fGetNearbyObjEq` for exact cone geometry
- `zWarning IN (0, 16)` — includes broad-line QSOs at high S/N (bit 4)
- `sciencePrimary = 1` — unique spectra only, no duplicate plate observations
- Source names: IAU SDSS designation `SDSS Jhhmmss.ss+ddmmss.s` (sexagesimal, truncated)
- Photometry: psfMag_u, psfMag_g, psfMag_r (values >30 treated as missing)
- Rectangle timeout: 300 s (large result sets expected); cone timeout: 60 s
