"""
query_simbad.py — Query SIMBAD for QSO/AGN candidates.

Supports two spatial modes:

  Rectangle (broad sky search — preferred):
    python src/query_simbad.py --project <name> \\
        --dec-min 5.0 --dec-max 35.0 [--ra-min 120.0 --ra-max 200.0] \\
        [--z-min 2.0] [--z-max 3.5]

  Cone (specific field — backward compatible):
    python src/query_simbad.py --project <name> \\
        --ra <deg> --dec <deg> --radius <deg> \\
        [--z-min 2.0] [--z-max 3.5]

Rectangle mode queries the SIMBAD TAP service via ADQL.
Cone mode uses astroquery's query_region.
"""

import argparse
import csv
import io
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
import db

# SIMBAD condensed otype codes for QSO/AGN classes (simbad.cds.unistra.fr/guide/otypes)
# Strip trailing '?' before matching.
OBJECT_TYPES = {"QSO", "AGN", "SyG", "Sy1", "Sy2", "Bla", "BLL"}

SIMBAD_TAP_URL = "https://simbad.cds.unistra.fr/simbad/tap/sync"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _existing_coords(project: str):
    from astropy.coordinates import SkyCoord
    existing = db.get_all_sources(project)
    if not existing:
        return None
    return SkyCoord(
        ra=[s["ra"] for s in existing],
        dec=[s["dec"] for s in existing],
        unit="deg",
    )


def _otype_ok(otype: str) -> bool:
    return str(otype).strip().rstrip("?") in OBJECT_TYPES


def _insert_tap_rows(project: str, rows: list[dict], existing_coords) -> int:
    """Insert rows from SIMBAD TAP CSV response into DB."""
    from astropy.coordinates import SkyCoord
    new_sources = 0

    for row in rows:
        otype = row.get("otype", "")
        if not _otype_ok(otype):
            continue

        try:
            z = float(row["z_value"])
        except (TypeError, ValueError):
            continue

        try:
            ra  = float(row["ra"])
            dec = float(row["dec"])
        except (TypeError, ValueError):
            continue

        name = str(row.get("main_id", "")).strip() or f"SIMBAD J{ra:.4f}{dec:+.4f}"

        # rvz_type: "z"=spectroscopic, "v"=radial velocity (spec), "p"=photometric
        rvz_type = str(row.get("rvz_type", "")).strip().lower()
        if rvz_type == "p":
            flags = ["photo_z"]
        elif rvz_type in ("z", "v"):
            flags = []
        else:
            flags = ["z_type_unknown"]

        # Position dedup
        if existing_coords is not None:
            new_coord = SkyCoord(ra=ra, dec=dec, unit="deg")
            if new_coord.separation(existing_coords).min().arcsec < 3.0:
                continue

        sid = db.insert_source(
            project=project,
            name=name,
            ra=ra, dec=dec, z=z,
            z_source="SIMBAD",
            added_by="skill:query_simbad",
        )
        if flags:
            db.update_source_status(project, sid, "candidate", flags)
        new_sources += 1

    return new_sources


# ---------------------------------------------------------------------------
# Rectangle mode
# ---------------------------------------------------------------------------

