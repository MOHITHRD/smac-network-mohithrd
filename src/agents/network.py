"""
agents/network.py - Network & Routing Infrastructure agent.

    python agents/network.py      # serves on :8003

Joins OpenStreetMap's pedestrian network to TransLink GTFS stops for a pinned
South East Queensland study area, and reports how reliable that join is.

The two datasets share no identifier. Connecting a GTFS stop to a walkable node
is stop matching, and it is imperfect: a node metres away in a straight line may
be hundreds of metres away on foot across an untagged crossing. Every response
therefore carries a `match_confidence` object describing how the connection was
made and how far it can be trusted. That field is returned whether or not it was
asked for - the point is that a caller receives it without requesting it.
"""
import os
import sys
from pathlib import Path
from typing import Annotated

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import networkx as nx
from mcp.server import MCPServer
from pydantic import Field

import common
import data
import llm
import matching as M
from smac import check_identity, guard, in_seq, metres, out_of_scope, respond, seconds

AGENT_NAME = "smac-network-mohithrd"
VERSION = "0.1.0"

check_identity(AGENT_NAME, VERSION)
mcp = MCPServer(name=AGENT_NAME, version=VERSION)

# Which matching strategy is live. Set by environment, never by the caller:
# a caller-selectable strategy would be an uncontrolled experimental variable,
# and "which matching algorithm would you like?" is not a question a mobility
# orchestrator can meaningfully answer.
STRATEGY = os.environ.get("MATCH_STRATEGY", "M3").upper()

WALK_SPEED_MS = 1.35          # ~4.9 km/h, standard pedestrian planning speed
MAX_SNAP_M = 500              # further than this from any footpath = out of area


def _sources() -> list[str]:
    """Both datasets, with extract dates, per spec section 5."""
    mani = M.load_manifest()
    osm = mani.get("osm", {})
    gtfs = mani.get("gtfs", {})
    built = mani.get("built_utc", "")[:10]
    gtfs_licence = getattr(data, "GTFS_LICENCE", "TransLink SEQ GTFS (CC BY 4.0)")
    return [
        f"OpenStreetMap contributors via Overpass/OSMnx (ODbL 1.0), "
        f"{osm.get('network_type', 'walk')} network for "
        f"{mani.get('study_area', 'the study area')}, extract {built}",
        f"{gtfs_licence}, stops.txt filtered to the study area, extract {built}",
    ]


def _study_area() -> str:
    return M.load_manifest().get("study_area", "the configured study area")


# --- walk network helpers -----------------------------------------------------

_UG = None


def _undirected():
    global _UG
    if _UG is None:
        _UG = M.load_graph().to_undirected(as_view=True)
    return _UG


def _walk_m(a: str, b: str) -> float | None:
    """Shortest walking distance between two graph nodes, metres."""
    if a == b:
        return 0.0
    try:
        return nx.shortest_path_length(_undirected(), a, b, weight="length")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


def _snap(lat: float, lon: float):
    """Nearest walkable node to a point, or None if the point is outside the
    mapped study area."""
    node, dist = M.nearest_nodes(lat, lon, k=1)[0]
    return (node, dist) if dist <= MAX_SNAP_M else (None, dist)


def _leg(from_node: str, to_node: str) -> dict | None:
    d = _walk_m(from_node, to_node)
    if d is None:
        return None
    return {"mode": "walk",
            "distance_m": metres(d),
            "duration_s": seconds(d / WALK_SPEED_MS)}


def _stop_entry(stop: dict, match: M.Match, from_node: str | None) -> dict:
    """One stop with its match confidence and, if routable, the walk to it."""
    entry = {
        "stop_id": stop["stop_id"],
        "stop_name": stop["stop_name"],
        "location": {"lat": stop["lat"], "lon": stop["lon"]},
        "match_confidence": match.public(),
    }
    if match.matched and from_node:
        leg = _leg(from_node, match.node)
        if leg:
            entry["walk"] = leg
    return entry


common.register(mcp, agent_name=AGENT_NAME, version=VERSION,
                data_sources=_sources())


# --- tool 1 -------------------------------------------------------------------

