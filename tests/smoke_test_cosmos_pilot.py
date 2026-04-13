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
