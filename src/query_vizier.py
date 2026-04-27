"""
query_vizier.py — Query VizieR catalogs for QSO candidates.

Default catalog: Milliquas v8 (VII/294, Flesch 2023, PASA 40, e010).

Column names verified against VizieR VII/294: RAJ2000, DEJ2000, Name, Type, Rmag, Bmag, z.
Note: VII/290 (Milliquas v7.2) uses different column names (RAdeg, DEdeg); do not confuse.

Supports two spatial modes:

  Rectangle (broad sky search — preferred):
    python src/query_vizier.py --project <name> \\
        --dec-min 5.0 --dec-max 35.0 [--ra-min 120.0 --ra-max 200.0] \\
        [--z-min 2.0] [--z-max 3.5]

  Cone (specific field — backward compatible):
    python src/query_vizier.py --project <name> \\
        --ra <deg> --dec <deg> --radius <deg> \\
        [--z-min 2.0] [--z-max 3.5]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

# Milliquas VII/294 (v8) column map: VizieR col -> our schema key
# Column names verified empirically via astroquery against VII/294.
# Bmag is heterogeneous (SDSS u, APM B, USNO B depending on source) — stored as b_mag,
# NOT u_mag, to avoid conflating with SDSS u-band in photometric quality cuts.
MILLIQUAS_COLUMN_MAP = {
    "RAJ2000": "ra",
    "DEJ2000": "dec",
    "z": "z",
    "Name": "name",
    "Rmag": "r_mag",
    "Bmag": "b_mag",
    "Type": "qso_type",
}

DEFAULT_CATALOG = "VII/294"  # Milliquas v8 (Flesch 2023, PASA 40, e010)

# Milliquas type filter: broad-line types only
# Q=QSO, A=AGN, B=BL Lac — excludes K=NLQSO, N=NLAGN (narrow-line; Lya geometry different)
BROAD_LINE_TYPES = {"Q", "A", "B"}

FLOAT_KEYS = {"ra", "dec", "z", "r_mag", "b_mag"}


def _insert_rows(project: str, result, catalog: str, existing_coords) -> int:
    """Insert VizieR table rows into DB. Returns count of new sources."""
    from astropy.coordinates import SkyCoord
    new_sources = 0

    for row in result:
        mapped = {}
        for vcol, schema_key in MILLIQUAS_COLUMN_MAP.items():
            if vcol not in result.colnames:
                continue
            val = row[vcol]
            is_masked = hasattr(val, "mask") and val.mask
            if val is None or is_masked:
                mapped[schema_key] = None
            elif schema_key in FLOAT_KEYS:
                try:
                    mapped[schema_key] = float(val)
                except (TypeError, ValueError):
                    mapped[schema_key] = None
            else:
                mapped[schema_key] = str(val).strip()

        ra  = mapped.get("ra")
        dec = mapped.get("dec")
        z   = mapped.get("z")
        name = mapped.get("name")
        qso_type = mapped.get("qso_type", "Q")

        if ra is None or dec is None or z is None:
            continue
        if qso_type and qso_type[0] not in BROAD_LINE_TYPES:
            continue
        if name is None:
            name = f"Milliquas J{ra:.4f}{dec:+.4f}"

        # Position dedup against existing sources
        if existing_coords is not None:
            new_coord = SkyCoord(ra=ra, dec=dec, unit="deg")
            if new_coord.separation(existing_coords).min().arcsec < 3.0:
                continue

        db.insert_source(
            project=project,
            name=str(name),
            ra=ra, dec=dec, z=z,
            z_source=f"VizieR:{catalog}",
            r_mag=mapped.get("r_mag"),
            b_mag=mapped.get("b_mag"),  # Milliquas Bmag (heterogeneous blue-band)
            added_by="skill:query_vizier",
        )
        new_sources += 1

    return new_sources


def _existing_coords(project: str):
    """Return SkyCoord of all existing sources, or None if DB is empty."""
    from astropy.coordinates import SkyCoord
    existing = db.get_all_sources(project)
    if not existing:
        return None
    return SkyCoord(
        ra=[s["ra"] for s in existing],
        dec=[s["dec"] for s in existing],
        unit="deg",
    )


# ---------------------------------------------------------------------------
# Rectangle mode
# ---------------------------------------------------------------------------

def run(
    project: str,
    dec_min: float,
    dec_max: float,
    ra_min: float = None,
    ra_max: float = None,
    catalog: str = DEFAULT_CATALOG,
    z_min: float = 2.0,
    z_max: float = 3.5,
    column_map: dict = None,
) -> dict:
    """
    Broad-sky rectangle query against a VizieR catalog using column constraints.
    Replaces the positional cone search with direct column filtering.
    """
    col_map = column_map or MILLIQUAS_COLUMN_MAP
    params = {
        "mode": "rectangle",
        "database": "vizier",
        "catalog": catalog,
        "dec_min": dec_min,
        "dec_max": dec_max,
        "ra_min": ra_min,
        "ra_max": ra_max,
        "z_min": z_min,
        "z_max": z_max,
    }

    db.ensure_schema(project)
    if db.has_been_queried(project, "vizier", params):
        out = {"cached": True, "new_sources": 0, "raw_count": 0}
        print(json.dumps(out))
        return out

    from astroquery.vizier import Vizier

    # VizieR range constraint syntax: "min..max"
    # Column names must match the catalog's actual VizieR column names (RAJ2000/DEJ2000/z for VII/294).
    constraints = {
        "DEJ2000": f"{dec_min}..{dec_max}",
        "z":       f"{z_min}..{z_max}",
    }
    if ra_min is not None and ra_max is not None:
        constraints["RAJ2000"] = f"{ra_min}..{ra_max}"

    v = Vizier(columns=list(col_map.keys()), row_limit=-1)

    try:
        result_list = v.query_constraints(catalog=catalog, **constraints)
    except Exception as e:
        db.record_query(project, "vizier", params, result_count=0)
        out = {"cached": False, "new_sources": 0, "raw_count": 0, "error": str(e)}
        print(json.dumps(out))
        return out

    if not result_list or len(result_list) == 0:
        db.record_query(project, "vizier", params, result_count=0)
        out = {"cached": False, "new_sources": 0, "raw_count": 0}
        print(json.dumps(out))
        return out

    result = result_list[0]
    raw_count = len(result)
    existing = _existing_coords(project)
    new_sources = _insert_rows(project, result, catalog, existing)
    db.record_query(project, "vizier", params, result_count=raw_count)

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
    catalog: str = DEFAULT_CATALOG,
    z_min: float = 2.0,
    z_max: float = 3.5,
    column_map: dict = None,
) -> dict:
    """Single cone query. Use for specific scheduled fields."""
    col_map = column_map or MILLIQUAS_COLUMN_MAP
    params = {
        "mode": "cone",
        "database": "vizier",
        "catalog": catalog,
        "ra": ra_center,
        "dec": dec_center,
        "radius_deg": radius_deg,
        "z_min": z_min,
        "z_max": z_max,
    }

    db.ensure_schema(project)
    if db.has_been_queried(project, "vizier", params):
        out = {"cached": True, "new_sources": 0, "raw_count": 0}
        print(json.dumps(out))
        return out

    from astroquery.vizier import Vizier
    from astropy.coordinates import SkyCoord
    import astropy.units as u

    v = Vizier(columns=list(col_map.keys()), row_limit=-1)
    coord = SkyCoord(ra=ra_center, dec=dec_center, unit="deg")

    try:
        result_list = v.query_region(coord, radius=radius_deg * u.deg, catalog=catalog)
    except Exception as e:
        db.record_query(project, "vizier", params, result_count=0)
        out = {"cached": False, "new_sources": 0, "raw_count": 0, "error": str(e)}
        print(json.dumps(out))
        return out

    if not result_list or len(result_list) == 0:
        db.record_query(project, "vizier", params, result_count=0)
        out = {"cached": False, "new_sources": 0, "raw_count": 0}
        print(json.dumps(out))
        return out

    result = result_list[0]

    # Filter z range post-query (cone mode gets all z from VizieR)
    # Use lowercase "z" — the actual column name in VII/294.
    from astropy.table import Table
    mask = (result["z"] >= z_min) & (result["z"] <= z_max)
    result = result[mask]

    raw_count = len(result)
    existing = _existing_coords(project)
    new_sources = _insert_rows(project, result, catalog, existing)
    db.record_query(project, "vizier", params, result_count=raw_count)

    out = {"cached": False, "new_sources": new_sources, "raw_count": raw_count}
    print(json.dumps(out))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Query VizieR/Milliquas QSO catalog (rectangle or cone mode)"
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--catalog", default=DEFAULT_CATALOG)
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
            catalog=args.catalog,
            z_min=args.z_min,
            z_max=args.z_max,
        )
    elif args.ra is not None and args.dec is not None and args.radius is not None:
        run_cone(
            project=args.project,
            ra_center=args.ra,
            dec_center=args.dec,
            radius_deg=args.radius,
            catalog=args.catalog,
            z_min=args.z_min,
            z_max=args.z_max,
        )
    else:
        parser.error(
            "Provide either --dec-min/--dec-max (rectangle) "
            "or --ra/--dec/--radius (cone)"
        )
