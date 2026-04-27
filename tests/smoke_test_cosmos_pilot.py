"""
Smoke tests for CosmicWebCrawler — cosmos-pilot project.

Verifies DB structure and core logic WITHOUT calling external APIs or Claude.

Run: pytest tests/smoke_test_cosmos_pilot.py -v
"""

import json
import os
import sys
import pytest
from pathlib import Path

# Allow imports from src/
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import db

PROJECT = "cosmos-pilot-test"


@pytest.fixture(autouse=True)
def chdir_tmp(tmp_path, monkeypatch):
    """Run each test in a temp directory so projects/ doesn't pollute the repo."""
    monkeypatch.chdir(tmp_path)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_schema_creates_cleanly():
    db.ensure_schema(PROJECT)
    summary = db.get_sample_summary(PROJECT)
    assert summary["total_sources"] == 0
    assert summary["by_status"] == {}
    assert summary["total_observations"] == 0
    assert summary["total_bibliography"] == 0
    assert summary["reading_queue_pending"] == 0


def test_db_file_created_in_correct_location():
    db.ensure_schema(PROJECT)
    db_path = Path("projects") / PROJECT / f"{PROJECT}.db"
    assert db_path.exists()


def test_schema_is_idempotent():
    db.ensure_schema(PROJECT)
    db.ensure_schema(PROJECT)  # should not raise
    summary = db.get_sample_summary(PROJECT)
    assert summary["total_sources"] == 0


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def test_insert_and_retrieve_source():
    db.ensure_schema(PROJECT)
    sid = db.insert_source(
        PROJECT,
        name="TEST J150.1234+02.2345",
        ra=150.1234,
        dec=2.2345,
        z=2.51,
        z_source="SIMBAD",
        u_mag=20.3,
    )
    assert isinstance(sid, int)
    src = db.get_source(PROJECT, sid)
    assert src["name"] == "TEST J150.1234+02.2345"
    assert src["ra"] == pytest.approx(150.1234)
    assert src["z"] == pytest.approx(2.51)
    assert src["status"] == "candidate"
    assert src["flags"] == []


def test_insert_source_dedup_by_name():
    db.ensure_schema(PROJECT)
    sid1 = db.insert_source(PROJECT, name="QSO_A", ra=150.0, dec=2.0, z=2.5)
    sid2 = db.insert_source(PROJECT, name="QSO_A", ra=150.0, dec=2.0, z=2.5)
    assert sid1 == sid2
    assert len(db.get_all_sources(PROJECT)) == 1


def test_update_source_status_and_flags():
    db.ensure_schema(PROJECT)
    sid = db.insert_source(PROJECT, name="QSO_B", ra=150.1, dec=2.1, z=2.7)
    db.update_source_status(PROJECT, sid, "rejected", ["z_implausible"])
    src = db.get_source(PROJECT, sid)
    assert src["status"] == "rejected"
    assert "z_implausible" in src["flags"]


def test_update_source_flags_merge():
    """Flags should merge, not overwrite."""
    db.ensure_schema(PROJECT)
    sid = db.insert_source(PROJECT, name="QSO_C", ra=150.2, dec=2.2, z=2.3)
    db.update_source_status(PROJECT, sid, "candidate", ["faint_u"])
    db.update_source_status(PROJECT, sid, "candidate", ["z_conflict"])
    src = db.get_source(PROJECT, sid)
    assert "faint_u" in src["flags"]
    assert "z_conflict" in src["flags"]


def test_get_sources_by_status():
    db.ensure_schema(PROJECT)
    db.insert_source(PROJECT, name="QSO_D", ra=150.3, dec=2.3, z=2.1)
    db.insert_source(PROJECT, name="QSO_E", ra=150.4, dec=2.4, z=2.2)
    sid3 = db.insert_source(PROJECT, name="QSO_F", ra=150.5, dec=2.5, z=2.3)
    db.update_source_status(PROJECT, sid3, "rejected")

    candidates = db.get_sources_by_status(PROJECT, "candidate")
    assert len(candidates) == 2
    rejected = db.get_sources_by_status(PROJECT, "rejected")
    assert len(rejected) == 1


