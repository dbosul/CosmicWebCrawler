---
name: sample-bias
description: Compute selection bias metrics for the current sample and update bias weights
argument-hint: <project>
---

Analyzes the current sample (accepted + candidate sources) and computes:
- Redshift distribution (mean, std, median, histogram)
- UV luminosity distribution and luminosity bias flag
- Spatial coverage (convex hull area in sq deg)
- Catalog origin breakdown (how many sources came from each database)

Also updates `bias_weight` on each source using 1/N_bin weighting by redshift bin
(proxy for 1/Vmax correction).

## Usage

```bash
python src/sample_bias.py --project <project>
```

## Output (JSON to stdout)

```json
{
  "n_sources": 35,
  "metrics": {
    "z_distribution": {"mean": 2.51, "std": 0.38, "median": 2.47, ...},
    "luminosity_bias_flag": true,
    "luminosity_bias_fraction": 0.91,
    "spatial_coverage_deg2": 0.43,
    "catalog_origin": {"SDSS_DR17": 18, "VizieR:VII/290": 12, "SIMBAD": 5}
  }
}
```

## Notes

- `luminosity_bias_flag: true` means >80% of sources are within 1 dex of the brightest
  — this is a warning that the sample is strongly luminosity-selected
- Run after each major batch of queries and after any rejections
- Bias weights are used downstream in stacking and statistical analyses
