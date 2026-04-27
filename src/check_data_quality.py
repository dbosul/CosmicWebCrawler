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
# Positional match for z_conflict cross-check: must EXCEED the dedup radius used at insertion.
# query_vizier.py and query_simbad.py dedup at 3.0 arcsec — any two rows within 3" are already
# merged, so a 1.5" match radius can never fire. Use 5.0" to catch cross-catalog pairs that
# survive dedup (e.g. marginally outside 3") without conflating distinct QSOs in lensing (>10").
Z_CONFLICT_MATCH_ARCSEC = 5.0
# u_mag quality check only applied to SDSS sources (z_source = SDSS_DR17)
# Milliquas Bmag is heterogeneous — do not apply SDSS limit to it
SDSS_U_MAG_LIMIT = 22.0  # SDSS spectroscopic u-band completeness (not photometric 23.5)

# KCWI BL throughput floor: below ~3700 Å throughput drops steeply (Morrissey et al. 2018,
# ApJ 864, 93, Fig. 8). Sources where Lyα_obs = 1216 × (1+z) < 3700 Å are at the blue edge
# and may be partially or wholly undetectable. Flag but do not auto-reject — observer can
# adjust grating setting (BM/BH) or accept reduced sensitivity.
KCWI_BL_LYA_MIN_ANGSTROM = 3700.0  # Lyα observed wavelength floor for BL grating

# Science floor for low-surface-brightness Lya nebula science (distinct from the detection
# floor above). KCWI BL throughput at 3700–3900 Å is ~5–30% of peak (Morrissey et al. 2018,
# ApJ 864, 93, Fig. 8). Lya nebulae are faint (SB ~ 10^-18 erg/s/cm²/arcsec²); every
# published KCWI/MUSE halo survey targets Lya above ~3900 Å. Sources in [3700, 3900) Å are
# flagged `lya_blue_edge_science` and should be deprioritised when cleaner alternatives exist.
KCWI_BL_LYA_SCIENCE_FLOOR_ANGSTROM = 3900.0

# ---------------------------------------------------------------------------
# UV proxy band selection
# ---------------------------------------------------------------------------
# Band centers (SDSS): u=3543 Å, g=4770 Å, r=6231 Å
# For a QSO at redshift z, a band with center λ probes rest-frame λ/(1+z).
# The target rest-frame window is ~1400–1600 Å (UV continuum, uncontaminated by Lyα forest).
#
# u-band at z>2: rest-frame < 1181 Å — inside the Lyα forest or below the Lyman break.
#   u-band is therefore UNUSABLE as a UV proxy at any z in the KCWI target range (z=2–3.5).
#
# g-band at z=2.0–2.5: probes 1363–1590 Å ✓
# r-band at z=2.5–3.5: probes 1425–1783 Å ✓
#
# Crossover at z=2.5: g-band center starts entering the Lyα forest (g/3.5 = 1363 Å).
# Above z=2.5, r-band is the cleaner proxy.

_UV_PROXY_ZBREAK = 2.5  # below: g-band; at or above: r-band


def _uv_proxy(z: float, g_mag, r_mag, b_mag=None, mi_z2=None) -> tuple:
    """Return (proxy_mag, band_name) for the appropriate UV proxy band.

    Preferred: mi_z2 (absolute i-band mag K-corrected to z=2, Richards+2006 convention).
    Provided directly by SDSS DR17Q VAC. Already an absolute magnitude — the caller must
    NOT apply _abs_uv_proxy() when band == "mi_z2".

    Fallback band selection (for non-SDSS sources lacking mi_z2):
      z < 2.5: g-band (4770 Å center → rest 1363–1590 Å, above Lyα forest)
      z ≥ 2.5: r-band (6231 Å center → rest 1425–1783 Å)

    Last resort for Milliquas-only sources lacking g/r photometry:
      b_mag (Milliquas Bmag, heterogeneous: SDSS u / APM B / USNO B) labelled "b_het".
      Do not compare directly with mi_z2 or g/r proxies.

    Returns (None, None) if no usable photometry is available.
    """
    if z is None:
        return None, None
    # mi_z2 is the preferred proxy: already K-corrected and absolute. Use it when available.
    if mi_z2 is not None:
        return float(mi_z2), "mi_z2"
    if z < _UV_PROXY_ZBREAK:
        # Preferred: g-band (rest ~1363–1590 Å, above Lyα forest)
        if g_mag is not None:
            return float(g_mag), "g"
        # Fallback: r-band (rest ~1780–2077 Å — redder but consistent SDSS photometry)
        # Better than heterogeneous Milliquas Bmag for ranking purposes.
        if r_mag is not None:
            return float(r_mag), "r"
    else:
        if r_mag is not None:
            return float(r_mag), "r"
        # Do NOT fall back to g-band at z>=2.5: rest-frame g probes <1363 Å (Lyα forest)
    # Last resort: Milliquas Bmag (heterogeneous: SDSS u / APM B / USNO B)
    # Label "b_het" so downstream can distinguish from clean g/r measurements.
    if b_mag is not None:
        return float(b_mag), "b_het"
    return None, None