# ---------------------------------------------------------------------------
# Bibliography + reading queue
# ---------------------------------------------------------------------------

def test_insert_paper_dedup():
    db.ensure_schema(PROJECT)
    bid1 = db.insert_paper(PROJECT, arxiv_id="2001.12345", title="Test Paper")
    bid2 = db.insert_paper(PROJECT, arxiv_id="2001.12345", title="Test Paper")
    assert bid1 == bid2


def test_link_source_paper():
    db.ensure_schema(PROJECT)
    sid = db.insert_source(PROJECT, name="QSO_G", ra=150.6, dec=2.6, z=2.8)
    bid = db.insert_paper(PROJECT, arxiv_id="2002.99999", title="Lya Nebula Paper")
    db.link_source_paper(PROJECT, sid, bid, context="detected Lya nebula")
    # No error = success (link table)


def test_reading_queue_enqueue_and_dedup():
    db.ensure_schema(PROJECT)
    qid1 = db.enqueue_paper(PROJECT, ref="2003.11111", reason="interesting citation", citation_depth=1)
    qid2 = db.enqueue_paper(PROJECT, ref="2003.11111", reason="duplicate", citation_depth=1)
    assert qid1 == qid2  # INSERT OR IGNORE


def test_reading_queue_get_next():
    db.ensure_schema(PROJECT)
    db.enqueue_paper(PROJECT, ref="low", priority=0.2)
    db.enqueue_paper(PROJECT, ref="high", priority=0.9)
    db.enqueue_paper(PROJECT, ref="mid", priority=0.5)
    next_item = db.get_next_queued_paper(PROJECT)
    assert next_item["ref"] == "high"


def test_queue_status_update():
    db.ensure_schema(PROJECT)
    qid = db.enqueue_paper(PROJECT, ref="2004.55555")
    db.update_queue_status(PROJECT, qid, "done")
    # Should no longer appear in next pending
    next_item = db.get_next_queued_paper(PROJECT)
    assert next_item is None or next_item["ref"] != "2004.55555"


# ---------------------------------------------------------------------------
# Query history / dedup
# ---------------------------------------------------------------------------

def test_params_hash_is_order_independent():
    h1 = db.compute_params_hash({"ra": 150.1, "dec": 2.2, "radius": 0.75})
    h2 = db.compute_params_hash({"radius": 0.75, "dec": 2.2, "ra": 150.1})
    assert h1 == h2


def test_params_hash_distinguishes_different_params():
    h1 = db.compute_params_hash({"ra": 150.1, "dec": 2.2})
    h2 = db.compute_params_hash({"ra": 150.1, "dec": 2.3})
    assert h1 != h2


def test_has_been_queried_false_initially():
    db.ensure_schema(PROJECT)
    params = {"ra": 150.1, "dec": 2.2, "radius_deg": 0.75}
    assert not db.has_been_queried(PROJECT, "simbad", params)


def test_record_and_check_query():
    db.ensure_schema(PROJECT)
    params = {"ra": 150.1, "dec": 2.2, "radius_deg": 0.75}
    db.record_query(PROJECT, "simbad", params, result_count=42)
    assert db.has_been_queried(PROJECT, "simbad", params)


def test_query_dedup_is_order_independent():
    db.ensure_schema(PROJECT)
    params_a = {"ra": 150.1, "dec": 2.2, "radius_deg": 0.75}
    params_b = {"radius_deg": 0.75, "ra": 150.1, "dec": 2.2}
    db.record_query(PROJECT, "ned", params_a, result_count=5)
    assert db.has_been_queried(PROJECT, "ned", params_b)


def test_different_databases_not_confused():
    db.ensure_schema(PROJECT)
    params = {"ra": 150.1, "dec": 2.2}
    db.record_query(PROJECT, "simbad", params, result_count=1)
    assert not db.has_been_queried(PROJECT, "sdss", params)


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------

