"""
plot_sample_bias.py — Generate a 4-panel bias figure for the sample report.

Produces a single PDF figure with:
  Panel A: Redshift distribution (sample vs parent)
  Panel B: M_i(z=2) distribution (sample vs parent)
  Panel C: Radio-loud fraction (FIRST > 1 mJy)
  Panel D: BAL QSO fraction (BI_CIV > 0)

Output is a vector PDF suitable for direct inclusion in AASTeX via \\includegraphics.

Usage:
    python src/plot_sample_bias.py --project <name>
Output:
    projects/<project>/products/bias_figure.pdf
    JSON to stdout: {"figure_path": "...", "panels": [...]}
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db
from sample_bias import RADIO_LOUD_THRESHOLD_MJY, BAL_THRESHOLD_KMS


def _wilson_interval(k: int, n: int, z: float = 1.0) -> tuple:
    """Wilson score interval for a binomial proportion at z sigma (default 1σ)."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = (z / denom) * (p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5
    return max(0.0, centre - half), min(1.0, centre + half)


def run(project: str) -> dict:
    try:
        import matplotlib
        matplotlib.use("Agg")  # non-interactive backend
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import numpy as np
    except ImportError:
        out = {"error": "matplotlib_unavailable"}
        print(json.dumps(out))
        return out

    db.ensure_schema(project)
    all_sources = db.get_all_sources(project)
    parent = [s for s in all_sources if s.get("z_source") == "SDSS_DR17"]
    sample = [s for s in all_sources if s.get("status") == "accepted"]

    if len(sample) < 2:
        out = {"error": "insufficient_data", "n_sample": len(sample)}
        print(json.dumps(out))
        return out

    # Colours: sample = solid blue, parent = hatched grey
    C_SAMPLE = "#2166ac"
    C_PARENT = "#d1d1d1"
    C_PARENT_EDGE = "#888888"

    # Apply paper style if available, fall back gracefully
    for style in ("seaborn-v0_8-paper", "seaborn-paper", "default"):
        try:
            plt.style.use(style)
            break
        except OSError:
            continue

    fig, axes = plt.subplots(2, 2, figsize=(7.0, 5.5))
    fig.subplots_adjust(hspace=0.45, wspace=0.38)

    # ------------------------------------------------------------------ #
    # Panel A — Redshift distribution
    # ------------------------------------------------------------------ #
    ax = axes[0, 0]
    sample_z = np.array([s["z"] for s in sample if s.get("z") is not None])
    parent_z = np.array([s["z"] for s in parent if s.get("z") is not None])

    z_min = min(parent_z.min(), sample_z.min()) if len(parent_z) and len(sample_z) else 2.0
    z_max = max(parent_z.max(), sample_z.max()) if len(parent_z) and len(sample_z) else 3.5
    bins = np.arange(z_min, z_max + 0.1, 0.1)

    if len(parent_z):
        ax.hist(parent_z, bins=bins, density=True, color=C_PARENT,
                edgecolor=C_PARENT_EDGE, label=f"Parent ($N={len(parent_z)}$)", zorder=1)
    if len(sample_z):
        ax.hist(sample_z, bins=bins, density=True, color=C_SAMPLE, alpha=0.75,
                label=f"Sample ($N={len(sample_z)}$)", zorder=2)

    ax.set_xlabel("Redshift $z$", fontsize=9)
    ax.set_ylabel("Probability density", fontsize=9)
    ax.set_title("Redshift", fontsize=9, fontweight="bold")
    ax.legend(fontsize=7, frameon=False)

    # KS p-value annotation
    if len(sample_z) >= 3 and len(parent_z) >= 3:
        try:
            from scipy.stats import ks_2samp
            _, pval = ks_2samp(sample_z, parent_z)
            ax.annotate(f"KS $p={pval:.2f}$", xy=(0.97, 0.94), xycoords="axes fraction",
                        ha="right", va="top", fontsize=7)
        except ImportError:
            pass

    # ------------------------------------------------------------------ #
    # Panel B — M_i(z=2) distribution
    # ------------------------------------------------------------------ #
    ax = axes[0, 1]
    sample_mi = np.array([s["mi_z2"] for s in sample if s.get("mi_z2") is not None])
    parent_mi = np.array([s["mi_z2"] for s in parent if s.get("mi_z2") is not None])

    if len(parent_mi) and len(sample_mi):
        mi_min = min(parent_mi.min(), sample_mi.min())
        mi_max = max(parent_mi.max(), sample_mi.max())
        bins_mi = np.linspace(mi_min - 0.1, mi_max + 0.1, 20)

        ax.hist(parent_mi, bins=bins_mi, density=True, color=C_PARENT,
                edgecolor=C_PARENT_EDGE, label=f"Parent ($N={len(parent_mi)}$)", zorder=1)
        ax.hist(sample_mi, bins=bins_mi, density=True, color=C_SAMPLE, alpha=0.75,
                label=f"Sample ($N={len(sample_mi)}$)", zorder=2)

        if len(sample_mi) >= 3 and len(parent_mi) >= 3:
            try:
                from scipy.stats import ks_2samp
                _, pval = ks_2samp(sample_mi, parent_mi)
                ax.annotate(f"KS $p={pval:.2f}$", xy=(0.97, 0.94), xycoords="axes fraction",
                            ha="right", va="top", fontsize=7)
            except ImportError:
                pass
    else:
        ax.text(0.5, 0.5, "Insufficient $M_i$ data", transform=ax.transAxes,
                ha="center", va="center", fontsize=8)

    ax.invert_xaxis()  # brighter (more negative) magnitudes to the right
    ax.set_xlabel("$M_i(z=2)$", fontsize=9)
    ax.set_ylabel("Probability density", fontsize=9)
    ax.set_title("UV luminosity", fontsize=9, fontweight="bold")
    ax.legend(fontsize=7, frameon=False)

    # ------------------------------------------------------------------ #
    # Panel C — Radio-loud fraction
    # ------------------------------------------------------------------ #
    ax = axes[1, 0]

    def _radio_loud_stats(sources):
        with_first = [s for s in sources if s.get("first_flux") is not None]
        n_loud = sum(1 for s in with_first if s["first_flux"] > RADIO_LOUD_THRESHOLD_MJY)
        n = len(with_first)
        frac = n_loud / n if n > 0 else 0.0
        lo, hi = _wilson_interval(n_loud, n)
        return frac, lo, hi, n

    s_frac, s_lo, s_hi, s_n = _radio_loud_stats(sample)
    p_frac, p_lo, p_hi, p_n = _radio_loud_stats(parent)

    x = [0, 1]
    fracs = [s_frac, p_frac]
    yerr_lo = [s_frac - s_lo, p_frac - p_lo]
    yerr_hi = [s_hi - s_frac, p_hi - p_frac]
    colors = [C_SAMPLE, C_PARENT]
    labels = [f"Sample\n($N={s_n}$)", f"Parent\n($N={p_n}$)"]
    bars = ax.bar(x, fracs, color=colors, edgecolor=["#154b80", C_PARENT_EDGE], width=0.5)
    ax.errorbar(x, fracs, yerr=[yerr_lo, yerr_hi], fmt="none", color="k",
                capsize=4, linewidth=1.2, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("Fraction", fontsize=9)
    ax.set_title(f"Radio-loud (FIRST $>{RADIO_LOUD_THRESHOLD_MJY:.0f}$ mJy)",
                 fontsize=9, fontweight="bold")
    ax.set_ylim(0, min(1.0, max(s_frac, p_frac) * 2.2 + 0.05))

    # ------------------------------------------------------------------ #
    # Panel D — BAL QSO fraction
    # ------------------------------------------------------------------ #
    ax = axes[1, 1]

    def _bal_stats(sources):
        with_biciv = [s for s in sources if s.get("bi_civ") is not None]
        n_bal = sum(1 for s in with_biciv if s["bi_civ"] > BAL_THRESHOLD_KMS)
        n = len(with_biciv)
        frac = n_bal / n if n > 0 else 0.0
        lo, hi = _wilson_interval(n_bal, n)
        return frac, lo, hi, n

    s_frac, s_lo, s_hi, s_n = _bal_stats(sample)
    p_frac, p_lo, p_hi, p_n = _bal_stats(parent)

    fracs = [s_frac, p_frac]
    yerr_lo = [s_frac - s_lo, p_frac - p_lo]
    yerr_hi = [s_hi - s_frac, p_hi - p_frac]
    labels = [f"Sample\n($N={s_n}$)", f"Parent\n($N={p_n}$)"]
    ax.bar(x, fracs, color=colors, edgecolor=["#154b80", C_PARENT_EDGE], width=0.5)
    ax.errorbar(x, fracs, yerr=[yerr_lo, yerr_hi], fmt="none", color="k",
                capsize=4, linewidth=1.2, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("Fraction", fontsize=9)
    ax.set_title("BAL QSO ($\\mathrm{BI_{CIV}} > 0$)", fontsize=9, fontweight="bold")
    ax.set_ylim(0, min(1.0, max(s_frac, p_frac) * 2.2 + 0.05))

    # ------------------------------------------------------------------ #
    # Save
    # ------------------------------------------------------------------ #
    out_dir = Path("projects") / project / "products"
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_path = out_dir / "bias_figure.pdf"
    fig.savefig(str(fig_path), bbox_inches="tight", dpi=150)
    plt.close(fig)

    out = {
        "figure_path": str(fig_path),
        "panels": ["z_distribution", "mi_z2_distribution", "radio_loud_fraction", "bal_fraction"],
    }
    print(json.dumps(out))
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate sample bias figure")
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    run(args.project)
