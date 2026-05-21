"""
Phase 0.5 — Space Weather Fetcher
Fetches the public SW-Last5Years.txt from CelesTrak and stores the F10.7
solar flux index in the SQLite cache to correlate atmospheric drag with Pc volatility.
"""
import httpx
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "cache.db"
CELESTRAK_URL = "https://celestrak.org/SpaceData/SW-Last5Years.txt"

def setup_db(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS space_weather (
            date_str TEXT PRIMARY KEY,
            f107 REAL
        )"""
    )
    conn.commit()

def fetch_and_store_weather():
    log.info("Fetching Space Weather data from CelesTrak...")
    try:
        resp = httpx.get(CELESTRAK_URL, timeout=30.0)
        resp.raise_for_status()
    except Exception as e:
        log.error("Failed to fetch space weather: %s", e)
        return

    lines = resp.text.splitlines()
    
    conn = sqlite3.connect(DB_PATH)
    setup_db(conn)
    
    count = 0
    for line in lines:
        if not line or line.startswith("DATATYPE") or line.startswith("VERSION") or line.startswith("UPDATED") or line.startswith("#") or line.startswith("BEGIN") or line.startswith("END"):
            continue
            
        # Fixed width parsing or just split by whitespace
        # Format: YYYY MM DD ...
        cols = line.split()
        if len(cols) < 27:
            continue
            
        try:
            year, month, day = cols[0], cols[1], cols[2]
            f107 = float(cols[26])
            
            date_str = f"{year}-{month}-{day}"
            
            conn.execute(
                "INSERT OR REPLACE INTO space_weather (date_str, f107) VALUES (?, ?)",
                (date_str, f107)
            )
            count += 1
        except Exception as e:
            continue
            
    conn.commit()
    conn.close()
    log.info("Successfully cached F10.7 solar flux data for %d days.", count)

if __name__ == "__main__":
    fetch_and_store_weather()