def test_insert_observation():
    db.ensure_schema(PROJECT)
    sid = db.insert_source(PROJECT, name="QSO_H", ra=150.7, dec=2.7, z=2.9)
    oid = db.insert_observation(PROJECT, sid, instrument="KCWI", pi="O'Sullivan", public=True)
    assert isinstance(oid, int)
    obs = db.get_observations_for_source(PROJECT, sid)
    assert len(obs) == 1
    assert obs[0]["instrument"] == "KCWI"
    assert obs[0]["public"] == 1


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def test_sample_summary_counts():
    db.ensure_schema(PROJECT)
    db.insert_source(PROJECT, name="QSO_I", ra=150.8, dec=2.8, z=2.0)
    s2 = db.insert_source(PROJECT, name="QSO_J", ra=150.9, dec=2.9, z=2.1)
    db.update_source_status(PROJECT, s2, "accepted")
    db.insert_paper(PROJECT, arxiv_id="2005.00001", title="Paper 1")
    db.enqueue_paper(PROJECT, ref="2005.00002")

    summary = db.get_sample_summary(PROJECT)
    assert summary["total_sources"] == 2
    assert summary["by_status"]["candidate"] == 1
    assert summary["by_status"]["accepted"] == 1
    assert summary["total_bibliography"] == 1
    assert summary["reading_queue_pending"] == 1


# ---------------------------------------------------------------------------
# source_bibcodes
# ---------------------------------------------------------------------------

def test_source_bibcodes_insert_dedup():
    db.ensure_schema(PROJECT)
    sid = db.insert_source(PROJECT, name="QSO_BIB_A", ra=151.0, dec=3.0, z=2.5)
    db.insert_source_bibcode(PROJECT, sid, "2021ApJ...912...54C")
    db.insert_source_bibcode(PROJECT, sid, "2021ApJ...912...54C")  # duplicate — silent no-op
    db.insert_source_bibcode(PROJECT, sid, "2020MNRAS.495.1847S")
    result = db.get_bibcodes_for_project(PROJECT)
    assert "2021ApJ...912...54C" in result
    assert result["2021ApJ...912...54C"] == [sid]
    assert len(result["2021ApJ...912...54C"]) == 1  # not doubled by dedup insert


def test_get_bibcodes_for_project():
    db.ensure_schema(PROJECT)
    s1 = db.insert_source(PROJECT, name="QSO_BIB_B", ra=151.1, dec=3.1, z=2.6)
    s2 = db.insert_source(PROJECT, name="QSO_BIB_C", ra=151.2, dec=3.2, z=2.7)
    shared_bibcode = "2020MNRAS.111.2222X"
    db.insert_source_bibcode(PROJECT, s1, shared_bibcode)
    db.insert_source_bibcode(PROJECT, s2, shared_bibcode)
    db.insert_source_bibcode(PROJECT, s1, "2019ApJ...000.0000Y")

    result = db.get_bibcodes_for_project(PROJECT)
    assert set(result[shared_bibcode]) == {s1, s2}
    assert result["2019ApJ...000.0000Y"] == [s1]


def test_bibcode_count_in_summary():
    db.ensure_schema(PROJECT)
    sid = db.insert_source(PROJECT, name="QSO_BIB_D", ra=151.3, dec=3.3, z=2.8)
    db.insert_source_bibcode(PROJECT, sid, "2022ApJ...999.1111Z")

    summary = db.get_sample_summary(PROJECT)
    assert "total_bibcodes" in summary
    assert summary["total_bibcodes"] >= 1


# ---------------------------------------------------------------------------
# mi_z2 UV proxy
# ---------------------------------------------------------------------------

