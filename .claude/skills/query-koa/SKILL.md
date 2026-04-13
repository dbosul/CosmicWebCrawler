---
name: query-koa
description: Search the Keck Observatory Archive for public KCWI observations of accepted sample sources, match calibration frames, and optionally download raw FITS.
argument-hint: <project> [--source-ids N [N ...]] [--radius 30.0] [--download] [--dest-dir PATH]
allowed-tools: [Bash]
---

# query-koa — KOA Archive Search for KCWI Data

Queries the KOA TAP server for public KCWI science frames covering accepted sources
in the project DB. For each frame found, also finds matching calibration frames
(arc, contbars, flat, bias) by instrument config (`statenam`) within ±3 days.
Results are written to `observations` and `koa_frames` tables.

## Key facts (see `kcwi-public-data` skill for full reference)

- All TAP-visible rows are publicly downloadable — no auth needed
- Do NOT filter on `propint=0` — that misses >99% of public frames
- Calibration frames always have `propint=0` (immediately public)
- Downloaded files must be renamed: `KB.YYYYMMDD.SSSSS.fits` → `kb{YYMMDD}_{NNNNN}.fits`
- Volume warning fires at >5 GB estimated download — coordinator should pause for human review

## Invocation

```bash
source .venv/bin/activate

# Find data for all accepted sources not yet searched (no download)
python src/query_koa.py --project cosmos-pilot

# Find data for specific sources only
python src/query_koa.py --project cosmos-pilot --source-ids 1 2 5

# Find + download (pauses if >5 GB)
python src/query_koa.py --project cosmos-pilot --download

# Custom cone radius (default 30 arcsec)
python src/query_koa.py --project cosmos-pilot --radius 45.0
```

## Output (JSON printed to stdout after summary lines)

```json
{
  "sources_searched": 10,
  "sources_with_data": 3,
  "sources_no_data": 7,
  "observations_found": 8,
  "frames_found": 8,
  "estimated_volume_gb": 0.08,
  "downloaded": false
}
```

## DB changes

- Each science frame → one row in `observations` (generic) + one row in `koa_frames` (KOA-specific)
- Sources with no KOA data → flagged `no_archive_data` in `sources.flags`
- `query_history` dedup: keyed on `{source_id, radius_arcsec}`, database=`"koa"`
- Calibration KOAIDs stored as JSON array in `koa_frames.calib_koaids`
- After download: `koa_frames.raw_path` set, `observations.status` → `"downloaded"`

## File layout after download

```
projects/<project>/
  raw/
    <koaid>/
      kb{YYMMDD}_{NNNNN}.fits    ← renamed science frame
  calibrations/
    <statenam>_<YYMMDD>/
      kb{YYMMDD}_{NNNNN}.fits    ← arc, flat, contbars, bias
```

## Sources with no KOA data

Flag `no_archive_data` is added to `sources.flags` but status remains `"accepted"`.
These are new-observation targets — the intended outcome for a science-driven sample.
The archive coordinator should report them separately, not treat them as failures.

## Calibration coverage check

The script prints a per-frame calibration summary:

```
[query_koa]   KB.20230415.12345.fits  2023-04-15  t=1800s  grat=BM  slicer=Large
              calib=24 frames [arclamp contbars flatlamp MISSING:domeflat bias]
```

`MISSING:` prefixed types indicate gaps — coordinator should note these in the report.
Required types for kcwidrp: `arclamp`, `contbars`, `flatlamp` OR `domeflat`, `bias`.
