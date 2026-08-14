"""
data.py - fetching open data, with a cache.

Two sources, both open, both keyless:

  * Queensland Government charging stations, via the data.qld.gov.au CKAN
    datastore API. Returns clean JSON - use this rather than the published CSV,
    which contains embedded newlines inside quoted fields.
  * OpenStreetMap place lookup, via Nominatim (ODbL). The specification requires openly
    licensed sources, which rules out Google Maps geocoding.

Everything is cached on disk. That is not an optimisation: a tool call must
return within 45 seconds, and Nominatim's public endpoint allows only one
request per second. Fifty-five agents calling it live would get the cohort
blocked.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

import csv
import io
import zipfile

import httpx

CACHE_DIR = Path(__file__).with_name(".cache")
CACHE_DIR.mkdir(exist_ok=True)

# data.qld.gov.au - "Find a charging station - Electric vehicle", CC BY 4.0
QLD_API = "https://www.data.qld.gov.au/api/3/action/datastore_search"
QLD_RESOURCE_ID = "a34d4b5f-8e3c-4995-8950-2e84fd7bb4d5"
QLD_LICENCE = "Queensland Government (TMR) via data.qld.gov.au, CC BY 4.0"

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OSM_LICENCE = "© OpenStreetMap contributors, ODbL 1.0"
USER_AGENT = "REIT7820-SMAC-agent/0.1 (UQ teaching project)"

_nominatim_lock = threading.Lock()
_nominatim_last = 0.0


def _cached(key: str, ttl_seconds: int, fetch) -> Any:
    """Return cached JSON if fresh, else fetch and store. Falls back to a stale
    copy if the fetch fails - a publisher outage must not fail your tool call."""
    path = CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest()[:16] + ".json")
    if path.exists() and time.time() - path.stat().st_mtime < ttl_seconds:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        payload = fetch()
        path.write_text(json.dumps(payload), encoding="utf-8")
        return payload
    except Exception:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        raise


def charging_stations(ttl_seconds: int = 6 * 3600) -> list[dict]:
    """All Queensland Electric Super Highway stations, as clean records.

    Fields kept: name, lat, lon, address, host, status, onward_stations.
    The source publishes a `Charging plugs available` column that is empty for
    every row, so it is left out rather than reported as unknown
    detail your caller might mistake for real.
    """
    def fetch():
        response = httpx.get(
            QLD_API,
            params={"resource_id": QLD_RESOURCE_ID, "limit": 1000},
            timeout=20.0,
        )
        response.raise_for_status()
        return response.json()["result"]["records"]

    stations = []
    for row in _cached(f"qld:{QLD_RESOURCE_ID}", ttl_seconds, fetch):
        try:
            lat, lon = float(row["Latitude"]), float(row["Longitude"])
        except (KeyError, TypeError, ValueError):
            continue  # skip malformed rows rather than crashing
        stations.append(
            {
                "name": str(row.get("Location Name", "")).strip(),
                "lat": lat,
                "lon": lon,
                "address": " ".join(str(row.get("Address", "")).split()),
                "host": str(row.get("Host", "")).strip() or None,
                "status": str(row.get("Status", "")).strip() or None,
                "onward_stations": " ".join(str(row.get("Nearest QESH charging station", "")).split()) or None,
            }
        )
    return stations


def geocode(place: str, ttl_seconds: int = 30 * 24 * 3600) -> dict | None:
    """Look up a place name on OpenStreetMap. Returns None if there is no match.

    Cached for a month and rate-limited to Nominatim's published 1 req/sec.
    """
    query = (place or "").strip()
    if not query:
        return None

    def fetch():
        global _nominatim_last
        with _nominatim_lock:
            wait = 1.1 - (time.time() - _nominatim_last)
            if wait > 0:
                time.sleep(wait)
            _nominatim_last = time.time()
        response = httpx.get(
            NOMINATIM,
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "au"},
            headers={"User-Agent": USER_AGENT},
            timeout=20.0,
        )
        response.raise_for_status()
        return response.json()

    results = _cached(f"osm:{query.lower()}", ttl_seconds, fetch)
    if not results:
        return None
    hit = results[0]
    return {
        "lat": float(hit["lat"]),
        "lon": float(hit["lon"]),
        "matched_name": hit.get("display_name"),
        # building vs suburb vs administrative area - precision varies hugely,
        # and the caller deserves to know which it got.
        "match_kind": f"{hit.get('class', '?')}/{hit.get('type', '?')}",
    }


# Translink GTFS, used by the public transport agent.
# data.qld.gov.au dataset: general-transit-feed-specification-gtfs-translink
GTFS_URL = "https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip"
GTFS_LICENCE = "Translink SEQ GTFS via data.qld.gov.au, CC BY 4.0"

_GTFS_CACHE: dict[str, list[dict]] = {}


def gtfs_table(filename: str, ttl_seconds: int = 24 * 3600) -> list[dict]:
    """Read one file out of the SEQ GTFS archive.

    The archive is 28 MB compressed. Only ask for the small members:
    stops.txt is 1.6 MB and routes.txt is 0.13 MB, but **stop_times.txt is
    164 MB uncompressed** and must never be parsed inside a tool call - you
    would blow the 45-second budget many times over. If you need
    timetables, index that file once at startup into your own structure.
    """
    if filename in _GTFS_CACHE:
        return _GTFS_CACHE[filename]

    archive = CACHE_DIR / "seq_gtfs.zip"
    if not archive.exists() or time.time() - archive.stat().st_mtime > ttl_seconds:
        with httpx.stream("GET", GTFS_URL, timeout=180.0, follow_redirects=True) as response:
            response.raise_for_status()
            with archive.open("wb") as fh:
                for chunk in response.iter_bytes():
                    fh.write(chunk)

    with zipfile.ZipFile(archive) as z, z.open(filename) as member:
        rows = list(csv.DictReader(io.TextIOWrapper(member, encoding="utf-8-sig")))

    # GTFS values arrive space-padded in this feed: ' -27.467834'.
    _GTFS_CACHE[filename] = [{k: (v.strip() if isinstance(v, str) else v) for k, v in r.items()} for r in rows]
    return _GTFS_CACHE[filename]


# Translink patronage, used by the policy agent.
PATRONAGE_SEQ_ID = "c49df919-5c0d-4bd2-9e43-776509b95ef6"
PATRONAGE_LICENCE = "Translink monthly performance data via data.qld.gov.au, CC BY 3.0"


def patronage_seq(ttl_seconds: int = 24 * 3600) -> list[dict]:
    """Monthly SEQ passenger trips by mode.

    Returns records with `month` (ISO 8601 date), `mode` and `trips` (int).
    The published fields are 'Month-Year' ("Dec-2023") and 'Passenger trips'
    (a string) - both normalised here so tools never repeat the parsing.
    """
    def fetch():
        response = httpx.get(
            QLD_API,
            params={"resource_id": PATRONAGE_SEQ_ID, "limit": 1000},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()["result"]["records"]

    from datetime import datetime

    records = []
    for row in _cached(f"patronage:{PATRONAGE_SEQ_ID}", ttl_seconds, fetch):
        try:
            month = datetime.strptime(str(row["Month-Year"]).strip(), "%b-%Y")
            trips = int(float(row["Passenger trips"]))
        except (KeyError, TypeError, ValueError):
            continue  # skip malformed rows rather than crashing
        records.append({"month": month.strftime("%Y-%m-01"), "mode": str(row["Mode"]).strip(), "trips": trips})
    return sorted(records, key=lambda r: (r["month"], r["mode"]))