def test_mi_z2_stored_and_used_as_proxy():
    """mi_z2 from SDSS DR17Q VAC should be used as the UV proxy when available.

    It is already an absolute magnitude — check_data_quality must NOT apply
    a distance modulus to it. uv_luminosity should equal mi_z2 exactly.
    """
    import check_data_quality

    db.ensure_schema(PROJECT)
    sid = db.insert_source(
        PROJECT,
        name="QSO_MI_TEST",
        ra=150.5,
        dec=2.5,
        z=2.5,
        z_source="SDSS_DR17",
        g_mag=19.8,
        r_mag=19.5,
        mi_z2=-27.3,
    )

    check_data_quality.run(PROJECT)

    src = db.get_source(PROJECT, sid)
    # mi_z2 should be preferred over g/r observed-frame magnitudes
    assert src["uv_proxy_band"] == "mi_z2", (
        f"Expected uv_proxy_band='mi_z2', got '{src['uv_proxy_band']}'"
    )
    # mi_z2 is already absolute — stored unchanged as uv_luminosity
    assert src["uv_luminosity"] == pytest.approx(-27.3), (
        f"Expected uv_luminosity=-27.3 (no distance modulus), got {src['uv_luminosity']}"
    )
    assert src["uv_proxy_mag"] == pytest.approx(-27.3)


def test_no_mi_z2_falls_back_to_g_band():
    """Sources without mi_z2 (Milliquas, NED) should fall back to g/r band selection."""
    import check_data_quality

    db.ensure_schema(PROJECT)
    sid = db.insert_source(
        PROJECT,
        name="QSO_NO_MI_TEST",
        ra=150.6,
        dec=2.6,
        z=2.3,
        z_source="Milliquas",
        g_mag=19.8,
        r_mag=19.5,
        # mi_z2 intentionally omitted (None)
    )

    check_data_quality.run(PROJECT)

    src = db.get_source(PROJECT, sid)
    # z=2.3 < 2.5, so g-band should be preferred
    assert src["uv_proxy_band"] == "g", (
        f"Expected fallback to g-band, got '{src['uv_proxy_band']}'"
    )
    # uv_luminosity should differ from g_mag (distance modulus applied)
    assert src["uv_luminosity"] != pytest.approx(19.8)


# ---------------------------------------------------------------------------
# first_flux and bi_civ columns (schema v8)
# ---------------------------------------------------------------------------

def test_first_flux_bi_civ_columns_exist():
    """Schema v8 must include first_flux and bi_civ columns on the sources table."""
    import sqlite3

    db.ensure_schema(PROJECT)
    db_path = Path("projects") / PROJECT / f"{PROJECT}.db"
    con = sqlite3.connect(str(db_path))
    cols = [row[1] for row in con.execute("PRAGMA table_info(sources)").fetchall()]
    con.close()
    assert "first_flux" in cols, f"first_flux column missing; cols={cols}"
    assert "bi_civ" in cols, f"bi_civ column missing; cols={cols}"


def test_insert_and_retrieve_first_flux_bi_civ():
    """first_flux and bi_civ values round-trip through insert_source / get_source."""
    db.ensure_schema(PROJECT)
    sid = db.insert_source(
        PROJECT,
        name="QSO_RADIO_BAL",
        ra=150.3,
        dec=2.3,
        z=2.8,
        z_source="SDSS_DR17",
        first_flux=2.5,   # mJy — radio-loud
        bi_civ=800.0,     # km/s — BAL QSO
    )
    src = db.get_source(PROJECT, sid)
    assert src["first_flux"] == pytest.approx(2.5)
    assert src["bi_civ"] == pytest.approx(800.0)


def test_first_flux_null_outside_footprint():
    """first_flux=None means outside FIRST footprint; must be stored as NULL."""
    import sqlite3

    db.ensure_schema(PROJECT)
    sid = db.insert_source(
        PROJECT,
        name="QSO_NO_FIRST",
        ra=150.4,
        dec=2.4,
        z=2.9,
        z_source="SDSS_DR17",
        first_flux=None,
        bi_civ=0.0,
    )
    db_path = Path("projects") / PROJECT / f"{PROJECT}.db"
    con = sqlite3.connect(str(db_path))
    row = con.execute(
        "SELECT first_flux FROM sources WHERE id=?", (sid,)
    ).fetchone()
    con.close()
    assert row[0] is None, f"Expected NULL for first_flux, got {row[0]}"


# ---------------------------------------------------------------------------
# sample_bias metrics structure
# ---------------------------------------------------------------------------