@mcp.tool()
@guard
def find_nearest_accessible_stops(
    lat: Annotated[float, Field(description="WGS84 latitude of the starting point, inside the agent's study area.")],
    lon: Annotated[float, Field(description="WGS84 longitude of the starting point, inside the agent's study area.")],
    max_results: Annotated[int, Field(description="How many stops to return, 1 to 5.")] = 3,
    explain: Annotated[bool, Field(description="Include a short written summary of the access quality.")] = True,
) -> dict:
    """Find the public transport stops nearest a point, with the walking distance to each and how reliably each stop connects to the footpath network.

    Answers "which stop can I actually walk to from here" rather than "which stop
    is closest as the crow flies". Walking distances are computed over the
    OpenStreetMap pedestrian network, so a stop across an uncrossable road
    reports the real detour, not the straight line.

    Every stop carries a match_confidence object reporting how its coordinate was
    joined to the footpath network and whether that join is trustworthy. Some
    stops return no reliable access point at all: where the surrounding
    pedestrian network is severed by an untagged or absent crossing, which side
    of the barrier the stop sits on cannot be determined from its coordinate, and
    the stop is reported as unmatched rather than given a confident-looking
    nearest node.

    Coverage is one pinned South East Queensland study area only - see the
    study_area field. Points outside it are declined. Data is a fixed dated
    extract of OpenStreetMap and TransLink GTFS, NOT live: no timetables, no
    real-time departures, no service alerts, no fares, and no vehicle positions.
    """
    if not in_seq(lat, lon):
        return out_of_scope(
            f"This agent covers South East Queensland; {lat}, {lon} is outside it.",
            sources=_sources(),
        )

    origin_node, snap_d = _snap(lat, lon)
    if origin_node is None:
        return out_of_scope(
            f"This agent covers the pinned walk network for {_study_area()}. "
            f"The nearest mapped footpath to {lat}, {lon} is {snap_d:.0f} m away, "
            "so this point lies outside the study area.",
            sources=_sources(),
        )

    max_results = max(1, min(int(max_results), 5))
    index = M.match_index(STRATEGY)

    scored = sorted(
        ((s, M.haversine_m(lat, lon, s["lat"], s["lon"])) for s in M.load_stops()),
        key=lambda t: t[1],
    )[: max_results * 3]

    entries = [_stop_entry(s, index[s["stop_id"]], origin_node) for s, _ in scored]
    entries.sort(key=lambda e: (not e["match_confidence"]["matched"],
                                e.get("walk", {}).get("distance_m", 10**9)))
    entries = entries[:max_results]

    routable = [e for e in entries if "walk" in e]
    payload = {
        "origin": {"lat": lat, "lon": lon},
        "study_area": _study_area(),
        "matching_strategy": STRATEGY,
        "stops": entries,
        "stops_in_study_area": len(M.load_stops()),
        "unreachable_count": len(entries) - len(routable),
        "data_gaps": ["timetables", "real_time_departures", "service_alerts", "fares"],
    }

    if explain:
        payload["summary"] = _prose_stops(payload, routable, entries)

    return respond(payload, sources=_sources())


# --- tool 2 -------------------------------------------------------------------

