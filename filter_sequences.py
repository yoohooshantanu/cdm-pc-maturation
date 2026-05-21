"""
Phase 2 — Filtering & Sequence Building

Reads raw CDMs from cache.db, groups them into conjunction event sequences,
applies LEO and minimum-length filters, and outputs clean sequences.

Grouping key:  (sorted(SAT_1_ID, SAT_2_ID), TCA ±15 min)

Usage:
    python filter_sequences.py
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

from config import (
    DATA_WINDOW_DAYS,
    EARLY_CDM_COUNT,
    LEO_MEAN_MOTION_THRESHOLD,
    MIN_CDMS_PER_SEQUENCE,
    PC_CRITICAL_THRESHOLD,
    REQUEST_DELAY_SECONDS,
    TCA_CLUSTER_TOLERANCE,
)

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
DB_PATH = DATA_DIR / "cache.db"
OUTPUT_PATH = DATA_DIR / "sequences_clean.json"

# ---------------------------------------------------------------------------
# Space-Track (for GP orbital data)
# ---------------------------------------------------------------------------
ST_BASE = "https://www.space-track.org"
ST_LOGIN = f"{ST_BASE}/ajaxauth/login"


def build_gp_url(norad_ids: list[int]) -> str:
    """Build GP query URL for a list of NORAD IDs."""
    ids_str = ",".join(str(i) for i in norad_ids)
    return (
        f"{ST_BASE}/basicspacedata/query/class/gp"
        f"/NORAD_CAT_ID/{ids_str}"
        f"/decay_date/null-val"
        f"/orderby/EPOCH desc"
        f"/format/json/emptyresult/show"
    )


# ---------------------------------------------------------------------------
# SQLite for orbital cache
# ---------------------------------------------------------------------------
CREATE_ORBITAL_TABLE = """
CREATE TABLE IF NOT EXISTS orbital_cache (
    norad_id      INTEGER PRIMARY KEY,
    mean_motion   REAL,
    eccentricity  REAL,
    inclination   REAL,
    period        REAL,
    apoapsis      REAL,
    periapsis     REAL,
    fetched_at    TEXT NOT NULL
);
"""


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(CREATE_ORBITAL_TABLE)
    return conn


# ---------------------------------------------------------------------------
# Step 1: Load raw CDMs from cache
# ---------------------------------------------------------------------------
def load_cdms(conn: sqlite3.Connection) -> list[dict]:
    """Load all CDMs from the raw cache."""
    rows = conn.execute(
        "SELECT cdm_id, created, tca, pc, min_rng, "
        "sat_1_id, sat_1_name, sat1_object_type, "
        "sat_2_id, sat_2_name, sat2_object_type "
        "FROM cdm_raw ORDER BY tca, created"
    ).fetchall()

    cdms = []
    for r in rows:
        cdms.append({
            "cdm_id": r["cdm_id"],
            "created": r["created"],
            "tca": r["tca"],
            "pc": r["pc"],
            "min_rng": r["min_rng"],
            "sat_1_id": r["sat_1_id"],
            "sat_1_name": r["sat_1_name"],
            "sat1_object_type": r["sat1_object_type"],
            "sat_2_id": r["sat_2_id"],
            "sat_2_name": r["sat_2_name"],
            "sat2_object_type": r["sat2_object_type"],
        })
    return cdms


# ---------------------------------------------------------------------------
# Step 2: Group CDMs into conjunction events
# ---------------------------------------------------------------------------
def parse_dt(s: str | None) -> datetime | None:
    """Parse a datetime string from Space-Track."""
    if not s:
        return None
    # Handle various formats
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def group_into_events(cdms: list[dict]) -> dict[str, list[dict]]:
    """
    Group CDMs into conjunction events.

    Grouping key: (sorted(SAT_1_ID, SAT_2_ID), TCA ±15 min)

    Algorithm:
    1. For each CDM, compute the unordered object pair.
    2. Within each pair, cluster by TCA proximity (±15 min).
    3. Each cluster = one conjunction event.
    """
    # Group by unordered pair first
    pair_groups: dict[tuple[int, int], list[dict]] = defaultdict(list)

    for cdm in cdms:
        s1 = cdm["sat_1_id"]
        s2 = cdm["sat_2_id"]
        if s1 is None or s2 is None:
            continue
        pair = (min(s1, s2), max(s1, s2))
        pair_groups[pair].append(cdm)

    # Within each pair, cluster by TCA proximity
    events: dict[str, list[dict]] = {}
    tolerance = TCA_CLUSTER_TOLERANCE

    for pair, pair_cdms in pair_groups.items():
        # Sort by TCA
        pair_cdms.sort(key=lambda c: c["tca"] or "")

        clusters: list[list[dict]] = []
        current_cluster: list[dict] = []
        current_tca: datetime | None = None

        for cdm in pair_cdms:
            tca = parse_dt(cdm["tca"])
            if tca is None:
                continue

            if current_tca is None or abs((tca - current_tca).total_seconds()) <= tolerance.total_seconds():
                current_cluster.append(cdm)
                # Update the reference TCA to the most recent TCA to allow rolling drift
                current_tca = tca
            else:
                # New cluster
                if current_cluster:
                    clusters.append(current_cluster)
                current_cluster = [cdm]
                current_tca = tca

        if current_cluster:
            clusters.append(current_cluster)

        # Create event IDs
        for cluster in clusters:
            # Use the first TCA as the reference
            ref_tca = cluster[0]["tca"] or "unknown"
            event_id = f"{pair[0]}_{pair[1]}_{ref_tca}"

            # Sort cluster by CREATED timestamp (chronological CDM order)
            cluster.sort(key=lambda c: c["created"] or "")
            events[event_id] = cluster

    return events


# ---------------------------------------------------------------------------
# Step 3: LEO filter via orbital data
# ---------------------------------------------------------------------------
def get_cached_orbits(conn: sqlite3.Connection, norad_ids: set[int]) -> dict[int, float]:
    """Get mean_motion for cached NORAD IDs."""
    result = {}
    for nid in norad_ids:
        row = conn.execute(
            "SELECT mean_motion FROM orbital_cache WHERE norad_id = ?", (nid,)
        ).fetchone()
        if row and row["mean_motion"] is not None:
            result[nid] = row["mean_motion"]
    return result


def fetch_and_cache_orbits(
    conn: sqlite3.Connection, norad_ids: list[int]
) -> dict[int, float]:
    """Fetch GP data from Space-Track and cache orbital elements."""
    email = os.getenv("SPACETRACK_EMAIL", "")
    password = os.getenv("SPACETRACK_PASSWORD", "")
    if not email or not password:
        log.warning("No Space-Track credentials — skipping orbital fetch")
        return {}

    result: dict[int, float] = {}

    # Batch into chunks of 200 IDs to avoid overly long URLs
    batch_size = 200
    batches = [norad_ids[i:i + batch_size] for i in range(0, len(norad_ids), batch_size)]

    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        # Authenticate
        log.info("Authenticating for GP orbital data…")
        resp = client.post(ST_LOGIN, data={"identity": email, "password": password})
        if resp.status_code != 200 or "Login Failed" in resp.text:
            log.error("GP auth failed")
            return {}

        now_iso = datetime.now(timezone.utc).isoformat()

        for i, batch in enumerate(batches):
            url = build_gp_url(batch)
            log.info(
                "Fetching GP data batch %d/%d (%d IDs)…",
                i + 1, len(batches), len(batch),
            )
            resp = client.get(url)
            if resp.status_code != 200:
                log.error("GP fetch failed (%d)", resp.status_code)
                continue

            data = resp.json()
            if not isinstance(data, list):
                continue

            # Deduplicate: keep latest epoch per NORAD ID
            latest: dict[int, dict] = {}
            for gp in data:
                nid = int(gp.get("NORAD_CAT_ID", 0))
                epoch = gp.get("EPOCH", "")
                if nid not in latest or epoch > latest[nid].get("EPOCH", ""):
                    latest[nid] = gp

            for nid, gp in latest.items():
                mm = None
                try:
                    mm = float(gp.get("MEAN_MOTION", 0))
                except (ValueError, TypeError):
                    pass

                ecc = None
                try:
                    ecc = float(gp.get("ECCENTRICITY", 0))
                except (ValueError, TypeError):
                    pass

                inc = None
                try:
                    inc = float(gp.get("INCLINATION", 0))
                except (ValueError, TypeError):
                    pass

                period = None
                try:
                    period = float(gp.get("PERIOD", 0))
                except (ValueError, TypeError):
                    pass

                apo = None
                try:
                    apo = float(gp.get("APOAPSIS", 0))
                except (ValueError, TypeError):
                    pass

                peri = None
                try:
                    peri = float(gp.get("PERIAPSIS", 0))
                except (ValueError, TypeError):
                    pass

                conn.execute(
                    """INSERT OR REPLACE INTO orbital_cache
                       (norad_id, mean_motion, eccentricity, inclination,
                        period, apoapsis, periapsis, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (nid, mm, ecc, inc, period, apo, peri, now_iso),
                )
                if mm is not None:
                    result[nid] = mm

            conn.commit()

            if i < len(batches) - 1:
                time.sleep(REQUEST_DELAY_SECONDS)

    return result


