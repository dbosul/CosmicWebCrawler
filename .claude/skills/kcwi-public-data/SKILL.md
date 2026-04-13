---
name: kcwi-public-data
description: Query and download public KCWI data from the Keck Observatory Archive (KOA). Covers TAP query interface, metadata columns, calibration matching, download URL pattern, and file naming gotcha for the DRP.
argument-hint: <project> <ra> <dec> <radius_deg>
---

# KCWI Public Data — Keck Observatory Archive (KOA)

## Key facts established by live testing (2026-04-13)

- **~35,150 public KCWI science frames** available as of April 2026, spanning Sep 2017–Oct 2024
- **No authentication required** for data whose proprietary period has expired
- **Proprietary period:** 12 months (NASA programs, since 2023A) or 18 months (Caltech/UC/Hawaii)
- The TAP server automatically injects `current_date > add_months(date_obs, propint)` into every
  anonymous query — all rows returned are already public and downloadable
- **Do NOT filter on `propint=0`** — that only catches frames where the PI chose immediate release
  (~387 frames). All TAP-visible rows are accessible.

## TAP Query Interface

**Endpoint:** `https://koa.ipac.caltech.edu/TAP/sync`  
**Table:** `koa_kcwi`  
**Protocol:** IVOA ADQL (Oracle SQL dialect — use `TOP N` not `LIMIT N`, `ROWNUM` not `OFFSET`)

### Cone search for science frames

```python
import requests

def query_koa_kcwi(ra, dec, radius_deg, z_min, z_max, instrument="KCWI"):
    """
    Find public KCWI science observations covering a target field.
    waveblue/wavered in Angstroms; filter to Lya window at target redshift.
    """
    wave_target_min = 1216.0 * (1 + z_min)  # Lya at z_min
    wave_target_max = 1216.0 * (1 + z_max)  # Lya at z_max

    adql = f"""
        SELECT koaid, ra, dec, date_obs, propint, exptime,
               bgratnam, ifunam, waveblue, wavered, wavecntr,
               progid, progpi, progtitl, targname,
               statenam, stateid, filehand, semester
        FROM koa_kcwi
        WHERE koaimtyp = 'object'
          AND CONTAINS(POINT('ICRS', ra, dec),
                       CIRCLE('ICRS', {ra}, {dec}, {radius_deg})) = 1
          AND waveblue <= {wave_target_max}
          AND wavered  >= {wave_target_min}
        ORDER BY date_obs DESC
    """
    resp = requests.get(
        "https://koa.ipac.caltech.edu/TAP/sync",
        params={"LANG": "ADQL", "FORMAT": "csv", "QUERY": adql},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.text  # CSV; parse with csv.DictReader or pandas
```

### Find matching calibration frames

Calibrations have **zero proprietary period** — always public.
Match by `statenam` (instrument config) within ±3 days of science observation.

```sql
SELECT koaid, date_obs, koaimtyp, exptime, bgratnam, ifunam, filehand
FROM koa_kcwi
WHERE koaimtyp IN ('arclamp', 'contbars', 'flatlamp', 'domeflat', 'bias', 'dark', 'twiflat')
  AND statenam = '<statenam_from_science_frame>'
  AND date_obs BETWEEN '<sci_date - 3 days>' AND '<sci_date + 3 days>'
```

Required calibration types for kcwidrp:

| `koaimtyp` | Purpose |
|---|---|
| `bias` | Overscan/bias subtraction |
| `contbars` | Geometric solution (bar tracing) — **required** |
| `arclamp` | Wavelength calibration — **required** |
| `flatlamp` or `domeflat` | Flat field — **required** |
| `dark` | Dark current (optional) |
| `twiflat` | Illumination correction (optional) |
| `object` (standard star) | Flux calibration — needed for `icubes` output |

## Download

**URL pattern:**
```
https://koa.ipac.caltech.edu/cgi-bin/getKOA/nph-getKOA?filehand={filehand}
```

