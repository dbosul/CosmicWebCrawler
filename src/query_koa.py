"""
query_koa.py — KOA TAP archive search for KCWI data.

Queries the Keck Observatory Archive for KCWI science frames covering accepted
sample sources, matches calibration frames, optionally downloads raw FITS,
and writes results to the project DB.

Usage:
    python src/query_koa.py --project <name> [--source-ids 1 2 3] [--download]
                            [--radius 30.0] [--dest-dir projects/<name>/raw]

The TAP server at koa.ipac.caltech.edu injects a proprietary-period check for
anonymous queries, so all returned rows are publicly downloadable. Do NOT
filter on propint=0 (that only catches ~387 "immediate release" frames;
~35,150 science frames are accessible in total).
"""

import argparse
import csv
import io
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

# Allow running from project root without installing as package
sys.path.insert(0, str(Path(__file__).parent))
import db

KOA_TAP_URL = "https://koa.ipac.caltech.edu/TAP/sync"
KOA_DOWNLOAD_URL = "https://koa.ipac.caltech.edu/cgi-bin/getKOA/nph-getKOA"

# Default cone search radius (arcsec).
# KOA stores the telescope pointing RA/Dec, not the source centroid. In practice
# KCWI pointings can be offset from the target by 20–40 arcsec (IFU placement,
# guide star offsets, dithers). 60" safely captures all frames where the target
# falls within any KCWI IFU footprint (largest slicer: 33"×20.4").
DEFAULT_RADIUS_ARCSEC = 60.0

# Volume warning threshold (GB) — pause before download if estimated volume exceeds this
VOLUME_WARN_GB = 5.0

# Approximate raw FITS size per science frame (MB)
FITS_MB_PER_FRAME = 10.0

# Required calibration types for kcwidrp
REQUIRED_CALIB_TYPES = ("arclamp", "contbars", "flatlamp", "domeflat", "bias")
OPTIONAL_CALIB_TYPES = ("dark", "twiflat")
ALL_CALIB_TYPES = REQUIRED_CALIB_TYPES + OPTIONAL_CALIB_TYPES

# Calibration search window (days either side of science obs_date)
CALIB_WINDOW_DAYS = 3


# ---------------------------------------------------------------------------
# TAP query helpers
# ---------------------------------------------------------------------------

def _tap_query(adql: str, timeout: int = 60) -> list[dict]:
    """Execute an ADQL query against KOA TAP. Returns list of row dicts."""
    resp = requests.get(
        KOA_TAP_URL,
        params={"LANG": "ADQL", "FORMAT": "csv", "QUERY": adql},
        timeout=timeout,
    )
    resp.raise_for_status()
    text = resp.text.strip()
    if not text or text.startswith("ERROR"):
        return []
    reader = csv.DictReader(io.StringIO(text))
    return [dict(r) for r in reader]


def query_science_frames(ra: float, dec: float, radius_arcsec: float) -> list[dict]:
    """
    Blind cone search: return ALL KCWI frames within radius_arcsec of the position.

    No koaimtyp or wavelength filter — the probability of a calibration frame
    landing on a science target without accompanying science frames is negligible,
    and we should not pre-filter on grating setup or wavelength coverage.
    The coordinator decides what is scientifically useful from the returned metadata.
    """
    radius_deg = radius_arcsec / 3600.0

    adql = f"""
        SELECT koaid, ra, dec, date_obs, exptime, koaimtyp,
               bgratnam, ifunam, waveblue, wavered, wavecntr,
               progid, progpi, progtitl, targname,
               statenam, stateid, filehand, semester
        FROM koa_kcwi
        WHERE CONTAINS(POINT('ICRS', ra, dec),
                       CIRCLE('ICRS', {ra}, {dec}, {radius_deg})) = 1
        ORDER BY date_obs DESC
    """
    return _tap_query(adql)


