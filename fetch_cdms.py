"""
Phase 1 — Data Collection: Fetch ALL CDMs from Space-Track

Pulls cdm_public records for the last DATA_WINDOW_DAYS, paginates through
results, and caches everything in a local SQLite database (data/cache.db).

Usage:
    python fetch_cdms.py
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

from config import DATA_WINDOW_DAYS, PAGE_SIZE, REQUEST_DELAY_SECONDS

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "cache.db"

# ---------------------------------------------------------------------------
# Space-Track URLs
# ---------------------------------------------------------------------------
BASE_URL = "https://www.space-track.org"
LOGIN_URL = f"{BASE_URL}/ajaxauth/login"


def build_cdm_url(days_back: int, limit: int) -> str:
    """
    Build the cdm_public query URL.

    Uses the exact working Conjunx pattern:
    EMERGENCY_REPORTABLE/Y with TCA > now-N days.
    No offset or orderby (causes 500 on large dataset queries).
    """
    return (
        f"{BASE_URL}/basicspacedata/query/class/cdm_public"
        f"/EMERGENCY_REPORTABLE/Y"
        f"/TCA/%3Enow-{days_back}"
        f"/limit/{limit}"
        f"/format/json/emptyresult/show"
    )


# ---------------------------------------------------------------------------
# SQLite setup
# ---------------------------------------------------------------------------
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS cdm_raw (
    cdm_id          INTEGER PRIMARY KEY,
    created         TEXT,
    tca             TEXT,
    pc              REAL,
    min_rng         REAL,
    sat_1_id        INTEGER,
    sat_1_name      TEXT,
    sat1_object_type TEXT,
    sat1_rcs        TEXT,
    sat_2_id        INTEGER,
    sat_2_name      TEXT,
    sat2_object_type TEXT,
    sat2_rcs        TEXT,
    emergency_reportable TEXT,
    raw_json        TEXT NOT NULL,
    fetched_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cdm_tca ON cdm_raw(tca);
CREATE INDEX IF NOT EXISTS idx_cdm_sat1 ON cdm_raw(sat_1_id);
CREATE INDEX IF NOT EXISTS idx_cdm_sat2 ON cdm_raw(sat_2_id);
"""


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(CREATE_TABLE)
    return conn


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------
class CDMFetcher:
    """Synchronous Space-Track CDM fetcher with pagination and caching."""

    def __init__(self):
        self.email = os.getenv("SPACETRACK_EMAIL", "")
        self.password = os.getenv("SPACETRACK_PASSWORD", "")
        if not self.email or not self.password:
            log.error("SPACETRACK_EMAIL and SPACETRACK_PASSWORD must be set in .env")
            sys.exit(1)

        self.client = httpx.Client(timeout=120.0, follow_redirects=True)
        self.authenticated = False

    def authenticate(self) -> bool:
        """Login to Space-Track. Session cookie is stored in the client."""
        log.info("Authenticating with Space-Track…")
        resp = self.client.post(
            LOGIN_URL,
            data={"identity": self.email, "password": self.password},
        )
        if resp.status_code == 200 and "Login Failed" not in resp.text:
            self.authenticated = True
            log.info("✓ Authentication successful")
            return True
        else:
            log.error("✗ Authentication failed: %s", resp.text[:200])
            self.authenticated = False
            return False

    def fetch_page(self, url: str) -> list[dict] | None:
        """Fetch a single page, re-auth on 401."""
        if not self.authenticated:
            if not self.authenticate():
                return None

        resp = self.client.get(url)

        if resp.status_code == 401:
            log.warning("Session expired — re-authenticating")
            if not self.authenticate():
                return None
            resp = self.client.get(url)

        if resp.status_code != 200:
            log.error("GET failed (%d): %s", resp.status_code, url[:120])
            log.error("Response body: %s", resp.text[:500])
            return None

        data = resp.json()
        return data if isinstance(data, list) else []

    def close(self):
        self.client.close()


# ---------------------------------------------------------------------------
# Insert logic
# ---------------------------------------------------------------------------
def upsert_cdm(conn: sqlite3.Connection, cdm: dict, fetched_at: str) -> bool:
    """Insert a CDM into the cache. Returns True if it was a new record."""
    cdm_id = cdm.get("CDM_ID")
    if cdm_id is None:
        return False

    # Check if already cached
    existing = conn.execute(
        "SELECT 1 FROM cdm_raw WHERE cdm_id = ?", (int(cdm_id),)
    ).fetchone()
    if existing:
        return False

    def safe_float(val):
        try:
            return float(val) if val else None
        except (ValueError, TypeError):
            return None

    def safe_int(val):
        try:
            return int(val) if val else None
        except (ValueError, TypeError):
            return None

    conn.execute(
        """INSERT OR IGNORE INTO cdm_raw
           (cdm_id, created, tca, pc, min_rng,
            sat_1_id, sat_1_name, sat1_object_type, sat1_rcs,
            sat_2_id, sat_2_name, sat2_object_type, sat2_rcs,
            emergency_reportable, raw_json, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            safe_int(cdm_id),
            cdm.get("CREATED"),
            cdm.get("TCA"),
            safe_float(cdm.get("PC")),
            safe_float(cdm.get("MIN_RNG")),
            safe_int(cdm.get("SAT_1_ID")),
            cdm.get("SAT_1_NAME"),
            cdm.get("SAT1_OBJECT_TYPE"),
            cdm.get("SAT1_RCS"),
            safe_int(cdm.get("SAT_2_ID")),
            cdm.get("SAT_2_NAME"),
            cdm.get("SAT2_OBJECT_TYPE"),
            cdm.get("SAT2_RCS"),
            cdm.get("EMERGENCY_REPORTABLE"),
            json.dumps(cdm),
            fetched_at,
        ),
    )
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info("=" * 60)
    log.info("Pc Maturation — Phase 1: Data Collection")
    log.info("=" * 60)
    log.info("Window: last %d days (TCA > now-%d)", DATA_WINDOW_DAYS, DATA_WINDOW_DAYS)
    log.info("Database: %s", DB_PATH)

    conn = init_db()
    fetcher = CDMFetcher()
    fetched_at = datetime.now(timezone.utc).isoformat()

    try:
        # Request up to 20,000 records in one go (we saw ~3,000 for 30 days)
        FETCH_LIMIT = 20000
        url = build_cdm_url(DATA_WINDOW_DAYS, FETCH_LIMIT)
        log.info("Fetching CDMs (limit=%d)…", FETCH_LIMIT)

        page = fetcher.fetch_page(url)
        if page is None:
            log.error("Fetch failed — aborting")
        else:
            new_count = 0
            for cdm in page:
                if upsert_cdm(conn, cdm, fetched_at):
                    new_count += 1

            conn.commit()
            total_fetched = len(page)
            total_new = new_count

            log.info(
                "  → %d records (%d new)",
                len(page), new_count
            )

    finally:
        fetcher.close()

    # Summary
    row = conn.execute("SELECT COUNT(*) as cnt FROM cdm_raw").fetchone()
    total_cached = row["cnt"] if row else 0

    log.info("")
    log.info("=" * 60)
    log.info("FETCH COMPLETE")
    log.info("=" * 60)
    log.info("CDMs received:   %d", total_fetched)
    log.info("New CDMs cached: %d", total_new)
    log.info("Total in cache:  %d", total_cached)
    log.info("Database:        %s", DB_PATH)

    conn.close()


if __name__ == "__main__":
    main()