def test_sample_bias_returns_required_keys():
    """sample_bias.run() must return n_sample, n_parent, and the four metric blocks."""
    import sample_bias

    db.ensure_schema(PROJECT)
    # Insert a parent (SDSS DR17) source
    for i, (fl, bic) in enumerate([(0.5, 0.0), (3.0, 500.0), (None, None)]):
        db.insert_source(
            PROJECT,
            name=f"PARENT_{i}",
            ra=150.0 + i * 0.01,
            dec=2.0 + i * 0.01,
            z=2.5 + i * 0.1,
            z_source="SDSS_DR17",
            mi_z2=-26.0 - i * 0.3,
            first_flux=fl,
            bi_civ=bic,
        )
    # Insert accepted sample sources (also have SDSS DR17 origin)
    for i in range(2):
        sid = db.insert_source(
            PROJECT,
            name=f"SAMPLE_{i}",
            ra=150.1 + i * 0.01,
            dec=2.1 + i * 0.01,
            z=2.6 + i * 0.1,
            z_source="SDSS_DR17",
            mi_z2=-27.0 - i * 0.2,
            first_flux=0.3,
            bi_civ=0.0,
        )
        db.update_source_status(PROJECT, sid, "accepted")

    result = sample_bias.run(PROJECT)

    assert "n_sample" in result
    assert "n_parent" in result
    assert result["n_sample"] == 2
    # n_parent includes ALL SDSS_DR17 sources (including those now accepted)
    assert result["n_parent"] >= 3

    # Redshift block
    assert "redshift" in result
    assert "sample_mean" in result["redshift"]
    assert "parent_mean" in result["redshift"]
    assert "ks_stat" in result["redshift"]
    assert "ks_pvalue" in result["redshift"]

    # mi_z2 block
    assert "mi_z2" in result
    assert "sample_mean" in result["mi_z2"]
    assert "n_sample_with_data" in result["mi_z2"]
    assert "n_parent_with_data" in result["mi_z2"]

    # Radio-loud block
    assert "radio_loud" in result
    rl = result["radio_loud"]
    assert "threshold_mjy" in rl
    assert "sample_fraction" in rl
    assert "parent_fraction" in rl
    assert "n_sample_with_first" in rl
    assert "n_parent_with_first" in rl

    # BAL block
    assert "bal" in result
    bal = result["bal"]
    assert "threshold_kms" in bal
    assert "sample_fraction" in bal
    assert "parent_fraction" in bal
    assert "n_sample_with_biciv" in bal
    assert "n_parent_with_biciv" in bal


def test_sample_bias_excludes_null_from_fractions():
    """Sources with first_flux=None (outside FIRST footprint) must not count toward n_with_first."""
    import sample_bias

    db.ensure_schema(PROJECT)
    # Two SDSS DR17 sources: one with FIRST data, one outside footprint
    db.insert_source(
        PROJECT, name="P_FIRST", ra=150.0, dec=2.0, z=2.5,
        z_source="SDSS_DR17", first_flux=0.5, bi_civ=0.0,
    )
    db.insert_source(
        PROJECT, name="P_NO_FIRST", ra=150.1, dec=2.1, z=2.6,
        z_source="SDSS_DR17", first_flux=None, bi_civ=None,
    )
    sid = db.insert_source(
        PROJECT, name="S_FIRST", ra=150.2, dec=2.2, z=2.7,
        z_source="SDSS_DR17", first_flux=2.5, bi_civ=0.0,
    )
    db.update_source_status(PROJECT, sid, "accepted")

    result = sample_bias.run(PROJECT)
    # parent = all SDSS_DR17 (P_FIRST + P_NO_FIRST + S_FIRST); with non-NULL first_flux = 2
    # sample = accepted (S_FIRST only); with non-NULL first_flux = 1
    assert result["radio_loud"]["n_sample_with_first"] == 1
    assert result["radio_loud"]["n_parent_with_first"] == 2
    # P_NO_FIRST has first_flux=None → excluded from fraction, not counted as non-detection
    assert result["radio_loud"]["n_parent_with_first"] < 3
