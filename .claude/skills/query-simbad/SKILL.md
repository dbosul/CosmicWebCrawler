---
name: query-simbad
description: Query SIMBAD for QSO/AGN candidates in a sky region
argument-hint: <project> [--dec-min D --dec-max D] | [--ra R --dec D --radius R] [z_min z_max]
---

Query SIMBAD for QSO and AGN objects filtered by redshift range. Two spatial modes:

- **Rectangle** (preferred): queries SIMBAD TAP via ADQL — no RA assumption
- **Cone** (backward compatible): uses astroquery query_region

Results written directly to the project DB. Duplicate queries skipped via query_history.

## Usage

```bash
# Rectangle mode (broad sky search):
python src/query_simbad.py --project <project> \
    --dec-min <dec_min> --dec-max <dec_max> \
    [--ra-min <ra_min> --ra-max <ra_max>] \
    [--z-min 2.0] [--z-max 3.5]

# Cone mode (specific field):
python src/query_simbad.py --project <project> \
    --ra <ra_deg> --dec <dec_deg> --radius <radius_deg> \
    [--z-min 2.0] [--z-max 3.5]
```

## Output (JSON to stdout)

```json
{"cached": false, "new_sources": 47, "raw_count": 312}
```

## Notes

- Object types: QSO, AGN, SyG, Sy1, Sy2, Bla, BLL (trailing `?` stripped before match)
- Rectangle mode: hits SIMBAD TAP at simbad.cds.unistra.fr — timeout 120 s
- Rectangle mode: u_mag/g_mag will be None (TAP basic table has no flux columns);
  photometry is filled by SDSS cross-match for sources in the SDSS footprint
- Cone mode: retrieves U and G flux via add_votable_fields
- rvz_type checked: `p` → `photo_z` flag; unknown type → `z_type_unknown` flag
- Position dedup: sources within 3 arcsec of existing DB entries are skipped