@mcp.tool()
@guard
def find_multimodal_route(
    origin_lat: Annotated[float, Field(description="WGS84 latitude of the trip origin, inside the agent's study area.")],
    origin_lon: Annotated[float, Field(description="WGS84 longitude of the trip origin, inside the agent's study area.")],
    destination_lat: Annotated[float, Field(description="WGS84 latitude of the trip destination, inside the agent's study area.")],
    destination_lon: Annotated[float, Field(description="WGS84 longitude of the trip destination, inside the agent's study area.")],
    explain: Annotated[bool, Field(description="Include a short written summary of the route and its reliability.")] = True,
) -> dict:
    """Plan a walk-and-transit journey between two points, reporting the boarding and alighting stops, the walking legs over the real footpath network, and how reliably each stop connects to it.

    Composes the pedestrian half of a multi-modal trip: walk from the origin to a
    boarding stop, and from an alighting stop to the destination, with both walks
    routed over the OpenStreetMap pedestrian network rather than measured in a
    straight line. Returns the GTFS stop IDs for the transit leg so a timetable
    agent can complete it.

    Each stop carries a match_confidence object. Where the pedestrian network
    around a stop is severed by an untagged or absent crossing, no reliable
    access point exists, and the route is refused rather than returned with an
    access point that may be on the wrong side of the road.

    Coverage is one pinned South East Queensland study area only. Does NOT
    provide the transit leg itself: no departure times, journey durations,
    interchanges, route numbers, fares or real-time information - those come
    from schedule data this agent does not carry. Also does not plan driving,
    cycling or wheelchair-specific routes.
    """
    for lat, lon, label in ((origin_lat, origin_lon, "origin"),
                            (destination_lat, destination_lon, "destination")):
        if not in_seq(lat, lon):
            return out_of_scope(
                f"This agent covers South East Queensland; the {label} "
                f"{lat}, {lon} is outside it.",
                sources=_sources(),
            )

    o_node, o_d = _snap(origin_lat, origin_lon)
    d_node, d_d = _snap(destination_lat, destination_lon)
    for node, dist, label in ((o_node, o_d, "origin"), (d_node, d_d, "destination")):
        if node is None:
            return out_of_scope(
                f"This agent covers the pinned walk network for {_study_area()}. "
                f"The nearest mapped footpath to the {label} is {dist:.0f} m away, "
                "so it lies outside the study area.",
                sources=_sources(),
            )

    index = M.match_index(STRATEGY)
    board = _closest_usable(origin_lat, origin_lon, o_node, index)
    alight = _closest_usable(destination_lat, destination_lon, d_node, index)

    base = {
        "origin": {"lat": origin_lat, "lon": origin_lon},
        "destination": {"lat": destination_lat, "lon": destination_lon},
        "study_area": _study_area(),
        "matching_strategy": STRATEGY,
    }

    # No usable access point at one or both ends. Refuse, and say which stops
    # were rejected and why - a refusal with its reasoning is a correct answer.
    if board is None or alight is None:
        end = "origin" if board is None else "destination"
        near = M.match_index(STRATEGY)
        rejected = _rejected_near(
            origin_lat if end == "origin" else destination_lat,
            origin_lon if end == "origin" else destination_lon, near)
        return respond({
            **base,
            "status": "no_reliable_route",
            "reason": (
                f"No transit stop near the {end} has a reliable connection to the "
                f"pedestrian network under strategy {STRATEGY}. The nearest stops "
                "sit where the footpath network is severed, so the side of the "
                "barrier they stand on cannot be determined from their "
                "coordinates. Returning a route would place a walker at an access "
                "point that may be across an uncrossable road."
            ),
            "rejected_stops": rejected,
            "data_gaps": ["transit_leg", "departure_times", "fares", "real_time"],
        }, sources=_sources())

    b_stop, b_match = board
    a_stop, a_match = alight
    leg_in = _leg(o_node, b_match.node)
    leg_out = _leg(a_match.node, d_node)

    payload = {
        **base,
        "status": "ok",
        "boarding_stop": _stop_entry(b_stop, b_match, o_node),
        "alighting_stop": _stop_entry(a_stop, a_match, d_node),
        "legs": [
            {"sequence": 1, **(leg_in or {"mode": "walk", "distance_m": None}),
             "to_stop_id": b_stop["stop_id"]},
            {"sequence": 2, "mode": "transit", "status": "not_composed",
             "from_stop_id": b_stop["stop_id"], "to_stop_id": a_stop["stop_id"],
             "note": "This agent supplies the pedestrian network and stop access "
                     "only. Schedule, route and duration for this leg come from a "
                     "timetable source this agent does not carry."},
            {"sequence": 3, **(leg_out or {"mode": "walk", "distance_m": None}),
             "from_stop_id": a_stop["stop_id"]},
        ],
        "walk_total_m": metres((leg_in or {}).get("distance_m", 0)
                               + (leg_out or {}).get("distance_m", 0)),
        "data_gaps": ["transit_leg", "departure_times", "journey_duration",
                      "route_numbers", "fares", "real_time"],
    }

    if explain:
        payload["summary"] = _prose_route(payload, b_match, a_match)

    return respond(payload, sources=_sources())


