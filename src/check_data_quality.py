"""
check_data_quality.py — Cross-source consistency and sanity checks on candidates.

Checks:
  - Redshift plausibility (1.5 <= z <= 5.0)
  - Photometry completeness (u_mag < 23.5 for SDSS detection limit)
  - Cross-source z consistency (flag z_conflict if |delta_z| > 0.05 between sources)

Usage:
    python src/check_data_quality.py --project <name> [--source-ids 1,2,3]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

Z_MIN_PLAUSIBLE = 1.5
Z_MAX_PLAUSIBLE = 5.0
# Spectroscopic redshift conflicts at z~2-3: pipelines agree to Δz < 0.01 for clean spectra.
# 0.05 is too lenient — use 0.01 for spectroscopic consistency check.
Z_CONFLICT_THRESHOLD = 0.01
# Positional match for same-object dedup: 1.5 arcsec (conservative for SDSS astrometry ~0.1")
# 5 arcsec was too large — could confuse distinct QSOs in lensing systems
Z_CONFLICT_MATCH_ARCSEC = 1.5
# u_mag quality check only applied to SDSS sources (z_source = SDSS_DR17)
# Milliquas Bmag is heterogeneous — do not apply SDSS limit to it
SDSS_U_MAG_LIMIT = 22.0  # SDSS spectroscopic u-band completeness (not photometric 23.5)


def run(project: str, source_ids: list = None) -> dict:
    if source_ids:
        sources = [db.get_source(project, sid) for sid in source_ids]
        sources = [s for s in sources if s is not None]
    else:
        sources = db.get_sources_by_status(project, "candidate")

    if not sources:
        result = {"checked": 0, "flagged": 0, "rejected": 0}
        print(json.dumps(result))
        return result

    from astropy.coordinates import SkyCoord
    import astropy.units as u

    # Build spatial index for cross-match
    coords = SkyCoord(
        ra=[s["ra"] for s in sources],
        dec=[s["dec"] for s in sources],
        unit="deg",
    )

    flagged = 0
    rejected = 0

    for i, source in enumerate(sources):
        new_flags = []
        new_status = source["status"]

        # Redshift plausibility
        z = source.get("z")
        if z is None or not (Z_MIN_PLAUSIBLE <= z <= Z_MAX_PLAUSIBLE):
            new_flags.append("z_implausible")
            new_status = "rejected"
            rejected += 1

        # Photometry check — only for SDSS sources with genuine u-band measurements
        if source.get("z_source") == "SDSS_DR17":
            u_mag = source.get("u_mag")
            if u_mag is not None and u_mag > SDSS_U_MAG_LIMIT:
                new_flags.append("faint_u")

        # Cross-source z consistency — find nearby sources (within 1.5 arcsec)
        # Tight match to avoid confusing distinct QSOs in projection / lensing systems
        if z is not None:
            source_coord = SkyCoord(ra=source["ra"], dec=source["dec"], unit="deg")
            seps = source_coord.separation(coords)
            nearby_indices = [
                j for j, sep in enumerate(seps)
                if sep.arcsec < Z_CONFLICT_MATCH_ARCSEC and j != i
            ]
            for j in nearby_indices:
                other_z = sources[j].get("z")
                if other_z is not None and abs(z - other_z) > Z_CONFLICT_THRESHOLD:
                    new_flags.append("z_conflict")
                    break

        if new_flags:
            db.update_source_status(project, source["id"], new_status, new_flags)
            flagged += 1
        elif new_status != source["status"]:
            db.update_source_status(project, source["id"], new_status)

    result = {"checked": len(sources), "flagged": flagged, "rejected": rejected}
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--source-ids", type=str, default=None,
                        help="Comma-separated list of source IDs")
    args = parser.parse_args()

    ids = [int(x) for x in args.source_ids.split(",")] if args.source_ids else None
    run(project=args.project, source_ids=ids)
