---
name: check-field-of-view
description: Check for bright stars and foreground galaxies within KCWI or PCWI field of view
argument-hint: <project> [instrument] [source_ids]
---

For each non-rejected candidate source, queries:
1. SIMBAD for stars brighter than V=12 within the instrument FoV
2. NED for foreground galaxies (z < 0.5) within the FoV

Flags sources with `bright_star_contamination` or `foreground_galaxy`.

FoV search radii:
- KCWI large slicer (16.5" x 20.4"): 25 arcsec search radius
- PCWI (40" x 60"): 75 arcsec search radius

## Usage

```bash
python src/check_field_of_view.py --project <project> [--instrument KCWI]
python src/check_field_of_view.py --project <project> --instrument PCWI --source-ids 3,7
```

## Output (JSON to stdout)

```json
{"checked": 40, "flagged_bright_star": 3, "flagged_foreground": 1,
 "instrument": "KCWI", "fov_radius_arcsec": 25.0}
```

## Notes

- Network failures per-source are silently skipped — source is not penalized
- Flags are merged into existing flags, not replaced
- `bright_star_contamination` does not auto-reject — coordinator decides based on severity