def query_calibration_frames(statenam: str, obs_date: str) -> list[dict]:
    """
    Find calibration frames matching an instrument configuration (statenam)
    within ±CALIB_WINDOW_DAYS of the science observation date.

    Calibration frames have zero proprietary period — always public.
    """
    try:
        dt = datetime.strptime(obs_date[:10], "%Y-%m-%d")
    except ValueError:
        return []

    date_lo = (dt - timedelta(days=CALIB_WINDOW_DAYS)).strftime("%Y-%m-%d")
    date_hi = (dt + timedelta(days=CALIB_WINDOW_DAYS)).strftime("%Y-%m-%d")

    calib_types = ", ".join(f"'{t}'" for t in ALL_CALIB_TYPES)

    adql = f"""
        SELECT koaid, date_obs, koaimtyp, exptime, bgratnam, ifunam, filehand, statenam
        FROM koa_kcwi
        WHERE koaimtyp IN ({calib_types})
          AND statenam = '{statenam}'
          AND date_obs >= '{date_lo}'
          AND date_obs <= '{date_hi}'
        ORDER BY date_obs
    """
    return _tap_query(adql)


# ---------------------------------------------------------------------------
# Filename conversion (KOA → telescope/kcwidrp convention)
# ---------------------------------------------------------------------------

def koa_to_telescope_name(koa_name: str) -> str:
    """
    KB.20170918.21047.fits  →  kb170918_21047.fits

    kcwidrp expects the telescope convention. KOA renames files on ingest.
    """
    m = re.match(r"KB\.(\d{4})(\d{2})(\d{2})\.(\d+)\.fits", koa_name, re.IGNORECASE)
    if not m:
        raise ValueError(f"Unexpected KOA filename format: {koa_name!r}")
    yyyy, mm, dd, num = m.groups()
    return f"kb{yyyy[2:]}{mm}{dd}_{num}.fits"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_frame(filehand: str, dest_dir: Path, rename: bool = True) -> Path:
    """
    Download a single FITS frame from KOA. Renames to telescope convention by default.
    Returns the local path.
    """
    koaid = filehand.split("/")[-1]
    if rename:
        local_name = koa_to_telescope_name(koaid)
    else:
        local_name = koaid

    dest = dest_dir / local_name
    if dest.exists():
        return dest  # already downloaded

    dest_dir.mkdir(parents=True, exist_ok=True)
    url = f"{KOA_DOWNLOAD_URL}?filehand={filehand}"
    resp = requests.get(url, timeout=300, stream=True)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    return dest


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------

