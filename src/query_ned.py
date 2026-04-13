"""
query_ned.py — Query NED for QSO/AGN candidates.

Supports two spatial modes:

  Rectangle (broad sky search — preferred):
    python src/query_ned.py --project <name> \\
        --dec-min 5.0 --dec-max 35.0 [--ra-min 120.0 --ra-max 200.0] \\
        [--z-min 2.0] [--z-max 3.5]

  Cone (specific field — backward compatible):
    python src/query_ned.py --project <name> \\
        --ra <deg> --dec <deg> --radius <deg> \\
        [--z-min 2.0] [--z-max 3.5]

Rectangle mode automatically tiles the sky region with overlapping cones, since
NED has no bulk catalog endpoint. Each tile is recorded in query_history
independently, so interrupted runs can resume without re-querying completed tiles.
"""

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

NED_QSO_TYPES = {"QSO", "AGN", "Sy1", "Sy2", "BLLAC"}


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


def _query_ned_cone(ra_center, dec_center, radius_deg):
    """Execute one NED cone search. Returns astropy Table or None."""
    from astroquery.ipac.ned import Ned
    from astropy.coordinates import SkyCoord
    import astropy.units as u

    coord = SkyCoord(ra=ra_center, dec=dec_center, unit="deg")
    try:
        return Ned.query_region(coord, radius=radius_deg * u.deg)
    except Exception:
        return None


def _insert_ned_rows(project: str, result, z_min: float, z_max: float,
                     existing_coords) -> int:
    """Filter and insert NED rows into DB. Returns count of new sources."""
    from astropy.coordinates import SkyCoord
    new_sources = 0

    for row in result:
        obj_type = str(row["Type"]).strip()
        if not any(t in obj_type for t in NED_QSO_TYPES):
            continue

        z = row["Redshift"]
        if z is None:
            continue
        z = float(z)
        if not (z_min <= z <= z_max):
            continue

        ra  = float(row["RA"])
        dec = float(row["DEC"])
        name = str(row["Object Name"]).strip()

        if existing_coords is not None:
            new_coord = SkyCoord(ra=ra, dec=dec, unit="deg")
            if new_coord.separation(existing_coords).min().arcsec < 3.0:
                continue

        db.insert_source(
            project=project,
            name=name,
            ra=ra, dec=dec, z=z,
            z_source="NED",
            added_by="skill:query_ned",
        )
        new_sources += 1

    return new_sources


# ---------------------------------------------------------------------------
# Tiling geometry
# ---------------------------------------------------------------------------

def _rectangle_tiles(
    dec_min: float,
    dec_max: float,
    ra_min: float = None,
    ra_max: float = None,
) -> list[tuple[float, float, float]]:
    """
    Generate (ra_center, dec_center, radius_deg) tuples that fully cover the
    rectangle [ra_min..ra_max] x [dec_min..dec_max] with 10% overlap between
    adjacent tiles.

    The cone radius is sized to cover the full Dec extent of the rectangle.
    RA tiling uses the cos(Dec) scaling at the Dec midpoint.
    """
    dec_center = (dec_min + dec_max) / 2.0
    dec_half   = (dec_max - dec_min) / 2.0
    radius     = dec_half * 1.1  # 10% margin so tiles overlap in Dec

    # RA span covered by one cone of this radius at dec_center
    cos_dec  = max(math.cos(math.radians(dec_center)), 0.1)
    ra_span  = 2.0 * radius / cos_dec     # full RA diameter in deg
    step_ra  = ra_span * 0.9              # 10% overlap between adjacent tiles

    ra_lo = ra_min if ra_min is not None else 0.0
    ra_hi = ra_max if ra_max is not None else 360.0

    tiles = []
    ra = ra_lo + step_ra / 2.0
    while ra < ra_hi:
        tiles.append((ra, dec_center, radius))
        ra += step_ra

    return tiles


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
    Broad-sky rectangle query via automatic RA tiling.

    Each tile is deduped individually in query_history. Interrupted runs resume
    automatically by skipping already-completed tiles.
    """
    db.ensure_schema(project)

    tiles = _rectangle_tiles(dec_min, dec_max, ra_min, ra_max)
    n_tiles = len(tiles)

    total_raw   = 0
    total_new   = 0
    tiles_done  = 0
    tiles_failed = 0

    existing = _existing_coords(project)

    for tile_ra, tile_dec, tile_radius in tiles:
        tile_params = {
            "mode": "ned_tile",
            "database": "ned",
            "tile_ra": round(tile_ra, 4),
            "tile_dec": round(tile_dec, 4),
            "tile_radius": round(tile_radius, 4),
            "dec_min": dec_min,
            "dec_max": dec_max,
            "ra_min": ra_min,
            "ra_max": ra_max,
            "z_min": z_min,
            "z_max": z_max,
        }

        if db.has_been_queried(project, "ned", tile_params):
            tiles_done += 1
            continue

        result = _query_ned_cone(tile_ra, tile_dec, tile_radius)

        if result is None:
            db.record_query(project, "ned", tile_params, result_count=-1)
            tiles_failed += 1
            continue

        raw_count  = len(result)
        new_sources = _insert_ned_rows(project, result, z_min, z_max, existing)

        # Refresh coords so subsequent tiles dedup correctly against newly inserted sources
        existing = _existing_coords(project)

        db.record_query(project, "ned", tile_params, result_count=raw_count)
        total_raw += raw_count
        total_new += new_sources
        tiles_done += 1

    cached = (tiles_done == n_tiles and total_new == 0 and total_raw == 0)
    out = {
        "cached": cached,
        "new_sources": total_new,
        "raw_count": total_raw,
        "tiles_total": n_tiles,
        "tiles_completed": tiles_done,
        "tiles_failed": tiles_failed,
    }
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
    """Single cone query. Use for specific scheduled fields."""
    params = {
        "mode": "cone",
        "database": "ned",
        "ra": ra_center,
        "dec": dec_center,
        "radius_deg": radius_deg,
        "z_min": z_min,
        "z_max": z_max,
    }

    db.ensure_schema(project)
    if db.has_been_queried(project, "ned", params):
        out = {"cached": True, "new_sources": 0, "raw_count": 0}
        print(json.dumps(out))
        return out

    result = _query_ned_cone(ra_center, dec_center, radius_deg)

    if result is None:
        db.record_query(project, "ned", params, result_count=0)
        out = {"cached": False, "new_sources": 0, "raw_count": 0, "error": "NED query failed"}
        print(json.dumps(out))
        return out

    raw_count  = len(result)
    existing   = _existing_coords(project)
    new_sources = _insert_ned_rows(project, result, z_min, z_max, existing)
    db.record_query(project, "ned", params, result_count=raw_count)

    out = {"cached": False, "new_sources": new_sources, "raw_count": raw_count}
    print(json.dumps(out))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Query NED for QSO/AGN candidates (rectangle or cone mode)"
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
