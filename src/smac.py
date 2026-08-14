"""
smac.py - shared plumbing for every REIT7820 agent.

You do not need to edit this file. You should read it once, though: every
function here exists because the specification requires something, and using
them is what makes your agent pass the Week 9 handshake test.
"""

from __future__ import annotations

import functools
import inspect
import math
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FuturesTimeout
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable

# Identity

# The seven domains are fixed by the specification. The kit ships skeletons for
# the first three, but this must accept every name the spec permits - rejecting
# a conformant agent here would fail you at startup for something the spec
# explicitly allows.
DOMAINS = "charging|pt|policy|equity|network|weather|custom"
AGENT_NAME_RE = re.compile(rf"^smac-({DOMAINS})-[a-z0-9]+(-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def check_identity(agent_name: str, version: str) -> None:
    """Fail loudly at startup rather than quietly at the handshake test."""
    if not AGENT_NAME_RE.match(agent_name):
        raise ValueError(
            f"AGENT_NAME {agent_name!r} does not match the required pattern:\n"
            "  smac-{domain}-{slot}, lowercase and hyphenated\n"
            "  domain must be one of: charging pt policy equity network weather custom\n"
            "  e.g. smac-charging-reliability"
        )
    if not SEMVER_RE.match(version):
        raise ValueError(f"VERSION {version!r} must be semantic, e.g. '1.0.0'")


# Response envelope

def respond(payload: dict[str, Any], sources: Iterable[str]) -> dict[str, Any]:
    """Return a tool result with the mandatory `sources` array attached.

    Every tool response MUST cite the dataset or API behind the answer.
    Returning through this function is the easiest way to never forget.

        return respond({"chargers": [...]}, sources=["OpenChargeMap (ODbL)"])
    """
    sources = [s for s in sources if s]
    if not sources:
        raise ValueError(
            "Every response needs at least one source. "
            "Cite the dataset or API that backs this answer."
        )
    return {**payload, "sources": sources}


def out_of_scope(reason: str, sources: Iterable[str] = ()) -> dict[str, Any]:
    """Say honestly that a query is outside your coverage.

    Do NOT invent an answer for a question you cannot serve. Behaviour under
    out-of-scope queries is part of the Showcase rubric, and the Orchestrator
    can route to another agent if you tell it plainly that you cannot help.
    """
    return {"status": "out_of_scope", "reason": reason, "sources": list(sources)}


# Safety wrapper

TOOL_BUDGET_SECONDS = 45.0  # spec allows 45s; we return before that

_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="smac-tool")


def guard(fn):
    """Wrap a tool so it can never crash the server or blow the time budget.

    Put it *under* the @mcp.tool() decorator:

        @mcp.tool()
        @guard
        def my_tool(...): ...

    Three things happen:
      1. Any exception becomes a readable MCP tool error instead of a crash.
      2. Anything still running at 40s is abandoned with a clear timeout error,
         so you stay inside the 45s budget.
      3. Your docstring is cleaned up, so the indentation of a multi-line
         docstring does not leak into the description the Orchestrator reads.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return _POOL.submit(fn, *args, **kwargs).result(timeout=TOOL_BUDGET_SECONDS)
        except _FuturesTimeout:
            raise RuntimeError(
                f"{fn.__name__} did not finish within {TOOL_BUDGET_SECONDS:.0f}s. "
                "Cache your data or narrow the query - the spec limit is 45s."
            ) from None
        except Exception as exc:  # noqa: BLE001 - deliberate: never crash
            raise RuntimeError(f"{fn.__name__} failed: {type(exc).__name__}: {exc}") from None

    if wrapper.__doc__:
        wrapper.__doc__ = inspect.cleandoc(wrapper.__doc__)
    return wrapper


# Data conventions. Use these rather than hand-rolling them.

# South East Queensland, generously bounded: Noosa in the north, the NSW
# border in the south, Toowoomba in the west, the coast in the east.
SEQ_BBOX = {"lat_min": -28.30, "lat_max": -26.00, "lon_min": 151.50, "lon_max": 153.60}

BRISBANE_TZ = timezone(timedelta(hours=10))  # AEST year-round, no daylight saving


def in_seq(lat: float, lon: float) -> bool:
    """True if a WGS84 point is inside the theme's SEQ coverage area."""
    return (
        SEQ_BBOX["lat_min"] <= lat <= SEQ_BBOX["lat_max"]
        and SEQ_BBOX["lon_min"] <= lon <= SEQ_BBOX["lon_max"]
    )


def now_brisbane() -> str:
    """Current time as ISO 8601 with timezone, e.g. 2026-08-08T15:04:05+10:00."""
    return datetime.now(BRISBANE_TZ).isoformat(timespec="seconds")


def money(amount: float | int | str | Decimal) -> str:
    """AUD as a decimal string: money(0.5) -> '0.50'.

    This is the convention students most often get wrong. The spec wants a
    string, not a float - floats cannot represent cents exactly.
    """
    return str(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def metres(value: float) -> int:
    """Distances are integer metres."""
    return int(round(value))


def seconds(value: float) -> int:
    """Durations are integer seconds."""
    return int(round(value))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Great-circle distance between two WGS84 points, in metres."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return metres(2 * r * math.asin(math.sqrt(a)))