def run(
    project: str,
    source_ids: list[int] | None = None,
    search_radius_arcsec: float = DEFAULT_RADIUS_ARCSEC,
    download: bool = False,
    dest_dir: Path | None = None,
) -> dict:
    """
    Search KOA for KCWI observations of accepted sample sources.

    Args:
        project: Project namespace (projects/<project>/<project>.db)
        source_ids: Specific source IDs to search. None = all accepted sources
                    that haven't been searched yet.
        search_radius_arcsec: Cone search radius around each source centroid.
        download: If True, download raw FITS files (science + calibrations).
        dest_dir: Root directory for downloads. Defaults to projects/<project>/.

    Returns:
        Summary dict with counts and estimated volume.
    """
    db.ensure_schema(project)

    # Determine which sources to search
    if source_ids:
        sources = [db.get_source(project, sid) for sid in source_ids]
        sources = [s for s in sources if s is not None]
    else:
        sources = db.get_sources_needing_archive_search(project)

    if not sources:
        print("[query_koa] No sources to search.")
        return {
            "sources_searched": 0,
            "sources_with_data": 0,
            "sources_no_data": 0,
            "observations_found": 0,
            "frames_found": 0,
            "estimated_volume_gb": 0.0,
            "downloaded": False,
        }

    if dest_dir is None:
        dest_dir = Path("projects") / project

    total_frames = 0
    sources_with_data = 0
    sources_no_data = 0
    observations_found = 0

    for source in sources:
        sid = source["id"]
        ra = source["ra"]
        dec = source["dec"]
        z = source.get("z")
        name = source["name"]

        # Dedup check
        params = {"source_id": sid, "radius_arcsec": search_radius_arcsec}
        if db.has_been_queried(project, "koa", params):
            print(f"[query_koa] {name}: already searched, skipping")
            continue

        print(f"[query_koa] Searching {name} (z={z if z else '?'}, RA={ra:.4f}, Dec={dec:.4f}) ...")

        try:
            frames = query_science_frames(ra, dec, search_radius_arcsec)
        except requests.RequestException as exc:
            print(f"[query_koa] {name}: TAP query failed: {exc}")
            db.record_query(project, "koa", params, -1)
            continue

        db.record_query(project, "koa", params, len(frames))

        if not frames:
            print(f"[query_koa] {name}: no KCWI data in KOA")
            db.update_source_status(project, sid, "accepted", ["no_archive_data"])
            sources_no_data += 1
            continue

        sources_with_data += 1
        print(f"[query_koa] {name}: found {len(frames)} science frame(s)")

        for frame in frames:
            statenam = frame.get("statenam", "")
            obs_date = frame.get("date_obs", "")
            koaid = frame["koaid"]
            filehand = frame["filehand"]
            progid = frame.get("progid", "")
            pi = frame.get("progpi", "")

            # Find calibration frames for this science exposure
            calib_frames = []
            if statenam and obs_date:
                try:
                    calib_frames = query_calibration_frames(statenam, obs_date)
                except requests.RequestException as exc:
                    print(f"[query_koa]   calib query failed for {koaid}: {exc}")

            calib_koaids = [c["koaid"] for c in calib_frames]

            # Insert generic observation record
            obs_id = db.insert_observation(
                project=project,
                source_id=sid,
                instrument="KCWI",
                program_id=progid,
                pi=pi,
                obs_date=obs_date,
                public=True,
                archive="KOA",
                notes=f"type={frame.get('koaimtyp','?')} grating={frame.get('bgratnam','?')} "
                      f"slicer={frame.get('ifunam','?')} "
                      f"waveblue={frame.get('waveblue','?')} wavered={frame.get('wavered','?')}",
            )

            # Insert KOA-specific frame record
            frame_id = db.insert_koa_frame(
                project=project,
                observation_id=obs_id,
                koaid=koaid,
                filehand=filehand,
                exptime=_safe_float(frame.get("exptime")),
                grating=frame.get("bgratnam"),
                slicer=frame.get("ifunam"),
                waveblue=_safe_float(frame.get("waveblue")),
                wavered=_safe_float(frame.get("wavered")),
                statenam=statenam,
                calib_koaids=calib_koaids,
            )

            observations_found += 1
            total_frames += 1

            calib_summary = _calib_coverage_summary(calib_frames)
            print(
                f"[query_koa]   {koaid}  {obs_date}  "
                f"t={frame.get('exptime','?')}s  "
                f"grat={frame.get('bgratnam','?')}  "
                f"slicer={frame.get('ifunam','?')}  "
                f"calib={len(calib_koaids)} frames [{calib_summary}]"
            )

    estimated_gb = (total_frames * FITS_MB_PER_FRAME) / 1024.0

    result = {
        "sources_searched": len(sources),
        "sources_with_data": sources_with_data,
        "sources_no_data": sources_no_data,
        "observations_found": observations_found,
        "frames_found": total_frames,
        "estimated_volume_gb": round(estimated_gb, 2),
        "downloaded": False,
    }

    if not download:
        print(
            f"\n[query_koa] Summary: {sources_with_data}/{len(sources)} sources have KCWI data  "
            f"({total_frames} frames, ~{estimated_gb:.1f} GB estimated)"
        )
        if estimated_gb > VOLUME_WARN_GB:
            print(
                f"[query_koa] WARNING: estimated volume {estimated_gb:.1f} GB exceeds "
                f"{VOLUME_WARN_GB} GB threshold — re-run with --download only after review"
            )
        return result

    # --- Download path ---
    if estimated_gb > VOLUME_WARN_GB:
        print(
            f"[query_koa] Volume {estimated_gb:.1f} GB > {VOLUME_WARN_GB} GB limit. "
            f"Aborting download. Re-run with explicit --dest-dir and human approval."
        )
        return result

    print(f"\n[query_koa] Downloading {total_frames} science frames ...")

    downloaded = 0
    failed = 0

    # Re-fetch frame records from DB (we may have been called with existing frames too)
    for source in sources:
        sid = source["id"]
        for obs in db.get_observations_for_source(project, sid):
            if obs.get("archive") != "KOA":
                continue
            for kframe in db.get_koa_frames_for_observation(project, obs["id"]):
                if kframe.get("raw_path"):
                    continue  # already downloaded

                koaid = kframe["koaid"]
                filehand = kframe["filehand"]
                sci_dest = dest_dir / "raw" / koaid
                sci_dest.mkdir(parents=True, exist_ok=True)

                try:
                    local = download_frame(filehand, sci_dest, rename=True)
                    db.update_koa_frame(project, kframe["id"], raw_path=str(local))
                    db.update_observation_status(project, obs["id"], "downloaded")
                    downloaded += 1
                    print(f"[query_koa]   downloaded {local.name}")
                except Exception as exc:
                    print(f"[query_koa]   FAILED {koaid}: {exc}")
                    failed += 1

                # Download associated calibrations
                calib_koaids = kframe.get("calib_koaids") or []
                if isinstance(calib_koaids, str):
                    calib_koaids = json.loads(calib_koaids)

                if calib_koaids:
                    statenam = kframe.get("statenam", "unknown")
                    date_str = (obs.get("obs_date") or "")[:8].replace("-", "")
                    calib_dest = dest_dir / "calibrations" / f"{statenam}_{date_str}"
                    for ckid in calib_koaids:
                        # Reconstruct filehand for calibration — same convention as science
                        # filehand = /koadata/<prog>/YYYYMMDD/<koaid>
                        # For calibrations we fetch via koaid directly
                        c_fh = _koaid_to_filehand(ckid)
                        if not c_fh:
                            continue
                        try:
                            download_frame(c_fh, calib_dest, rename=True)
                        except Exception as exc:
                            print(f"[query_koa]   calib FAILED {ckid}: {exc}")

    result["downloaded"] = True
    result["download_success"] = downloaded
    result["download_failed"] = failed

    print(f"[query_koa] Download complete: {downloaded} ok, {failed} failed")
    return result


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _safe_float(val) -> float | None:
    try:
        return float(val) if val not in (None, "", "null") else None
    except (ValueError, TypeError):
        return None