# --- helpers ------------------------------------------------------------------

def _closest_usable(lat: float, lon: float, from_node: str, index: dict):
    """Nearest stop that has a usable access point, by network walking distance."""
    cands = sorted(
        ((s, M.haversine_m(lat, lon, s["lat"], s["lon"])) for s in M.load_stops()),
        key=lambda t: t[1],
    )[:12]
    usable = []
    for stop, _ in cands:
        m = index[stop["stop_id"]]
        if not m.matched:
            continue
        d = _walk_m(from_node, m.node)
        if d is not None:
            usable.append((d, stop, m))
    if not usable:
        return None
    usable.sort(key=lambda t: t[0])
    return usable[0][1], usable[0][2]


def _rejected_near(lat: float, lon: float, index: dict, k: int = 3) -> list[dict]:
    cands = sorted(
        ((s, M.haversine_m(lat, lon, s["lat"], s["lon"])) for s in M.load_stops()),
        key=lambda t: t[1],
    )[:8]
    return [{"stop_id": s["stop_id"], "stop_name": s["stop_name"],
             "match_confidence": index[s["stop_id"]].public()}
            for s, _ in cands if not index[s["stop_id"]].matched][:k]


# The model writes prose about numbers already computed. It is never asked for
# a distance, a confidence, or a judgement about reliability - only to restate
# facts it is handed. Note for the evaluation: prose that already narrates
# uncertainty may be relayed by an orchestrator rather than inferred from the
# structured field, so `explain=False` is the cleaner condition when measuring
# uncertainty handling.
_SYSTEM = (
    "You explain pedestrian access to public transport stops. Use only the "
    "facts you are given. Never invent distances, timetables, route numbers or "
    "fares, and never describe a connection as reliable if you are told it is "
    "not. At most three sentences."
)


def _prose_stops(payload: dict, routable: list, entries: list) -> str:
    if not routable:
        return llm.ask(system=_SYSTEM, user=(
            f"No stop near this point has a reliable footpath connection under "
            f"strategy {payload['matching_strategy']}. "
            f"{len(entries)} stops were considered and all were rejected."))
    top = routable[0]
    return llm.ask(system=_SYSTEM, user=(
        f"Closest reachable stop: {top['stop_name']} (id {top['stop_id']}), "
        f"{top['walk']['distance_m']} m walk, about "
        f"{top['walk']['duration_s'] // 60} minutes. "
        f"Match quality: {top['match_confidence']['quality']}. "
        f"{top['match_confidence']['reason']} "
        f"{payload['unreachable_count']} of the nearby stops had no reliable "
        f"access point. Timetables and real-time departures are not available."))


def _prose_route(payload: dict, b: M.Match, a: M.Match) -> str:
    return llm.ask(system=_SYSTEM, user=(
        f"Walk {payload['legs'][0].get('distance_m')} m to "
        f"{payload['boarding_stop']['stop_name']} (id "
        f"{payload['boarding_stop']['stop_id']}), match quality {b.quality}. "
        f"Then transit to {payload['alighting_stop']['stop_name']} (id "
        f"{payload['alighting_stop']['stop_id']}), match quality {a.quality}, "
        f"then walk {payload['legs'][2].get('distance_m')} m to the destination. "
        "The transit leg itself, its departure times, route number and duration "
        "are not available from this agent."))


if __name__ == "__main__":
    # Warm the caches so the first tool call is a lookup, not a graph build.
    M.load_graph()
    stats = M.statistics(STRATEGY)
    print(f"{AGENT_NAME} {VERSION} | {_study_area()} | strategy {STRATEGY} | "
          f"{stats['matched']}/{stats['stops']} stops matched "
          f"(MRR {stats['mrr'] * 100:.1f}%)", flush=True)

    mcp.run(transport="streamable-http", host="0.0.0.0",
            port=int(os.environ.get("PORT", "8000")))