def run(
    project: str,
    dec_min: float,
    dec_max: float,
    ra_min: float = None,
    ra_max: float = None,
    z_min: float = 2.0,
    z_max: float = 3.5,
) -> dict:
    """
    Broad-sky rectangle query via SIMBAD TAP ADQL.

    Note: SIMBAD TAP does not expose flux columns in the basic table.
    u_mag and g_mag will be None for SIMBAD-only sources; they will be filled
    in by cross-matching with SDSS photometry downstream if needed.
    """
    params = {
        "mode": "rectangle",
        "database": "simbad",
        "dec_min": dec_min,
        "dec_max": dec_max,
        "ra_min": ra_min,
        "ra_max": ra_max,
        "z_min": z_min,
        "z_max": z_max,
    }

    db.ensure_schema(project)
    if db.has_been_queried(project, "simbad", params):
        out = {"cached": True, "new_sources": 0, "raw_count": 0}
        print(json.dumps(out))
        return out

    # Build ADQL — use LIKE to match both clean otypes and '?' candidates
    otype_clauses = " OR ".join(
        f"otype LIKE '{t}%'" for t in sorted(OBJECT_TYPES)
    )
    ra_clause = ""
    if ra_min is not None and ra_max is not None:
        ra_clause = f"AND ra BETWEEN {ra_min} AND {ra_max}"

    adql = f"""
        SELECT main_id, ra, dec, z_value, rvz_type, otype
        FROM basic
        WHERE dec BETWEEN {dec_min} AND {dec_max}
          AND z_value BETWEEN {z_min} AND {z_max}
          AND ({otype_clauses})
          {ra_clause}
    """

    try:
        resp = requests.get(
            SIMBAD_TAP_URL,
            params={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": adql},
            timeout=120,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        db.record_query(project, "simbad", params, result_count=0)
        out = {"cached": False, "new_sources": 0, "raw_count": 0, "error": str(e)}
        print(json.dumps(out))
        return out

    text = resp.text.strip()
    if not text or text.lower().startswith("error"):
        db.record_query(project, "simbad", params, result_count=0)
        out = {"cached": False, "new_sources": 0, "raw_count": 0, "error": text[:200]}
        print(json.dumps(out))
        return out

    rows = list(csv.DictReader(io.StringIO(text)))
    raw_count = len(rows)

    existing = _existing_coords(project)
    new_sources = _insert_tap_rows(project, rows, existing)
    db.record_query(project, "simbad", params, result_count=raw_count)

    out = {"cached": False, "new_sources": new_sources, "raw_count": raw_count}
    print(json.dumps(out))
    return out


# ---------------------------------------------------------------------------
# Cone mode (backward compatible)
# ---------------------------------------------------------------------------

def run_cone(
    project: str,
    ra_center: float,
    dec_center: float,
    radius_deg: float,
    z_min: float = 2.0,
    z_max: float = 3.5,
) -> dict:
    """Single cone query using astroquery. Use for specific scheduled fields."""
    params = {
        "mode": "cone",
        "database": "simbad",
        "ra": ra_center,
        "dec": dec_center,
        "radius_deg": radius_deg,
        "z_min": z_min,
        "z_max": z_max,
    }

    db.ensure_schema(project)
    if db.has_been_queried(project, "simbad", params):
        out = {"cached": True, "new_sources": 0, "raw_count": 0}
        print(json.dumps(out))
        return out

    from astroquery.simbad import Simbad
    from astropy.coordinates import SkyCoord
    import astropy.units as u

    simbad = Simbad()
    # astroquery >= 0.4.8: use "U"/"G" directly → columns U, G
    # rvz_type distinguishes spectroscopic (z/v) from photometric (p) redshifts
    simbad.add_votable_fields("rvz_redshift", "rvz_type", "U", "G", "otype")
    simbad.TIMEOUT = 60

    coord = SkyCoord(ra=ra_center, dec=dec_center, unit="deg")
    result = simbad.query_region(coord, radius=radius_deg * u.deg)

    if result is None:
        db.record_query(project, "simbad", params, result_count=0)
        out = {"cached": False, "new_sources": 0, "raw_count": 0}
        print(json.dumps(out))
        return out

    raw_count = len(result)
    new_sources = 0

    for row in result:
        otype = str(row["otype"]).strip().rstrip("?")
        if otype not in OBJECT_TYPES:
            continue

        z = row["rvz_redshift"]
        if z is None or (hasattr(z, "mask") and z.mask):
            continue
        try:
            z = float(z)
        except (TypeError, ValueError):
            continue
        if not (z_min <= z <= z_max):
            continue

        rvz_type = str(row["rvz_type"]).strip() if "rvz_type" in result.colnames else ""
        if rvz_type.lower() == "p":
            flags = ["photo_z"]
        elif rvz_type.lower() in ("z", "v"):
            flags = []
        else:
            flags = ["z_type_unknown"]

        name = str(row["main_id"]).strip()
        ra   = float(row["ra"])
        dec  = float(row["dec"])

        u_mag = None
        g_mag = None
        try:
            val = row["U"]
            u_mag = float(val) if val is not None and not (hasattr(val, "mask") and val.mask) else None
        except (TypeError, ValueError, KeyError):
            pass
        try:
            val = row["G"]
            g_mag = float(val) if val is not None and not (hasattr(val, "mask") and val.mask) else None
        except (TypeError, ValueError, KeyError):
            pass

        sid = db.insert_source(
            project=project,
            name=name,
            ra=ra, dec=dec, z=z,
            z_source="SIMBAD",
            u_mag=u_mag,
            g_mag=g_mag,
            added_by="skill:query_simbad",
        )
        if flags:
            db.update_source_status(project, sid, "candidate", flags)
        new_sources += 1

    db.record_query(project, "simbad", params, result_count=raw_count)

    out = {"cached": False, "new_sources": new_sources, "raw_count": raw_count}
    print(json.dumps(out))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Query SIMBAD for QSO/AGN candidates (rectangle or cone mode)"
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--z-min", type=float, default=2.0)
    parser.add_argument("--z-max", type=float, default=3.5)

    # Rectangle mode
    parser.add_argument("--dec-min", type=float, default=None)
    parser.add_argument("--dec-max", type=float, default=None)
    parser.add_argument("--ra-min", type=float, default=None)
    parser.add_argument("--ra-max", type=float, default=None)

    # Cone mode
    parser.add_argument("--ra", type=float, default=None)
    parser.add_argument("--dec", type=float, default=None)
    parser.add_argument("--radius", type=float, default=None)

    args = parser.parse_args()

    if args.dec_min is not None and args.dec_max is not None:
        run(
            project=args.project,
            dec_min=args.dec_min,
            dec_max=args.dec_max,
            ra_min=args.ra_min,
            ra_max=args.ra_max,
            z_min=args.z_min,
            z_max=args.z_max,
        )
    elif args.ra is not None and args.dec is not None and args.radius is not None:
        run_cone(
            project=args.project,
            ra_center=args.ra,
            dec_center=args.dec,
            radius_deg=args.radius,
            z_min=args.z_min,
            z_max=args.z_max,
        )
    else:
        parser.error(
            "Provide either --dec-min/--dec-max (rectangle) "
            "or --ra/--dec/--radius (cone)"
        )
