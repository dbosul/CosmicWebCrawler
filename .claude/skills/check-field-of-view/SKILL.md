---
name: check-field-of-view
description: Check for bright stars and foreground galaxies within KCWI or PCWI field of view
argument-hint: <project> [instrument] [source_ids]
---

For each non-rejected candidate source, queries:
1. SIMBAD for stars brighter than V=12 within the instrument FoV
2. NED for foreground galaxies (z < 0.5) within the FoV

Flags sources with `bright_star_contamination`, `foreground_galaxy` (spectroscopic z), or
`foreground_galaxy_photoz` (photometric z — lower confidence, flag for human review).

FoV search radii:
- KCWI large slicer (33.1" x 20.4"): 20 arcsec search radius (half-diagonal ~19.3", padded to 20")
- PCWI (40" x 60"): 40 arcsec search radius

## Usage

```bash
python src/check_field_of_view.py --project <project> [--instrument KCWI]
python src/check_field_of_view.py --project <project> --instrument PCWI --source-ids 3,7
```

## Output (JSON to stdout)

```json
{"checked": 40, "flagged_bright_star": 3, "flagged_foreground": 1,
 "instrument": "KCWI", "fov_radius_arcsec": 20.0}
```

## Notes

- Network failures per-source are silently skipped — source is not penalized
- Flags are merged into existing flags, not replaced
- `bright_star_contamination` does not auto-reject — coordinator decides based on severity