- `filehand` comes directly from the TAP query result
- No authentication header needed for expired-proprietary data
- Returns raw FITS (~10 MB per science frame)
- HTTP 200 = success; HTTP 401 = still proprietary (shouldn't happen for TAP-visible rows)

Example:
```python
import requests
from pathlib import Path

def download_koa_frame(filehand: str, dest_dir: Path) -> Path:
    url = f"https://koa.ipac.caltech.edu/cgi-bin/getKOA/nph-getKOA?filehand={filehand}"
    koaid = filehand.split("/")[-1]
    dest = dest_dir / koaid
    if dest.exists():
        return dest  # already downloaded
    resp = requests.get(url, timeout=300, stream=True)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    return dest
```

## CRITICAL: File naming for kcwidrp

**KOA renames files** from telescope convention to KOA convention on ingest:

| Convention | Format | Example |
|---|---|---|
| Telescope (DRP expects) | `kb{YYMMDD}_{NNNNN}.fits` | `kb170918_21047.fits` |
| KOA (downloaded as) | `KB.{YYYYMMDD}.{SSSSS}.fits` | `KB.20170918.21047.fits` |

**Rename after download before running kcwidrp:**
```python
import re
from pathlib import Path

def koa_to_telescope_name(koa_name: str) -> str:
    """KB.20170918.21047.fits → kb170918_21047.fits"""
    m = re.match(r"KB\.(\d{4})(\d{2})(\d{2})\.(\d+)\.fits", koa_name)
    if not m:
        raise ValueError(f"Unexpected KOA filename format: {koa_name}")
    yyyy, mm, dd, num = m.groups()
    return f"kb{yyyy[2:]}{mm}{dd}_{num}.fits"
```

## Key TAP metadata columns

| Column | Description |
|---|---|
| `koaid` | KOA unique ID (`KB.YYYYMMDD.SSSSS.fits`) |
| `filehand` | Server path for download |
| `koaimtyp` | Frame classification: `object`, `arclamp`, `bias`, `contbars`, `flatlamp`, etc. |
| `propint` | Nominal proprietary period (months) — NOT remaining time |
| `ra`, `dec` | Pointing coordinates (degrees, ICRS) |
| `targname` | Target name from header |
| `date_obs` | UT observation date |
| `exptime` | Exposure time (seconds) |
| `bgratnam` | Blue grating: `BL`, `BM`, `BH1`, `BH2`, `BH3` |
| `ifunam` | Slicer: `Small`, `Medium`, `Large` |
| `waveblue`, `wavered`, `wavecntr` | Wavelength coverage (Angstroms) |
| `statenam`, `stateid` | Instrument config — use for calibration matching |
| `progid` | Program ID (e.g. `C379`) |
| `progpi` | PI last name |
| `progtitl` | Program title |
| `semester` | Observing semester (e.g. `2022B`) |
| `airmass` | Airmass at midpoint |
| `camera` | `BLUE` or `RED` |

## Data products from kcwidrp

The official Python DRP: https://github.com/Keck-DataReductionPipelines/KCWI_DRP

| Output suffix | Content |
|---|---|
| `_icube.fits` | 3D data cube (electrons/px, geometry applied) |
| `_icubed.fits` | DAR-corrected cube — **primary science product** |
| `_icubes.fits` | Flux-calibrated cube (requires standard star in program) |
| `_vcube*.fits` | Variance cubes |
| `_mcube*.fits` | Mask/flag cubes |

KOA also serves pre-reduced Lev2 products (`icubed`, `icubes`) for observations since
2022-02-17, produced using **PypeIt** (not the official kcwidrp). These are accessible via
the KOA web download script but are **not queryable as separate TAP rows**.

## Notes

- TAP uses Oracle SQL: no `LIMIT`, use `TOP N`; date literals need Oracle format
- Spatial queries use IVOA geometry: `CONTAINS(POINT(...), CIRCLE(...)) = 1`
- All calibration frames are immediately public regardless of science frame proprietary status
- Science frame total: ~35,150 public as of April 2026; calibration frames: ~35,000+
- `pyvo` library provides a cleaner Python TAP client than raw requests if available
