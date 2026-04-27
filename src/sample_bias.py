"""
sample_bias.py — Characterise selection bias vs. the parent DR17Q population.

Compares accepted sources against all SDSS DR17Q sources in the same footprint and
redshift range (the parent population, stored in the DB regardless of cut status).
Reports KS tests on redshift and UV luminosity distributions, radio-loud fraction
(FIRST > 1 mJy), and BAL QSO fraction (BI_CIV > 0).

Also computes redshift equalization weights (1/N_bin) for downstream use.

Usage:
    python src/sample_bias.py --project <name>

Output: JSON to stdout with keys: n_sample, n_parent, redshift, mi_z2, radio_loud, bal
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

# Radio-loud threshold: FIRST peak flux > 1 mJy (standard FIRST sensitivity floor).
# Sources with first_flux IS NULL are outside the FIRST footprint — excluded from fraction.
RADIO_LOUD_THRESHOLD_MJY = 1.0

# BAL threshold: BI_CIV > 0 km/s (Weymann+1991 definition).
# Sources with bi_civ IS NULL were not measured — excluded from fraction.
BAL_THRESHOLD_KMS = 0.0


def _ks_test(a: list, b: list) -> dict:
    """Run a 2-sample KS test. Returns stat, pvalue, or nulls if scipy unavailable."""
    if len(a) < 3 or len(b) < 3:
        return {"ks_stat": None, "ks_pvalue": None, "note": "insufficient_data"}
    try:
        from scipy.stats import ks_2samp
        stat, pval = ks_2samp(a, b)
        return {"ks_stat": round(float(stat), 4), "ks_pvalue": round(float(pval), 4)}
    except ImportError:
        return {"ks_stat": None, "ks_pvalue": None, "note": "scipy_unavailable"}


def _safe_mean(vals: list):
    return round(sum(vals) / len(vals), 4) if vals else None


def _safe_std(vals: list):
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    variance = sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)
    return round(variance ** 0.5, 4)


def _fraction_stats(sources: list, key: str, threshold: float) -> dict:
    """
    Compute fraction of sources where source[key] > threshold.
    Sources where key is None are excluded (outside survey footprint or unmeasured).
    """
    with_data = [s for s in sources if s.get(key) is not None]
    above = [s for s in with_data if s[key] > threshold]
    n = len(with_data)
    return {
        "fraction": round(len(above) / n, 4) if n > 0 else None,
        "n_with_data": n,
        "n_above_threshold": len(above),
    }


def _update_bias_weights(project: str, sources: list) -> None:
    """
    Assign 1/N_bin redshift equalization weights to accepted sources.
    Bins of width 0.25 over z=2–5. Sources outside range get weight 1.0.
    NOTE: these are equalization weights, not 1/Vmax corrections. Do not
    describe them as volume-corrected in publications.
    """
    BIN_WIDTH = 0.25
    bin_counts: dict = {}
    for s in sources:
        z = s.get("z")
        if z is None:
            continue
        b = round(int(z / BIN_WIDTH) * BIN_WIDTH, 4)
        bin_counts[b] = bin_counts.get(b, 0) + 1

    for s in sources:
        z = s.get("z")
        if z is None:
            db.update_source_bias_weight(project, s["id"], 1.0)
            continue
        b = round(int(z / BIN_WIDTH) * BIN_WIDTH, 4)
        n = bin_counts.get(b, 1)
        db.update_source_bias_weight(project, s["id"], round(1.0 / n, 6))


def run(project: str) -> dict:
    db.ensure_schema(project)

    all_sources = db.get_all_sources(project)
    # Parent population: all SDSS DR17Q sources regardless of status.
    # These all passed the same footprint+z filter at catalog query time.
    parent = [s for s in all_sources if s.get("z_source") == "SDSS_DR17"]
    # Sample: accepted sources (any catalog origin — SDSS, Milliquas, NED)
    sample = [s for s in all_sources if s.get("status") == "accepted"]

    n_sample = len(sample)
    n_parent = len(parent)

    if n_sample == 0:
        out = {"n_sample": 0, "n_parent": n_parent, "note": "no accepted sources"}
        print(json.dumps(out))
        return out

    _update_bias_weights(project, sample)

    # --- Redshift ---
    sample_z = [s["z"] for s in sample if s.get("z") is not None]
    parent_z = [s["z"] for s in parent if s.get("z") is not None]
    redshift = {
        "sample_mean": _safe_mean(sample_z),
        "sample_std": _safe_std(sample_z),
        "parent_mean": _safe_mean(parent_z),
        "parent_std": _safe_std(parent_z),
        **_ks_test(sample_z, parent_z),
    }

    # --- mi_z2 (UV luminosity, K-corrected to z=2) ---
    sample_mi = [s["mi_z2"] for s in sample if s.get("mi_z2") is not None]
    parent_mi = [s["mi_z2"] for s in parent if s.get("mi_z2") is not None]
    mi_z2 = {
        "sample_mean": _safe_mean(sample_mi),
        "parent_mean": _safe_mean(parent_mi),
        "n_sample_with_data": len(sample_mi),
        "n_parent_with_data": len(parent_mi),
        **_ks_test(sample_mi, parent_mi),
    }

    # --- Radio-loud fraction (FIRST_FLUX > 1 mJy) ---
    rs = _fraction_stats(sample, "first_flux", RADIO_LOUD_THRESHOLD_MJY)
    rp = _fraction_stats(parent, "first_flux", RADIO_LOUD_THRESHOLD_MJY)
    radio_loud = {
        "threshold_mjy": RADIO_LOUD_THRESHOLD_MJY,
        "sample_fraction": rs["fraction"],
        "parent_fraction": rp["fraction"],
        "n_sample_with_first": rs["n_with_data"],
        "n_parent_with_first": rp["n_with_data"],
    }

    # --- BAL QSO fraction (BI_CIV > 0) ---
    bs = _fraction_stats(sample, "bi_civ", BAL_THRESHOLD_KMS)
    bp = _fraction_stats(parent, "bi_civ", BAL_THRESHOLD_KMS)
    bal = {
        "threshold_kms": BAL_THRESHOLD_KMS,
        "sample_fraction": bs["fraction"],
        "parent_fraction": bp["fraction"],
        "n_sample_with_biciv": bs["n_with_data"],
        "n_parent_with_biciv": bp["n_with_data"],
    }

    out = {
        "n_sample": n_sample,
        "n_parent": n_parent,
        "redshift": redshift,
        "mi_z2": mi_z2,
        "radio_loud": radio_loud,
        "bal": bal,
    }
    print(json.dumps(out))
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sample bias assessment vs. parent DR17Q population"
    )
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    run(args.project)
