"""
fetch_cutouts.py — Download optical image thumbnails for accepted sources.

Downloads PS1 (default) color JPEG cutouts for each source at the given status level.
Images are saved to projects/<project>/cutouts/<survey>/ and named
source_<id>_<sanitized_name>.jpg.

Idempotent: skips sources where the output file already exists.
Use --force to re-fetch.

Usage:
    python src/fetch_cutouts.py --project cosmos-pilot
    python src/fetch_cutouts.py --project cosmos-pilot --survey ps1 --size 60 --force
    python src/fetch_cutouts.py --project cosmos-pilot --status candidate
"""

import argparse
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

# PS1 pixel scale arcsec/px
PS1_PIXSCALE = 0.25
# SDSS pixel scale arcsec/px
SDSS_PIXSCALE = 0.396


def sanitize_name(name: str) -> str:
    """Make a source name safe for use in a filename. Truncated to 50 chars."""
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    return safe[:50]


def fetch_ps1_cutout(
    ra: float,
    dec: float,
    size_arcsec: float,
    output_path: Path,
) -> tuple[bool, str]:
    """
    Download a PS1 gri color JPEG for the given position.

    Two-step: first calls ps1filenames.py to get stack image filenames,
    then calls fitscut.cgi for the color composite.

    Returns (success, error_msg). error_msg is 'no_coverage' if PS1 has
    no stack imaging at this position.
    """
    filenames_url = (
        "https://ps1images.stsci.edu/cgi-bin/ps1filenames.py"
        f"?ra={ra}&dec={dec}&filters=gri"
    )
    try:
        with urllib.request.urlopen(filenames_url, timeout=15) as resp:
            content = resp.read().decode("utf-8")
    except Exception as exc:
        return False, f"ps1filenames.py request failed: {exc}"

    # Response is tab-separated; first line is header
    lines = [ln for ln in content.strip().splitlines() if ln and not ln.startswith("#")]
    if len(lines) < 2:
        return False, "no_coverage"

    headers = lines[0].split()
    band_files: dict[str, str] = {}
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= len(headers):
            row = dict(zip(headers, parts))
            band = row.get("filter", "")
            filename = row.get("filename", "")
            if band and filename:
                band_files[band] = filename

    if not band_files:
        return False, "no_coverage"

    size_px = max(1, int(size_arcsec / PS1_PIXSCALE))
    params: dict[str, object] = {
        "ra": ra,
        "dec": dec,
        "size": size_px,
        "format": "jpeg",
        "autoscale": "99.5",
    }

    # gri color composite if all three bands available, else single-band
    if all(b in band_files for b in ("g", "r", "i")):
        params["red"] = band_files["i"]
        params["green"] = band_files["r"]
        params["blue"] = band_files["g"]
    else:
        band = next(iter(band_files))
        params["red"] = band_files[band]

    cutout_url = (
        "https://ps1images.stsci.edu/cgi-bin/fitscut.cgi?"
        + urllib.parse.urlencode(params)
    )

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(cutout_url, timeout=30) as resp:
            data = resp.read()
        if len(data) < 500:
            return False, f"suspiciously small response ({len(data)} bytes) — likely no coverage"
        output_path.write_bytes(data)
        return True, ""
    except Exception as exc:
        return False, f"fitscut.cgi request failed: {exc}"


def fetch_sdss_cutout(
    ra: float,
    dec: float,
    size_arcsec: float,
    output_path: Path,
) -> tuple[bool, str]:
    """
    Download an SDSS DR17 color JPEG cutout.
    Returns (success, error_msg).
    """
    size_px = min(2048, max(1, int(size_arcsec / SDSS_PIXSCALE)))
    url = (
        "https://skyserver.sdss.org/dr17/SkyServerWS/ImgCutout/getjpeg"
        f"?ra={ra}&dec={dec}&scale={SDSS_PIXSCALE}&width={size_px}&height={size_px}&opt="
    )
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read()
        if len(data) < 500:
            return False, f"suspiciously small SDSS response ({len(data)} bytes)"
        output_path.write_bytes(data)
        return True, ""
    except Exception as exc:
        return False, f"SDSS request failed: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument(
        "--status",
        default="accepted",
        help="Source status to fetch thumbnails for (default: accepted)",
    )
    parser.add_argument(
        "--survey",
        default="ps1",
        choices=["ps1", "sdss"],
        help="Image survey (default: ps1). PS1 automatically falls back to SDSS on no-coverage.",
    )
    parser.add_argument(
        "--size",
        type=float,
        default=60.0,
        help="Cutout size in arcseconds (default: 60)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch even if the output file already exists",
    )
    args = parser.parse_args()

    db.ensure_schema(args.project)
    sources = db.get_sources_by_status(args.project, args.status)

    if not sources:
        print(f"No sources with status='{args.status}' found in project '{args.project}'.")
        return

    cutout_dir = Path("projects") / args.project / "cutouts" / args.survey
    cutout_dir.mkdir(parents=True, exist_ok=True)

    ok = failed = skipped = 0

    for src in sources:
        safe = sanitize_name(src["name"])
        filename = f"source_{src['id']}_{safe}.jpg"
        output_path = cutout_dir / filename

        if output_path.exists() and not args.force:
            print(f"  skip  {src['name']} (already downloaded)")
            skipped += 1
            continue

        ra, dec = src["ra"], src["dec"]

        if args.survey == "ps1":
            success, err = fetch_ps1_cutout(ra, dec, args.size, output_path)
            if not success and err == "no_coverage":
                print(f"  PS1 no coverage for {src['name']}, trying SDSS fallback…")
                # Save to sdss subdir instead
                sdss_path = (
                    Path("projects") / args.project / "cutouts" / "sdss" / filename
                )
                success, err = fetch_sdss_cutout(ra, dec, args.size, sdss_path)
                if success:
                    output_path = sdss_path
        else:
            success, err = fetch_sdss_cutout(ra, dec, args.size, output_path)

        if success:
            print(f"  ok    {src['name']} → {output_path}")
            ok += 1
        else:
            print(f"  FAIL  {src['name']}: {err}", file=sys.stderr)
            failed += 1

        time.sleep(0.5)  # be a good citizen on shared API infrastructure

    print(f"\nDone: {ok} fetched, {skipped} skipped, {failed} failed.")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
