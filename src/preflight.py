"""
preflight.py - check the things that break a first run, before they do.

    python preflight.py            # check
    python preflight.py --fetch    # check, and download the datasets

Four failures account for nearly every bad first run: the wrong Python, a
missing dependency, no API key, and a dataset that has to be downloaded at the
worst possible moment. Each check says what is wrong and where to fix it, rather
than leaving a stack trace to interpret.

Nothing here is fatal on its own. With no API key your tools still return their
computed facts, so that is reported as a warning and the run carries on.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

OK, WARN, FAIL = "ok", "warn", "fail"


def _check(name: str, status: str, detail: str, fix: str = "") -> dict:
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def check_python() -> dict:
    version = ".".join(str(n) for n in sys.version_info[:3])
    if sys.version_info < (3, 10):
        return _check("Python", FAIL, f"{version}; the MCP SDK will not install below 3.10",
                      "Rebuild the image, or run the stack with Docker where 3.12 is pinned.")
    return _check("Python", OK, version)


def check_dependencies() -> dict:
    missing = []
    for module in ("mcp", "httpx", "starlette", "uvicorn", "pydantic"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    if missing:
        return _check("Dependencies", FAIL, f"missing: {', '.join(missing)}",
                      'pip install "mcp>=2.0.0,<3" "httpx>=0.27"')
    import mcp                                                     # noqa: F401
    return _check("Dependencies", OK, "mcp, httpx, starlette, uvicorn, pydantic all import")


def check_api_key() -> dict:
    import llm

    if not llm.configured():
        return _check(
            "API key", WARN,
            "none set, so your tools will skip their written commentary",
            "Put one line in docker/.env, then restart:\n"
            "    ANTHROPIC_API_KEY=...\n"
            "Compose reads .env from the directory holding compose.yml, not the "
            "repository root. Never commit it.",
        )
    return _check("API key", OK, f"Claude API configured, default model {llm.model_name()}")


def check_datasets(fetch: bool = False) -> list[dict]:
    """Confirm each open dataset is reachable, and optionally cache it now."""
    import data

    results = []
    cache = Path(data.CACHE_DIR)

    def one(name: str, loader, describe, hint: str) -> dict:
        try:
            rows = loader()
        except Exception as exc:
            return _check(name, FAIL, f"{type(exc).__name__}: {exc}", hint)
        return _check(name, OK, describe(rows))

    if fetch or not any(cache.glob("*.json")):
        results.append(one(
            "EV charging stations",
            lambda: data.charging_stations(),
            lambda r: f"{len(r)} stations from data.qld.gov.au",
            "The CKAN datastore API may be down. The agent falls back to a stale cache if it has one.",
        ))
    else:
        results.append(_check("EV charging stations", OK, "cached"))

    archive = cache / "seq_gtfs.zip"
    if fetch or not archive.exists():
        results.append(one(
            "Translink GTFS",
            lambda: data.gtfs_table("stops.txt"),
            lambda r: f"{len(r)} stops, archive cached at {archive.name}",
            "This is a 28 MB download. Check the container has network access.",
        ))
    else:
        size_mb = archive.stat().st_size / 1e6
        results.append(_check("Translink GTFS", OK, f"cached, {size_mb:.0f} MB"))

    if fetch or not any(cache.glob("*.json")):
        results.append(one(
            "Patronage series",
            lambda: data.patronage_seq(),
            lambda r: f"{len(r)} monthly records",
            "The CKAN datastore API may be down.",
        ))
    else:
        results.append(_check("Patronage series", OK, "cached"))

    if fetch:
        results.append(one(
            "Geocoding (OpenStreetMap)",
            lambda: data.geocode("Queensland Museum, South Brisbane"),
            lambda hit: f"resolved to {hit['matched_name'][:48]}..." if hit else "no match",
            "Nominatim allows one request per second and requires a User-Agent; "
            "data.py sets both.",
        ))

    return results


def run_checks(fetch: bool = False) -> list[dict]:
    checks = [check_python(), check_dependencies()]
    if checks[1]["status"] == FAIL:
        return checks
    checks.append(check_api_key())
    checks.extend(check_datasets(fetch))
    return checks


def main() -> int:
    fetch = "--fetch" in sys.argv
    if fetch:
        print("Downloading datasets. The GTFS archive is 28 MB, so this takes a moment.\n")

    checks = run_checks(fetch)
    width = max(len(c["name"]) for c in checks)
    mark = {OK: "  ok  ", WARN: " warn ", FAIL: " FAIL "}
    for check in checks:
        print(f"[{mark[check['status']]}] {check['name']:<{width}}  {check['detail']}")
        if check["fix"]:
            for line in check["fix"].splitlines():
                print(f"{'':<{width + 11}}{line}")

    failed = [c for c in checks if c["status"] == FAIL]
    warned = [c for c in checks if c["status"] == WARN]
    print()
    if failed:
        print(f"{len(failed)} check(s) failed. Fix those before demonstrating.")
        return 1
    if warned:
        print(f"Ready, with {len(warned)} warning(s).")
        return 0
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
