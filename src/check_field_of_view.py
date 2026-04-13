"""
check_field_of_view.py — Check for bright stars and foreground objects in instrument FoV.

Queries SIMBAD for stars brighter than a magnitude limit within the instrument's field of view,
and NED for foreground galaxies (z < 0.5) that could contaminate IFU observations.

Usage:
    python src/check_field_of_view.py --project <name> [--instrument KCWI] [--source-ids 1,2,3]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

# FoV search radii: half-diagonal of slicer footprint
# KCWI slicers (Morrissey et al. 2018, ApJ 864, 93):
#   small:  8.4" x 20.4" → half-diagonal ~11.1"
#   medium: 16.5" x 20.4" → half-diagonal ~13.2"
#   large:  33.1" x 20.4" → half-diagonal ~19.3"; use 20" to be safe
# PCWI 40"x60" → half-diagonal ~36"; use 40"
FOV_RADIUS_ARCSEC = {
    "KCWI": 20.0,   # large slicer half-diagonal
    "KCWI_MED": 14.0,
    "KCWI_SMALL": 12.0,
    "PCWI": 40.0,
}
# V < 12: star within primary IFU footprint causes PSF wing + scattered light contamination
# that degrades continuum subtraction in Lya emission searches. V < 9 would only catch
# stars bright enough to saturate the detector; most damaging contamination is V 9-12.
BRIGHT_STAR_LIMIT = 12.0  # V mag


def run(project: str, source_ids: list = None, instrument: str = "KCWI") -> dict:
    radius_arcsec = FOV_RADIUS_ARCSEC.get(instrument, FOV_RADIUS_ARCSEC["KCWI"])
    radius_deg = radius_arcsec / 3600.0

    if source_ids:
        sources = [db.get_source(project, sid) for sid in source_ids]
        sources = [s for s in sources if s is not None]
    else:
        # Check all non-rejected candidates
        all_sources = db.get_all_sources(project)
        sources = [s for s in all_sources if s["status"] not in ("rejected",)]

    if not sources:
        result = {"checked": 0, "flagged_bright_star": 0, "flagged_foreground": 0}
        print(json.dumps(result))
        return result

    from astroquery.simbad import Simbad
    from astroquery.ipac.ned import Ned
    from astropy.coordinates import SkyCoord
    import astropy.units as u

    simbad = Simbad()
    simbad.add_votable_fields("V", "otype")  # astroquery >= 0.4.8: "V" → column "V"
    simbad.TIMEOUT = 30

    flagged_bright_star = 0
    flagged_foreground = 0

    for source in sources:
        new_flags = []
        coord = SkyCoord(ra=source["ra"], dec=source["dec"], unit="deg")

        # --- Bright star check ---
        try:
            star_result = simbad.query_region(coord, radius=radius_deg * u.deg)
            if star_result is not None:
                for row in star_result:
                    # astroquery SIMBAD >= 0.4.8 returns lowercase column names
                    otype = str(row["otype"]).strip().rstrip("?")
                    # SIMBAD star otypes: '*' (star), 'V*' (variable), 'PM*', etc.
                    if not (otype == "*" or otype.endswith("*") or otype.startswith("*")):
                        continue
                    try:
                        v_mag = float(row["V"])
                        if v_mag < BRIGHT_STAR_LIMIT:
                            new_flags.append("bright_star_contamination")
                            flagged_bright_star += 1
                            break
                    except (TypeError, ValueError):
                        continue
        except Exception:
            pass  # Network failure — don't penalize the source

        # --- Foreground galaxy check ---
        try:
            ned_result = Ned.query_region(coord, radius=radius_deg * u.deg)
            if ned_result is not None:
                for row in ned_result:
                    z_fg = row["Redshift"]
                    if z_fg is not None and 0.0 < float(z_fg) < 0.5:
                        obj_type = str(row["Type"]).strip()
                        if "G" in obj_type:  # NED galaxy type codes include 'G'
                            new_flags.append("foreground_galaxy")
                            flagged_foreground += 1
                            break
        except Exception:
            pass

        if new_flags:
            db.update_source_status(project, source["id"], source["status"], new_flags)

    result = {
        "checked": len(sources),
        "flagged_bright_star": flagged_bright_star,
        "flagged_foreground": flagged_foreground,
        "instrument": instrument,
        "fov_radius_arcsec": radius_arcsec,
    }
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--instrument", default="KCWI", choices=["KCWI", "PCWI"])
    parser.add_argument("--source-ids", type=str, default=None)
    args = parser.parse_args()

    ids = [int(x) for x in args.source_ids.split(",")] if args.source_ids else None
    run(project=args.project, source_ids=ids, instrument=args.instrument)
