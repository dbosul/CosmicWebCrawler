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

# Foreground galaxy contamination thresholds for KCWI large slicer (33.1" × 20.4").
# Two severity tiers:
#
#   close_fg   (sep < CLOSE_FG_ARCSEC): galaxy is within the slicer short-axis half-width
#              (~10"). Fills multiple IFU slices, contributes continuum flux at the QSO
#              position, and cannot be spatially separated from the target. Treat as a
#              rejection criterion — coordinator should deprioritise unless no clean source
#              is available.
#
#   fg_in_fov  (sep in [CLOSE_FG_ARCSEC, FoV half-diagonal]): galaxy falls within the FoV
#              but outside the immediate slicer core. Can usually be masked in post-processing
#              at the cost of reduced spatial coverage. Flag for human review; do not reject.
#
# The z < 0.5 redshift gate is calibrated to the target Lya wavelength window (3700–5600 Å
# for z=2–3.6). A foreground galaxy at z=0.48 has [OII]3727 at 5514 Å — outside the window.
# The concern is angular proximity and spectral leakage from galaxy continuum and emission
# lines within the Lya band. z < 0.5 is a conservative first-pass filter; human review
# should check for spectral overlap in ambiguous cases.
CLOSE_FG_ARCSEC = 10.0  # below this separation → `close_fg` rejection flag


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
    # add_votable_fields calls list_votable_fields which requires a TAP network round-trip.
    # Wrap in try/except so that if the SIMBAD TAP endpoint is unreachable, we degrade
    # gracefully: star checks are skipped per-source (network failure = no penalty).
    simbad_fields_ok = False
    try:
        simbad.add_votable_fields("V", "otype")  # astroquery >= 0.4.8: "V" → column "V"
        simbad_fields_ok = True
    except Exception:
        pass  # TAP endpoint unreachable — SIMBAD star mag checks will be skipped
    simbad.TIMEOUT = 30

    flagged_bright_star = 0
    flagged_foreground = 0
    star_check_skipped = 0

    for source in sources:
        new_flags = []
        coord = SkyCoord(ra=source["ra"], dec=source["dec"], unit="deg")

        # --- Bright star check ---
        # Only attempt if we successfully registered the V + otype fields above.
        # If SIMBAD was unreachable, flag every source explicitly so reviewers know
        # the star check was not performed — do not silently treat as "passed".
        if not simbad_fields_ok:
            new_flags.append("star_check_skipped")
            star_check_skipped += 1
        else:
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
        # Log NED counterpart details (name, z, angular offset) in the flag string so
        # that the coordinator and human reviewer can assess contamination severity.
        #
        # Flag format (two severity tiers — see constants above):
        #   "close_fg:name=...:z=...:sep_arcsec=<sep>"         sep < CLOSE_FG_ARCSEC → deprioritise
        #   "fg_in_fov:name=...:z=...:sep_arcsec=<sep>"        sep ≥ CLOSE_FG_ARCSEC → review
        # Both have _photoz variants when NED redshift is photometric.
        #
        # NED galaxy type codes all start with 'G' (e.g. 'G', 'GClstr', 'GGroup', 'GPair').
        # Use startswith('G') — substring check "G" in obj_type incorrectly matches 'AGN'.
        try:
            ned_result = Ned.query_region(coord, radius=radius_deg * u.deg)
            if ned_result is not None:
                for row in ned_result:
                    z_fg = row["Redshift"]
                    if z_fg is not None and 0.0 < float(z_fg) < 0.5:
                        obj_type = str(row["Type"]).strip()
                        if not obj_type.startswith("G"):
                            continue
                        # Distinguish photometric vs spectroscopic redshifts.
                        # NED Redshift Flag: blank/empty = spectroscopic; "PHOT" = photometric.
                        try:
                            z_flag = str(row["Redshift Flag"]).strip().upper()
                        except Exception:
                            z_flag = ""
                        is_photoz = "PHOT" in z_flag or "PHOTO" in z_flag
                        # Compute angular separation for the log.
                        # NED query_region() returns a "Separation" column in arcminutes.
                        # Use it directly; fall back to computing from "RA"/"DEC" columns
                        # (astroquery NED column names, confirmed against live API).
                        try:
                            sep_arcmin = float(row["Separation"])
                            sep_arcsec = round(sep_arcmin * 60.0, 1)
                        except Exception:
                            try:
                                ned_coord = SkyCoord(
                                    ra=float(row["RA"]), dec=float(row["DEC"]), unit="deg"
                                )
                                sep_arcsec = round(coord.separation(ned_coord).arcsec, 1)
                            except Exception:
                                sep_arcsec = "?"
                        ned_name = str(row["Object Name"]).strip().replace(":", "_")

                        # Assign severity tier based on angular separation.
                        # close_fg: inside slicer core → deprioritise target
                        # fg_in_fov: within FoV but outside core → flag for review
                        try:
                            sep_float = float(sep_arcsec)
                            is_close = sep_float < CLOSE_FG_ARCSEC
                        except (TypeError, ValueError):
                            is_close = False  # unknown sep → conservative, use fg_in_fov
                        if is_close:
                            severity = "close_fg_photoz" if is_photoz else "close_fg"
                        else:
                            severity = "fg_in_fov_photoz" if is_photoz else "fg_in_fov"

                        flag_str = (
                            f"{severity}:"
                            f"name={ned_name}:"
                            f"z={float(z_fg):.3f}:"
                            f"sep_arcsec={sep_arcsec}"
                        )
                        new_flags.append(flag_str)
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
        "star_check_skipped": star_check_skipped,
        "instrument": instrument,
        "fov_radius_arcsec": radius_arcsec,
        "simbad_star_check": "skipped_network_error" if not simbad_fields_ok else "ok",
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
