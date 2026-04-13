"""
db.py — CosmicWebCrawler persistence layer.

ALL SQL lives here. No other file imports sqlite3.
All functions are project-aware and self-contained (open + close their own connections).
WAL mode is always enabled.
"""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 2


# ---------------------------------------------------------------------------
# Connection + schema
# ---------------------------------------------------------------------------

def get_db_path(project: str) -> Path:
    return Path("projects") / project / f"{project}.db"


def get_connection(project: str) -> sqlite3.Connection:
    db_path = get_db_path(project)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema(project: str) -> None:
    """Idempotent. Creates all tables and runs any pending migrations."""
    conn = get_connection(project)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version    INTEGER PRIMARY KEY,
                applied_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sources (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                name           TEXT NOT NULL,
                ra             REAL NOT NULL,
                dec            REAL NOT NULL,
                z              REAL,
                z_source       TEXT,
                u_mag          REAL,
                g_mag          REAL,
                r_mag          REAL,
                uv_luminosity  REAL,
                status         TEXT NOT NULL DEFAULT 'candidate',
                flags          TEXT NOT NULL DEFAULT '[]',
                bias_weight    REAL DEFAULT 1.0,
                added_by       TEXT,
                created_at     TEXT DEFAULT (datetime('now')),
                updated_at     TEXT DEFAULT (datetime('now')),
                UNIQUE(name)
            );

            CREATE TABLE IF NOT EXISTS observations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id   INTEGER NOT NULL REFERENCES sources(id),
                instrument  TEXT NOT NULL,
                program_id  TEXT,
                pi          TEXT,
                obs_date    TEXT,
                public      INTEGER DEFAULT 0,
                archive     TEXT,
                notes       TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS bibliography (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                arxiv_id        TEXT,
                doi             TEXT,
                title           TEXT,
                authors         TEXT,
                year            INTEGER,
                journal         TEXT,
                abstract        TEXT,
                relevance_notes TEXT,
                read_status     TEXT DEFAULT 'unread',
                created_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(arxiv_id),
                UNIQUE(doi)
            );

            CREATE TABLE IF NOT EXISTS source_refs (
                source_id  INTEGER NOT NULL REFERENCES sources(id),
                bib_id     INTEGER NOT NULL REFERENCES bibliography(id),
                context    TEXT,
                PRIMARY KEY (source_id, bib_id)
            );

            CREATE TABLE IF NOT EXISTS reading_queue (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ref             TEXT NOT NULL,
                reason          TEXT,
                recommended_by  TEXT,
                source_ids      TEXT DEFAULT '[]',
                citation_depth  INTEGER DEFAULT 0,
                priority        REAL DEFAULT 0.5,
                status          TEXT DEFAULT 'pending',
                created_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(ref)
            );

            CREATE TABLE IF NOT EXISTS query_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                database     TEXT NOT NULL,
                params_hash  TEXT NOT NULL,
                params_json  TEXT,
                result_count INTEGER,
                ran_at       TEXT DEFAULT (datetime('now')),
                UNIQUE(database, params_hash)
            );

            CREATE TABLE IF NOT EXISTS koa_frames (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                observation_id  INTEGER NOT NULL REFERENCES observations(id),
                koaid           TEXT UNIQUE NOT NULL,
                filehand        TEXT NOT NULL,
                exptime         REAL,
                grating         TEXT,
                slicer          TEXT,
                waveblue        REAL,
                wavered         REAL,
                statenam        TEXT,
                raw_path        TEXT,
                reduced_path    TEXT,
                calib_koaids    TEXT DEFAULT '[]',
                created_at      TEXT DEFAULT (datetime('now'))
            );
        """)
        cur = conn.execute("SELECT MAX(version) FROM schema_version")
        current = cur.fetchone()[0] or 0
        if current < 2:
            # v2: add status column to observations, koa_frames table already created above
            try:
                conn.execute("ALTER TABLE observations ADD COLUMN status TEXT DEFAULT 'found'")
            except sqlite3.OperationalError:
                pass  # column already exists (idempotent)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version) VALUES (2)", ()
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flags_load(raw: str) -> list:
    try:
        return json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return []


def _row_to_dict(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    for key in ("flags", "authors", "source_ids"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------

def insert_source(
    project: str,
    name: str,
    ra: float,
    dec: float,
    z: Optional[float] = None,
    z_source: Optional[str] = None,
    u_mag: Optional[float] = None,
    g_mag: Optional[float] = None,
    r_mag: Optional[float] = None,
    uv_luminosity: Optional[float] = None,
    added_by: Optional[str] = None,
) -> int:
    """Insert or ignore (by name). Returns source_id."""
    conn = get_connection(project)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO sources
               (name, ra, dec, z, z_source, u_mag, g_mag, r_mag, uv_luminosity, added_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, ra, dec, z, z_source, u_mag, g_mag, r_mag, uv_luminosity, added_by),
        )
        conn.commit()
        cur = conn.execute("SELECT id FROM sources WHERE name = ?", (name,))
        return cur.fetchone()[0]
    finally:
        conn.close()


def update_source_status(
    project: str,
    source_id: int,
    status: str,
    flags: Optional[list] = None,
) -> None:
    """Update status and merge new flags into the existing JSON array."""
    conn = get_connection(project)
    try:
        if flags:
            cur = conn.execute("SELECT flags FROM sources WHERE id = ?", (source_id,))
            row = cur.fetchone()
            existing = _flags_load(row[0]) if row else []
            merged = list(dict.fromkeys(existing + flags))  # deduplicate, preserve order
            conn.execute(
                "UPDATE sources SET status = ?, flags = ?, updated_at = datetime('now') WHERE id = ?",
                (status, json.dumps(merged), source_id),
            )
        else:
            conn.execute(
                "UPDATE sources SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (status, source_id),
            )
        conn.commit()
    finally:
        conn.close()


def update_source_bias_weight(project: str, source_id: int, weight: float) -> None:
    conn = get_connection(project)
    try:
        conn.execute(
            "UPDATE sources SET bias_weight = ?, updated_at = datetime('now') WHERE id = ?",
            (weight, source_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_source(project: str, source_id: int) -> Optional[dict]:
    conn = get_connection(project)
    try:
        cur = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,))
        return _row_to_dict(cur.fetchone())
    finally:
        conn.close()


def get_sources_by_status(project: str, status: str) -> list[dict]:
    conn = get_connection(project)
    try:
        cur = conn.execute("SELECT * FROM sources WHERE status = ? ORDER BY id", (status,))
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_all_sources(project: str) -> list[dict]:
    conn = get_connection(project)
    try:
        cur = conn.execute("SELECT * FROM sources ORDER BY id")
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# observations
# ---------------------------------------------------------------------------

def insert_observation(
    project: str,
    source_id: int,
    instrument: str,
    program_id: Optional[str] = None,
    pi: Optional[str] = None,
    obs_date: Optional[str] = None,
    public: bool = False,
    archive: Optional[str] = None,
    notes: Optional[str] = None,
) -> int:
    conn = get_connection(project)
    try:
        cur = conn.execute(
            """INSERT INTO observations
               (source_id, instrument, program_id, pi, obs_date, public, archive, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (source_id, instrument, program_id, pi, obs_date, int(public), archive, notes),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_observations_for_source(project: str, source_id: int) -> list[dict]:
    conn = get_connection(project)
    try:
        cur = conn.execute(
            "SELECT * FROM observations WHERE source_id = ? ORDER BY obs_date",
            (source_id,),
        )
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def update_observation_status(
    project: str,
    obs_id: int,
    status: str,
) -> None:
    conn = get_connection(project)
    try:
        conn.execute(
            "UPDATE observations SET status = ? WHERE id = ?",
            (status, obs_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_sources_needing_archive_search(project: str) -> list[dict]:
    """Return accepted sources that haven't been searched in KOA yet."""
    conn = get_connection(project)
    try:
        cur = conn.execute(
            """SELECT s.* FROM sources s
               WHERE s.status = 'accepted'
               AND NOT EXISTS (
                   SELECT 1 FROM query_history qh
                   WHERE qh.database = 'koa'
                   AND json_extract(qh.params_json, '$.source_id') = s.id
               )"""
        )
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# koa_frames
# ---------------------------------------------------------------------------

def insert_koa_frame(
    project: str,
    observation_id: int,
    koaid: str,
    filehand: str,
    exptime: Optional[float] = None,
    grating: Optional[str] = None,
    slicer: Optional[str] = None,
    waveblue: Optional[float] = None,
    wavered: Optional[float] = None,
    statenam: Optional[str] = None,
    calib_koaids: Optional[list] = None,
) -> int:
    conn = get_connection(project)
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO koa_frames
               (observation_id, koaid, filehand, exptime, grating, slicer,
                waveblue, wavered, statenam, calib_koaids)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                observation_id, koaid, filehand, exptime, grating, slicer,
                waveblue, wavered, statenam,
                json.dumps(calib_koaids or []),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_koa_frame(
    project: str,
    frame_id: int,
    raw_path: Optional[str] = None,
    reduced_path: Optional[str] = None,
) -> None:
    conn = get_connection(project)
    try:
        if raw_path is not None:
            conn.execute(
                "UPDATE koa_frames SET raw_path = ? WHERE id = ?",
                (raw_path, frame_id),
            )
        if reduced_path is not None:
            conn.execute(
                "UPDATE koa_frames SET reduced_path = ? WHERE id = ?",
                (reduced_path, frame_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_koa_frames_for_observation(project: str, observation_id: int) -> list[dict]:
    conn = get_connection(project)
    try:
        cur = conn.execute(
            "SELECT * FROM koa_frames WHERE observation_id = ?",
            (observation_id,),
        )
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# bibliography
# ---------------------------------------------------------------------------

def insert_paper(
    project: str,
    arxiv_id: Optional[str] = None,
    doi: Optional[str] = None,
    title: Optional[str] = None,
    authors: Optional[list] = None,
    year: Optional[int] = None,
    journal: Optional[str] = None,
    abstract: Optional[str] = None,
    relevance_notes: Optional[str] = None,
) -> int:
    """Insert or ignore (by arxiv_id or doi). Returns bib_id."""
    conn = get_connection(project)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO bibliography
               (arxiv_id, doi, title, authors, year, journal, abstract, relevance_notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                arxiv_id, doi, title,
                json.dumps(authors) if authors else None,
                year, journal, abstract, relevance_notes,
            ),
        )
        conn.commit()
        if arxiv_id:
            cur = conn.execute("SELECT id FROM bibliography WHERE arxiv_id = ?", (arxiv_id,))
        elif doi:
            cur = conn.execute("SELECT id FROM bibliography WHERE doi = ?", (doi,))
        else:
            cur = conn.execute("SELECT id FROM bibliography WHERE title = ?", (title,))
        return cur.fetchone()[0]
    finally:
        conn.close()


def update_paper_read_status(project: str, bib_id: int, status: str) -> None:
    conn = get_connection(project)
    try:
        conn.execute("UPDATE bibliography SET read_status = ? WHERE id = ?", (status, bib_id))
        conn.commit()
    finally:
        conn.close()


def get_paper_by_arxiv(project: str, arxiv_id: str) -> Optional[dict]:
    conn = get_connection(project)
    try:
        cur = conn.execute("SELECT * FROM bibliography WHERE arxiv_id = ?", (arxiv_id,))
        return _row_to_dict(cur.fetchone())
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# source_refs
# ---------------------------------------------------------------------------

def link_source_paper(
    project: str,
    source_id: int,
    bib_id: int,
    context: Optional[str] = None,
) -> None:
    conn = get_connection(project)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO source_refs (source_id, bib_id, context) VALUES (?, ?, ?)",
            (source_id, bib_id, context),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# reading_queue
# ---------------------------------------------------------------------------

def enqueue_paper(
    project: str,
    ref: str,
    reason: Optional[str] = None,
    recommended_by: Optional[str] = None,
    source_ids: Optional[list] = None,
    citation_depth: int = 0,
    priority: float = 0.5,
) -> int:
    """INSERT OR IGNORE by ref. Returns queue entry id."""
    conn = get_connection(project)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO reading_queue
               (ref, reason, recommended_by, source_ids, citation_depth, priority)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                ref, reason, recommended_by,
                json.dumps(source_ids or []),
                citation_depth, priority,
            ),
        )
        conn.commit()
        cur = conn.execute("SELECT id FROM reading_queue WHERE ref = ?", (ref,))
        return cur.fetchone()[0]
    finally:
        conn.close()


def get_next_queued_paper(project: str) -> Optional[dict]:
    """Highest priority pending entry."""
    conn = get_connection(project)
    try:
        cur = conn.execute(
            "SELECT * FROM reading_queue WHERE status = 'pending' ORDER BY priority DESC, id LIMIT 1"
        )
        return _row_to_dict(cur.fetchone())
    finally:
        conn.close()


def update_queue_status(project: str, queue_id: int, status: str) -> None:
    conn = get_connection(project)
    try:
        conn.execute("UPDATE reading_queue SET status = ? WHERE id = ?", (status, queue_id))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# query_history
# ---------------------------------------------------------------------------

def compute_params_hash(params: dict) -> str:
    """sha256 of canonicalized JSON (sort_keys). Order-independent."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def has_been_queried(project: str, database: str, params: dict) -> bool:
    h = compute_params_hash(params)
    conn = get_connection(project)
    try:
        cur = conn.execute(
            "SELECT 1 FROM query_history WHERE database = ? AND params_hash = ?",
            (database, h),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def record_query(project: str, database: str, params: dict, result_count: int) -> None:
    h = compute_params_hash(params)
    conn = get_connection(project)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO query_history
               (database, params_hash, params_json, result_count)
               VALUES (?, ?, ?, ?)""",
            (database, h, json.dumps(params, sort_keys=True), result_count),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def get_sample_summary(project: str) -> dict:
    """Returns counts by status and totals."""
    conn = get_connection(project)
    try:
        cur = conn.execute("SELECT status, COUNT(*) as n FROM sources GROUP BY status")
        by_status = {row["status"]: row["n"] for row in cur.fetchall()}
        total = sum(by_status.values())

        cur = conn.execute("SELECT COUNT(*) FROM observations")
        obs_count = cur.fetchone()[0]

        cur = conn.execute("SELECT COUNT(*) FROM bibliography")
        bib_count = cur.fetchone()[0]

        cur = conn.execute("SELECT COUNT(*) FROM reading_queue WHERE status = 'pending'")
        queue_pending = cur.fetchone()[0]

        return {
            "total_sources": total,
            "by_status": by_status,
            "total_observations": obs_count,
            "total_bibliography": bib_count,
            "reading_queue_pending": queue_pending,
        }
    finally:
        conn.close()