def _abs_uv_proxy(proxy_mag, z) -> float | None:
    """Absolute UV proxy magnitude using Planck18 distance modulus.

    No K-correction applied — acceptable for ranking/bias purposes over z=2–3.5
    where K-correction variation is ~0.1–0.3 mag, small relative to the ~3 mag
    luminosity spread in a typical QSO sample.

    Returns absolute AB magnitude (negative for luminous QSOs, e.g. −26 to −28).
    Returns None if proxy_mag or z is unavailable.
    """
    if proxy_mag is None or z is None:
        return None
    try:
        from astropy.cosmology import Planck18
        dm = Planck18.distmod(z).value
        return float(proxy_mag) - dm
    except Exception:
        return None


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

        # KCWI BL blue-edge check: Lyα at 1216 × (1+z) Å
        # Two tiers:
        #   lya_blue_edge        — below detection floor (3700 Å): grating may not cover
        #   lya_blue_edge_science — between detection floor and science floor (3700–3900 Å):
        #                          throughput 5–30% of peak, inadequate for low-SB nebula search
        # Neither is auto-rejected; coordinator should deprioritise below science floor.
        if z is not None and new_status != "rejected":
            lya_obs = 1216.0 * (1.0 + z)
            if lya_obs < KCWI_BL_LYA_MIN_ANGSTROM:
                new_flags.append(
                    f"lya_blue_edge:lya_obs={lya_obs:.0f}A"
                    f":kcwi_bl_floor={KCWI_BL_LYA_MIN_ANGSTROM:.0f}A"
                )
            elif lya_obs < KCWI_BL_LYA_SCIENCE_FLOOR_ANGSTROM:
                new_flags.append(
                    f"lya_blue_edge_science:lya_obs={lya_obs:.0f}A"
                    f":kcwi_bl_science_floor={KCWI_BL_LYA_SCIENCE_FLOOR_ANGSTROM:.0f}A"
                )

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

        # Compute UV proxy before writing status — b_het photometry is a flag.
        # Skip sources already rejected in this pass.
        if new_status != "rejected":
            proxy_mag, proxy_band = _uv_proxy(
                z, source.get("g_mag"), source.get("r_mag"),
                b_mag=source.get("b_mag"), mi_z2=source.get("mi_z2"),
            )
            db.update_source_uv_proxy(project, source["id"], proxy_mag, proxy_band)

            # Flag Milliquas-only sources that fell back to heterogeneous Bmag.
            # Milliquas Rmag/Bmag is assembled from SDSS r/u, APM B, USNO R, POSS-E plate
            # scans (Flesch 2023, OJAp 6, 49) — systematic uncertainty 0.1–0.3 mag.
            # Ranking b_het against SDSS g/r at <0.1 mag precision is invalid.
            if proxy_band == "b_het":
                new_flags.append("phot_heterogeneous")

            # Compute absolute UV proxy magnitude for luminosity bias assessment.
            # mi_z2 is already an absolute magnitude (K-corrected to z=2 by SDSS DR17Q VAC) —
            # do NOT apply a distance modulus to it. For g/r/b_het bands (apparent magnitudes),
            # subtract the Planck18 distance modulus to get the absolute value.
            if proxy_band == "mi_z2":
                abs_mag = proxy_mag  # already absolute
            else:
                abs_mag = _abs_uv_proxy(proxy_mag, z)
            if abs_mag is not None:
                db.update_source_uv_luminosity(project, source["id"], abs_mag)
        else:
            proxy_band = None

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