def apply_leo_filter(
    conn: sqlite3.Connection, events: dict[str, list[dict]]
) -> dict[str, list[dict]]:
    """Keep only events where at least one object is in LEO."""
    # Collect all unique NORAD IDs
    all_ids: set[int] = set()
    for cdms in events.values():
        for cdm in cdms:
            if cdm["sat_1_id"]:
                all_ids.add(cdm["sat_1_id"])
            if cdm["sat_2_id"]:
                all_ids.add(cdm["sat_2_id"])

    log.info("Need orbital data for %d unique objects", len(all_ids))

    # Check cache first
    orbits = get_cached_orbits(conn, all_ids)
    uncached = [nid for nid in all_ids if nid not in orbits]

    if uncached:
        log.info("%d objects not in orbital cache — fetching from Space-Track", len(uncached))
        new_orbits = fetch_and_cache_orbits(conn, uncached)
        orbits.update(new_orbits)

    log.info("Orbital data available for %d / %d objects", len(orbits), len(all_ids))

    # Filter
    leo_events = {}
    for event_id, cdms in events.items():
        s1 = cdms[0]["sat_1_id"]
        s2 = cdms[0]["sat_2_id"]

        mm1 = orbits.get(s1, 0)
        mm2 = orbits.get(s2, 0)

        # At least one object must be in LEO
        if mm1 > LEO_MEAN_MOTION_THRESHOLD or mm2 > LEO_MEAN_MOTION_THRESHOLD:
            leo_events[event_id] = cdms

    return leo_events


