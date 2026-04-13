"""
query_sdss.py — Query SDSS DR17 spectroscopic QSO catalog.

Supports two spatial modes driven by the science_config spatial_coverage block:

  Rectangle (broad sky search — preferred):
    python src/query_sdss.py --project <name> \\
        --dec-min 5.0 --dec-max 35.0 [--ra-min 120.0 --ra-max 200.0] \\
        [--z-min 2.0] [--z-max 3.5]

  Cone (specific field — backward compatible):
    python src/query_sdss.py --project <name> \\
        --ra <deg> --dec <deg> --radius <deg> \\
        [--z-min 2.0] [--z-max 3.5]

Mode is inferred from arguments: dec-min/dec-max → rectangle; ra/dec/radius → cone.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_name(ra: float, dec: float) -> str:
    """IAU SDSS designation: SDSS Jhhmmss.ss+ddmmss.s (sexagesimal, truncated)."""
    from astropy.coordinates import SkyCoord
    coord = SkyCoord(ra=ra, dec=dec, unit="deg")
    h = coord.ra.hms
    d = coord.dec.dms
    return (
        f"SDSS J"
        f"{int(h.h):02d}{int(h.m):02d}{h.s:05.2f}"
        f"{'+' if dec >= 0 else '-'}"
        f"{abs(int(d.d)):02d}{abs(int(d.m)):02d}{abs(d.s):04.1f}"
    )


def _insert_rows(project: str, result) -> int:
    """Insert astropy Table rows into the DB. Returns count of new sources."""
    new_sources = 0
    for row in result:
        ra  = float(row["ra"])
        dec = float(row["dec"])
        z   = float(row["z"])
        u_mag = float(row["psfMag_u"]) if row["psfMag_u"] < 30 else None
        g_mag = float(row["psfMag_g"]) if row["psfMag_g"] < 30 else None
        r_mag = float(row["psfMag_r"]) if row["psfMag_r"] < 30 else None
        db.insert_source(
            project=project,
            name=_make_name(ra, dec),
            ra=ra, dec=dec, z=z,
            z_source="SDSS_DR17",
            u_mag=u_mag, g_mag=g_mag, r_mag=r_mag,
            added_by="skill:query_sdss",
        )
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
    Broad-sky rectangle query. Primary mode for science-driven sampling.

    No RA constraint → full SDSS footprint in the Dec band.
    Optional ra_min/ra_max for scheduled-night restrictions.
    """
    params = {
        "mode": "rectangle",
        "database": "sdss",
        "dec_min": dec_min,
        "dec_max": dec_max,
        "ra_min": ra_min,
        "ra_max": ra_max,
        "z_min": z_min,
        "z_max": z_max,
    }

    db.ensure_schema(project)
    if db.has_been_queried(project, "sdss", params):
        out = {"cached": True, "new_sources": 0, "raw_count": 0}
        print(json.dumps(out))
        return out

    from astroquery.sdss import SDSS

    # DR17 (eBOSS) is intentional: final and most complete SDSS spectroscopic QSO catalog.
    # DR18+ are SDSS-V releases with a different targeting strategy.
    # zWarning=16 (MANY_OUTLIERS) fires on broad-line QSOs at high S/N — include it.
    # sciencePrimary=1 ensures unique spectra only (no duplicate plate observations).
    # Direct WHERE clause on dec replaces fGetNearbyObjEq for full-footprint queries.
    ra_clause = ""
    if ra_min is not None and ra_max is not None:
        ra_clause = f"AND s.ra BETWEEN {ra_min} AND {ra_max}"

    sql = f"""
        SELECT
            s.ra, s.dec,
            p.psfMag_u, p.psfMag_g, p.psfMag_r,
            s.z, s.specObjID
        FROM SpecObj s
        JOIN PhotoObjAll p ON s.bestObjID = p.objID
        WHERE s.class = 'QSO'
          AND (s.zWarning = 0 OR s.zWarning = 16)
          AND s.sciencePrimary = 1
          AND s.z BETWEEN {z_min} AND {z_max}
          AND s.dec BETWEEN {dec_min} AND {dec_max}
          {ra_clause}
    """

    result = SDSS.query_sql(sql, timeout=300)

    if result is None:
        db.record_query(project, "sdss", params, result_count=0)
        out = {"cached": False, "new_sources": 0, "raw_count": 0}
        print(json.dumps(out))
        return out

    raw_count = len(result)
    new_sources = _insert_rows(project, result)
    db.record_query(project, "sdss", params, result_count=raw_count)

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
    """
    Single cone query using fGetNearbyObjEq. Use for specific scheduled fields.
    """
    params = {
        "mode": "cone",
        "database": "sdss",
        "ra": ra_center,
        "dec": dec_center,
        "radius_deg": radius_deg,
        "z_min": z_min,
        "z_max": z_max,
    }

    db.ensure_schema(project)
    if db.has_been_queried(project, "sdss", params):
        out = {"cached": True, "new_sources": 0, "raw_count": 0}
        print(json.dumps(out))
        return out

    from astroquery.sdss import SDSS

    radius_arcmin = radius_deg * 60.0
    sql = f"""
        SELECT
            s.ra, s.dec,
            p.psfMag_u, p.psfMag_g, p.psfMag_r,
            s.z, s.specObjID
        FROM dbo.fGetNearbyObjEq({ra_center}, {dec_center}, {radius_arcmin}) n
        JOIN SpecObj s ON n.objID = s.bestObjID
        JOIN PhotoObjAll p ON s.bestObjID = p.objID
        WHERE s.class = 'QSO'
          AND (s.zWarning = 0 OR s.zWarning = 16)
          AND s.sciencePrimary = 1
          AND s.z BETWEEN {z_min} AND {z_max}
    """

    result = SDSS.query_sql(sql, timeout=60)

    if result is None:
        db.record_query(project, "sdss", params, result_count=0)
        out = {"cached": False, "new_sources": 0, "raw_count": 0}
        print(json.dumps(out))
        return out

    raw_count = len(result)
    new_sources = _insert_rows(project, result)
    db.record_query(project, "sdss", params, result_count=raw_count)

    out = {"cached": False, "new_sources": new_sources, "raw_count": raw_count}
    print(json.dumps(out))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Query SDSS DR17 QSO catalog (rectangle or cone mode)"
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--z-min", type=float, default=2.0)
    parser.add_argument("--z-max", type=float, default=3.5)

    # Rectangle mode
    parser.add_argument("--dec-min", type=float, default=None,
                        help="Rectangle mode: minimum declination (deg)")
    parser.add_argument("--dec-max", type=float, default=None,
                        help="Rectangle mode: maximum declination (deg)")
    parser.add_argument("--ra-min", type=float, default=None,
                        help="Rectangle mode: optional RA lower bound (deg)")
    parser.add_argument("--ra-max", type=float, default=None,
                        help="Rectangle mode: optional RA upper bound (deg)")

    # Cone mode
    parser.add_argument("--ra", type=float, default=None,
                        help="Cone mode: centre RA (deg)")
    parser.add_argument("--dec", type=float, default=None,
                        help="Cone mode: centre Dec (deg)")
    parser.add_argument("--radius", type=float, default=None,
                        help="Cone mode: radius (deg)")

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