def _calib_coverage_summary(calib_frames: list[dict]) -> str:
    """Summarise which required calibration types are present."""
    present = {f["koaimtyp"] for f in calib_frames}
    parts = []
    for t in REQUIRED_CALIB_TYPES:
        parts.append(t if t in present else f"MISSING:{t}")
    return " ".join(parts)


def _koaid_to_filehand(koaid: str) -> str | None:
    """
    Reconstruct the KOA filehand path from a KOAID.

    KOAIDs have the form KB.YYYYMMDD.SSSSS.fits
    filehands have the form /koadata/<PROGID>/YYYYMMDD/KB.YYYYMMDD.SSSSS.fits

    We cannot reconstruct progid without a separate TAP query, so we use a
    /koadata lookup that KOA supports for direct koaid-based retrieval.
    The download URL also accepts ?koaid=<koaid> as an alternative to filehand.
    """
    if not koaid:
        return None
    # KOA accepts ?filehand=/koadata/PUBLIC/YYYYMMDD/koaid for calibration frames.
    # Extract date component.
    m = re.match(r"KB\.(\d{8})\.\d+\.fits", koaid, re.IGNORECASE)
    if not m:
        return None
    date_str = m.group(1)
    # Use the PUBLIC pseudo-path that KOA resolves for calibrations
    return f"/koadata/PUBLIC/{date_str}/{koaid}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Search KOA for KCWI data for sample sources")
    parser.add_argument("--project", required=True, help="Project namespace")
    parser.add_argument(
        "--source-ids", nargs="+", type=int, default=None,
        help="Specific source IDs to search (default: all accepted sources not yet searched)",
    )
    parser.add_argument(
        "--radius", type=float, default=DEFAULT_RADIUS_ARCSEC,
        help=f"Cone search radius in arcsec (default: {DEFAULT_RADIUS_ARCSEC})",
    )
    parser.add_argument(
        "--download", action="store_true",
        help="Download raw FITS files (pauses if estimated volume > 5 GB)",
    )
    parser.add_argument(
        "--dest-dir", type=Path, default=None,
        help="Root directory for downloaded files (default: projects/<project>/)",
    )
    args = parser.parse_args()

    result = run(
        project=args.project,
        source_ids=args.source_ids,
        search_radius_arcsec=args.radius,
        download=args.download,
        dest_dir=args.dest_dir,
    )
    print("\n" + json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