# ---------------------------------------------------------------------------
# Step 4: Build final output
# ---------------------------------------------------------------------------
def build_output(events: dict[str, list[dict]]) -> list[dict]:
    """Build the final clean sequence output."""
    output = []

    for event_id, cdms in events.items():
        # Extract sequence
        sequence = []
        max_pc = 0.0
        for cdm in cdms:
            pc_val = cdm["pc"] if cdm["pc"] is not None else 0.0
            max_pc = max(max_pc, pc_val)
            sequence.append({
                "cdm_id": cdm["cdm_id"],
                "created": cdm["created"],
                "tca": cdm["tca"],
                "pc": cdm["pc"],
                "miss_distance": cdm["min_rng"],
            })

        final_pc = sequence[-1]["pc"]
        early_pcs = [s["pc"] for s in sequence[:EARLY_CDM_COUNT]]
        is_critical = max_pc >= PC_CRITICAL_THRESHOLD

        if not is_critical:
            continue

        output.append({
            "event_id": event_id,
            "sat_1": {
                "id": cdms[0]["sat_1_id"],
                "name": cdms[0]["sat_1_name"],
                "type": cdms[0]["sat1_object_type"],
            },
            "sat_2": {
                "id": cdms[0]["sat_2_id"],
                "name": cdms[0]["sat_2_name"],
                "type": cdms[0]["sat2_object_type"],
            },
            "is_critical": is_critical,
            "num_cdms": len(cdms),
            "final_pc": final_pc,
            "early_pcs": early_pcs,
            "max_pc": max_pc,
            "sequence": sequence,
        })

    # Sort by max_pc descending (most interesting events first)
    output.sort(key=lambda e: e["max_pc"] or 0, reverse=True)
    return output


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info("=" * 60)
    log.info("Pc Maturation — Phase 2: Filtering & Sequence Building")
    log.info("=" * 60)

    if not DB_PATH.exists():
        log.error("Cache database not found at %s", DB_PATH)
        log.error("Run fetch_cdms.py first!")
        sys.exit(1)

    conn = init_db()

    # Step 1: Load raw CDMs
    log.info("Loading CDMs from cache…")
    cdms = load_cdms(conn)
    log.info("Loaded %d raw CDMs", len(cdms))

    if not cdms:
        log.error("No CDMs in cache — nothing to process")
        sys.exit(1)

    # Step 2: Group into events
    log.info("Grouping CDMs into conjunction events…")
    log.info("  Grouping key: sorted(SAT_1_ID, SAT_2_ID) + TCA ±%s", TCA_CLUSTER_TOLERANCE)
    events = group_into_events(cdms)
    log.info("Formed %d conjunction events", len(events))

    # Stats before filtering
    seq_lengths = [len(v) for v in events.values()]
    if seq_lengths:
        log.info("  Sequence lengths: min=%d, max=%d, mean=%.1f",
                 min(seq_lengths), max(seq_lengths),
                 sum(seq_lengths) / len(seq_lengths))

    # Step 3: LEO filter
    log.info("Applying LEO filter (mean_motion > %.2f rev/day)…", LEO_MEAN_MOTION_THRESHOLD)
    events = apply_leo_filter(conn, events)
    log.info("After LEO filter: %d events", len(events))

    # Step 4: Minimum sequence length filter
    log.info("Applying minimum sequence length filter (≥ %d CDMs)…", MIN_CDMS_PER_SEQUENCE)
    events = {eid: seq for eid, seq in events.items() if len(seq) >= MIN_CDMS_PER_SEQUENCE}
    log.info("After length filter: %d events", len(events))

    if not events:
        log.warning("No events survived filtering! Try adjusting config thresholds.")
        conn.close()
        return

    # Step 5: Build output
    log.info("Building output sequences…")
    output = build_output(events)

    # Count critical
    critical = sum(1 for e in output if e["is_critical"])

    # Write output
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)
    log.info("Written to %s", OUTPUT_PATH)

    # Final summary
    log.info("")
    log.info("=" * 60)
    log.info("SUMMARY")
    log.info("=" * 60)
    log.info("Total raw CDMs:          %d", len(cdms))
    log.info("Conjunction events:      %d (before filters)", len(group_into_events(cdms)))
    log.info("After LEO filter:        → then ≥%d CDMs filter", MIN_CDMS_PER_SEQUENCE)
    log.info("Final clean events:      %d", len(output))
    log.info("Critical events (Pc≥%.0e): %d", PC_CRITICAL_THRESHOLD, critical)

    if output:
        lengths = [e["num_cdms"] for e in output]
        log.info("Sequence lengths:        min=%d, max=%d, mean=%.1f",
                 min(lengths), max(lengths), sum(lengths) / len(lengths))
        log.info("")
        log.info("Top 5 events by max Pc:")
        for e in output[:5]:
            log.info(
                "  %s vs %s | %d CDMs | max Pc=%.2e | final Pc=%.2e",
                e["sat_1"]["name"], e["sat_2"]["name"],
                e["num_cdms"], e["max_pc"] or 0, e["final_pc"] or 0,
            )

    conn.close()


if __name__ == "__main__":
    main()
