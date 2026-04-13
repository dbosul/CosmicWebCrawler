---
name: query-ned
description: Query NED for QSO/AGN candidates in a sky region
argument-hint: <project> [--dec-min D --dec-max D] | [--ra R --dec D --radius R] [z_min z_max]
---

Query NED (NASA/IPAC Extragalactic Database) for QSO/AGN candidates filtered by
redshift range. Two spatial modes:

- **Rectangle** (preferred): auto-tiles the Dec strip with overlapping cones — NED
  has no bulk catalog endpoint, so tiling is the only option for broad searches
- **Cone** (backward compatible): single cone query

Results written directly to the project DB. Each tile is deduped independently via
query_history, so interrupted runs resume without re-querying completed tiles.

## Usage

```bash
# Rectangle mode (broad sky search — NED tiles internally):
python src/query_ned.py --project <project> \
    --dec-min <dec_min> --dec-max <dec_max> \
    [--ra-min <ra_min> --ra-max <ra_max>] \
    [--z-min 2.0] [--z-max 3.5]

# Cone mode (specific field):
python src/query_ned.py --project <project> \
    --ra <ra_deg> --dec <dec_deg> --radius <radius_deg> \
    [--z-min 2.0] [--z-max 3.5]
```

## Output (JSON to stdout)

```json
{"cached": false, "new_sources": 12, "raw_count": 847,
 "tiles_total": 12, "tiles_completed": 12, "tiles_failed": 0}
```

## Notes

- Rectangle tiling: ~12 overlapping cones for Dec 5-35, more/fewer for other ranges
- Tile radius sized to cover full Dec extent with 10% margin; 10% RA overlap between tiles
- Failed tiles are skipped and logged (`tiles_failed`); re-run to retry them
- Object types: QSO, AGN, Sy1, Sy2, BLLAC
- Position dedup: sources within 3 arcsec of existing DB entries are skipped
- NED is a completeness check — SDSS and Milliquas are primary; NED adds non-SDSS sources
- NED queries can be slow or time out; failures are noted but do not abort the run
