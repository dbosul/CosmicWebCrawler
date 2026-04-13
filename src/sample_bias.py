"""
sample_bias.py — Compute selection bias metrics for the current sample.

Metrics reported:
  - Redshift distribution (mean, std, median, histogram)
  - UV luminosity distribution (if available; uv_luminosity column must be in log10(L/erg/s))
  - Spatial coverage (convex hull area in sq deg, cos(Dec)-corrected)
  - Catalog origin breakdown
  - Luminosity bias flag (>80% within 1 dex of brightest, in log space)

bias_weight is set to 1/N_bin — an equalisation weight over the redshift distribution.
This is NOT a 1/Vmax correction (which requires the luminosity function and survey
selection function). Do not describe these weights as 1/Vmax in any publication.

Usage:
    python src/sample_bias.py --project <name>
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db


def run(project: str) -> dict:
    sources = db.get_all_sources(project)
    accepted = [s for s in sources if s["status"] in ("accepted", "candidate")]

    if not accepted:
        result = {"n_sources": 0, "metrics": {}}
        print(json.dumps(result))
        return result

    import numpy as np

    redshifts = np.array([s["z"] for s in accepted if s.get("z") is not None])
    uv_lums = np.array([s["uv_luminosity"] for s in accepted if s.get("uv_luminosity") is not None])

    metrics = {}

    # Redshift distribution
    if len(redshifts) > 0:
        z_hist, z_edges = np.histogram(redshifts, bins=min(10, len(redshifts)))
        metrics["z_distribution"] = {
            "mean": float(np.mean(redshifts)),
            "std": float(np.std(redshifts)),
            "median": float(np.median(redshifts)),
            "histogram": z_hist.tolist(),
            "bin_edges": z_edges.tolist(),
        }

        # Redshift equalisation weights (1/N_bin).
        # Corrects for uneven sampling of the redshift distribution only.
        # This is NOT a 1/Vmax luminosity correction.
        bin_indices = np.clip(np.digitize(redshifts, z_edges[:-1]) - 1, 0, len(z_hist) - 1)
        bin_counts = np.bincount(bin_indices, minlength=len(z_hist))
        for i, source in enumerate([s for s in accepted if s.get("z") is not None]):
            bin_idx = bin_indices[i]
            n_in_bin = bin_counts[bin_idx]
            weight = 1.0 / max(n_in_bin, 1)
            db.update_source_bias_weight(project, source["id"], float(weight))

    # UV luminosity distribution
    # uv_luminosity must be stored as log10(L_UV / erg/s). The "- 1.0" threshold
    # below is a 1 dex cut in log space. If values are linear, this metric is meaningless.
    if len(uv_lums) > 0:
        metrics["uv_lum_distribution"] = {
            "mean_log": float(np.mean(uv_lums)),
            "std_log": float(np.std(uv_lums)),
            "p25_log": float(np.percentile(uv_lums, 25)),
            "p75_log": float(np.percentile(uv_lums, 75)),
            "units": "log10(L_UV / erg/s)",
        }
        fraction_within_1dex = float(np.mean(uv_lums >= np.max(uv_lums) - 1.0))
        metrics["luminosity_bias_flag"] = fraction_within_1dex > 0.8
        metrics["luminosity_bias_fraction"] = fraction_within_1dex
        metrics["luminosity_bias_note"] = (
            "Fraction of sample within 1 dex of brightest source (in log L_UV). "
            ">0.8 indicates strong luminosity selection."
        )
    else:
        metrics["luminosity_bias_flag"] = None

    # Spatial coverage via convex hull (cos(Dec)-corrected)
    # RA is compressed by cos(Dec) on the sky — correct before computing area.
    # Valid for small fields (<~10 deg); for larger fields use proper spherical geometry.
    ras = np.array([s["ra"] for s in accepted])
    decs = np.array([s["dec"] for s in accepted])
    if len(accepted) >= 3:
        try:
            from scipy.spatial import ConvexHull
            mean_dec_rad = np.deg2rad(np.mean(decs))
            ra_corrected = ras * np.cos(mean_dec_rad)
            points = np.column_stack([ra_corrected, decs])
            hull = ConvexHull(points)
            # hull.volume = enclosed area for 2D input (scipy naming convention)
            metrics["spatial_coverage_deg2"] = float(hull.volume)
        except Exception:
            metrics["spatial_coverage_deg2"] = None
    else:
        metrics["spatial_coverage_deg2"] = None

    # Catalog origin breakdown
    z_source_counts = {}
    for s in accepted:
        src = s.get("z_source") or "unknown"
        z_source_counts[src] = z_source_counts.get(src, 0) + 1
    metrics["catalog_origin"] = z_source_counts

    result = {"n_sources": len(accepted), "metrics": metrics}
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    run(project=args.project)
