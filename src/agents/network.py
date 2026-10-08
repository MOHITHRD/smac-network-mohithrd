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
VERSION = "0.3.1"

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

def _stops() -> list[dict]:
    """Boardable stops only.

    GTFS location_type 1 is a parent STATION record that groups its platforms
    (for example place_guyaft groups ferry stop 317572). Passengers board at
    the platforms (location_type 0), so listing a station beside its own
    platforms would count the same place twice. The 4 parent stations stay in
    the matching statistics for continuity with v1; they are excluded only
    from what the tools return and count.
    """
    return [s for s in M.load_stops() if s.get("location_type", "0") != "1"]


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

def _origin_context(lat: float, lon: float, snap_d: float) -> dict:
    """Where the supplied coordinate actually is, in named terms.

    match_confidence describes the stop -> footpath join. It cannot see an error
    made before this agent was called, such as a place name resolved to the
    wrong feature. This block names what the coordinate is next to, so a caller
    can notice that "the campus" has landed on a ferry terminal. Returned on
    every response, unrequested, like match_confidence.
    """
    stop = min(_stops(),
               key=lambda s: M.haversine_m(lat, lon, s["lat"], s["lon"]))
    return {
        "nearest_named_stop": stop["stop_name"],
        "nearest_stop_id": stop["stop_id"],
        "distance_to_nearest_stop_m": metres(M.haversine_m(lat, lon, stop["lat"], stop["lon"])),
        "distance_to_footpath_m": metres(snap_d),
        "note": ("Describes the coordinate supplied. If this is not where the "
                 "user meant, resolve the place again and call again."),
    }

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

    Starting point is a coordinate. If the user gave coordinates, pass them
    unchanged. If they gave a place name, resolve it with geocode_place and
    check what it matched before calling this tool: OpenStreetMap often returns
    a facility that merely shares the name, such as a ferry terminal, station,
    shop or office, instead of the campus, suburb or district the user meant.
    If match_kind is a facility but the user meant a larger place, look it up
    again using the place's full formal name. A geocode_place reply saying
    there is no match means the name was not found, NOT that the place is
    outside coverage: retry with a shorter or more formal name before
    answering. Every response includes origin_context, naming the stop nearest
    the coordinate supplied; if that is not where the user meant, resolve the
    place again and call again.

    Coverage is one pinned study area: the suburb of St Lucia, Brisbane
    (4.62 km2, including the University of Queensland St Lucia campus) - see
    the study_area field. Points outside it are declined. Data is a fixed dated
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
        ((s, M.haversine_m(lat, lon, s["lat"], s["lon"])) for s in _stops()),
        key=lambda t: t[1],
    )[: max_results * 3]

    entries = [_stop_entry(s, index[s["stop_id"]], origin_node) for s, _ in scored]
    entries.sort(key=lambda e: (not e["match_confidence"]["matched"],
                                e.get("walk", {}).get("distance_m", 10**9)))
    entries = entries[:max_results]

    routable = [e for e in entries if "walk" in e]
    payload = {
        "origin": {"lat": lat, "lon": lon},
        "origin_context": _origin_context(lat, lon, snap_d),
        "study_area": _study_area(),
        "matching_strategy": STRATEGY,
        "stops": entries,
        "stops_in_study_area": len(_stops()),
        "boardable_stops_in_study_area": len(_stops()),
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

    Origin and destination are coordinates. If the user gave coordinates, pass
    them unchanged. If they gave a place name, resolve it with geocode_place and
    check what it matched before calling this tool: OpenStreetMap often returns
    a facility that merely shares the name, such as a ferry terminal, station,
    shop or office, instead of the campus, suburb or district the user meant.
    If match_kind is a facility but the user meant a larger place, look it up
    again using the place's full formal name. A geocode_place reply saying
    there is no match means the name was not found, NOT that the place is
    outside coverage: retry with a shorter or more formal name before
    answering. Every response includes origin_context and destination_context,
    naming the stop nearest each coordinate supplied; if either is not where
    the user meant, resolve the place again and call again.

    Coverage is one pinned study area: the suburb of St Lucia, Brisbane
    (4.62 km2, including the University of Queensland St Lucia campus). Does NOT
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
        "origin_context": _origin_context(origin_lat, origin_lon, o_d),
        "destination_context": _origin_context(destination_lat, destination_lon, d_d),
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

# --- tool 3 -------------------------------------------------------------------

@mcp.tool()
@guard
def find_walking_route(
    origin_lat: Annotated[float, Field(description="WGS84 latitude of the start point, inside the St Lucia study area.")],
    origin_lon: Annotated[float, Field(description="WGS84 longitude of the start point, inside the St Lucia study area.")],
    destination_lat: Annotated[float, Field(description="WGS84 latitude of the end point, inside the St Lucia study area.")],
    destination_lon: Annotated[float, Field(description="WGS84 longitude of the end point, inside the St Lucia study area.")],
    explain: Annotated[bool, Field(description="Include a short written summary of the walk.")] = True,
) -> dict:
    """Measure the real walking route between two points in St Lucia, Brisbane: distance and time over the OpenStreetMap footpath network, the straight-line distance, and how much longer the walk is than the straight line.

    Use for "how far is it to walk from A to B", or to give another agent a
    true walking distance instead of a straight line (for example from a
    charger or a stop to a final destination). detour_ratio shows where roads,
    the river or missing crossings force a long way round: 1.0 is a straight
    walk, 3.0 means three times the straight-line distance. The route is
    returned as an ordered list of WGS84 points.

    Origin and destination are coordinates. If the user gave place names,
    resolve them with geocode_place and check what each matched: a ferry
    terminal, station, shop or office that merely shares the name is not the
    campus, suburb or district the user meant - look it up again with the full
    formal name. A geocode_place no-match means the name was not found, NOT
    that the place is outside coverage. origin_context and destination_context
    name the stop nearest each point so a wrong place can be noticed.

    Coverage is one pinned study area: the suburb of St Lucia, Brisbane
    (4.62 km2, including the University of Queensland St Lucia campus). Data is
    a fixed dated OpenStreetMap extract. Does NOT plan public transport,
    driving or cycling, and does NOT know about steps, gradients, lighting,
    wheelchair access or temporary closures.
    """
    checked = _locate_pair(origin_lat, origin_lon, destination_lat, destination_lon)
    if "status" in checked:
        return checked
    o_node, o_d, d_node, d_d = checked["o_node"], checked["o_d"], checked["d_node"], checked["d_d"]

    try:
        path = nx.shortest_path(_undirected(), o_node, d_node, weight="length")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        path = None
    network_m = _walk_m(o_node, d_node)
    if path is None or network_m is None:
        return respond({
            "status": "no_walking_route",
            "reason": "The two points are not connected in the mapped footpath network.",
            "study_area": _study_area(),
        }, sources=_sources())

    walk_m = network_m + o_d + d_d
    straight = M.haversine_m(origin_lat, origin_lon, destination_lat, destination_lon)
    G = M.load_graph()
    payload = {
        "status": "ok",
        "origin": {"lat": origin_lat, "lon": origin_lon},
        "destination": {"lat": destination_lat, "lon": destination_lon},
        "origin_context": _origin_context(origin_lat, origin_lon, o_d),
        "destination_context": _origin_context(destination_lat, destination_lon, d_d),
        "study_area": _study_area(),
        "distance_m": metres(walk_m),
        "duration_s": seconds(walk_m / WALK_SPEED_MS),
        "straight_line_m": metres(straight),
        "detour_ratio": round(walk_m / straight, 2) if straight >= 1 else 1.0,
        "path": [{"lat": round(G.nodes[n]["y"], 6), "lon": round(G.nodes[n]["x"], 6)} for n in path],
        "assumptions": {"walk_speed": f"{WALK_SPEED_MS} m/s (about 4.9 km/h)",
                        "includes_access_to_footpath": True},
        "data_gaps": ["steps_and_gradients", "lighting", "wheelchair_access", "temporary_closures"],
    }
    if explain:
        payload["summary"] = llm.ask(system=_SYSTEM_WALK, user=(
            f"Walking route: {payload['distance_m']} m, about "
            f"{payload['duration_s'] // 60} minutes. Straight-line distance "
            f"{payload['straight_line_m']} m, so the walk is {payload['detour_ratio']} "
            "times the straight line. Steps, gradients and accessibility are not known."))
    return respond(payload, sources=_sources())


# --- tool 4 -------------------------------------------------------------------

@mcp.tool()
@guard
def find_walkable_catchment(
    lat: Annotated[float, Field(description="WGS84 latitude of the centre point, inside the St Lucia study area.")],
    lon: Annotated[float, Field(description="WGS84 longitude of the centre point, inside the St Lucia study area.")],
    max_walk_s: Annotated[int, Field(description="Walking time budget in integer seconds, 60 to 1200 (1 to 20 minutes). 600 is a 10-minute walk.")] = 600,
    explain: Annotated[bool, Field(description="Include a short written summary of the catchment.")] = True,
) -> dict:
    """List every public transport stop reachable on foot within a time budget (60 to 1200 seconds, i.e. 1 to 20 minutes) from a point in St Lucia, Brisbane, with the size of the walkable area and how reliably each stop connects to the footpath network.

    Answers coverage and access questions: "how many stops are within a
    10-minute walk", "is this location well served on foot", "compare walking
    access at two places". Different from find_nearest_accessible_stops, which
    returns the few closest stops: this returns ALL stops inside the walking
    budget, a count, and the area reachable on foot. Walking speed is
    1.35 m/s (about 4.9 km/h, a standard planning speed).

    Stops include bus stops and ferry terminals; stop_name says which. Every
    stop carries a match_confidence object. Stops whose footpath connection is
    severed are listed separately in unreliable_stops and are not counted as
    reachable.

    The centre is a coordinate. If the user gave a place name, resolve it with
    geocode_place and check what it matched: a ferry terminal, station, shop or
    office that merely shares the name is not the campus, suburb or district
    the user meant - look it up again with the full formal name. A
    geocode_place no-match means the name was not found, NOT that the place is
    outside coverage. origin_context names the stop nearest the point so a
    wrong place can be noticed.

    Coverage is one pinned study area: the suburb of St Lucia, Brisbane
    (4.62 km2, including the University of Queensland St Lucia campus). The
    catchment is clipped to that area's mapped footpaths, so near its edge the
    true catchment is larger than reported. Data is a fixed dated extract of
    OpenStreetMap and TransLink GTFS, NOT live: no timetables, service
    frequency, real-time departures or fares.
    """
    if not in_seq(lat, lon):
        return out_of_scope(
            f"This agent covers South East Queensland; {lat}, {lon} is outside it.",
            sources=_sources())
    node, snap_d = _snap(lat, lon)
    if node is None:
        return out_of_scope(
            f"This agent covers the pinned walk network for {_study_area()}. "
            f"The nearest mapped footpath to {lat}, {lon} is {snap_d:.0f} m away, "
            "so this point lies outside the study area.",
            sources=_sources())

    budget_s = max(60, min(int(max_walk_s), 1200))
    minutes = budget_s // 60
    budget_m = budget_s * WALK_SPEED_MS
    reach = nx.single_source_dijkstra_path_length(
        _undirected(), node, cutoff=max(budget_m - snap_d, 0.0), weight="length")

    index = M.match_index(STRATEGY)
    reachable, unreliable = [], []
    for stop in _stops():
        m = index[stop["stop_id"]]
        if m.matched and m.node in reach:
            d = reach[m.node] + snap_d
            reachable.append((d, {
                "stop_id": stop["stop_id"], "stop_name": stop["stop_name"],
                "location": {"lat": stop["lat"], "lon": stop["lon"]},
                "walk": {"mode": "walk", "distance_m": metres(d),
                         "duration_s": seconds(d / WALK_SPEED_MS)},
                "match_confidence": m.public()}))
        elif not m.matched and M.haversine_m(lat, lon, stop["lat"], stop["lon"]) <= budget_m:
            unreliable.append({
                "stop_id": stop["stop_id"], "stop_name": stop["stop_name"],
                "location": {"lat": stop["lat"], "lon": stop["lon"]},
                "match_confidence": m.public()})
    reachable.sort(key=lambda t: t[0])

    G = M.load_graph()
    pts = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in reach]
    payload = {
        "origin": {"lat": lat, "lon": lon},
        "origin_context": _origin_context(lat, lon, snap_d),
        "study_area": _study_area(),
        "matching_strategy": STRATEGY,
        "walk_budget_s": seconds(budget_s),
        "walk_budget_m": metres(budget_m),
        "reachable_stop_count": len(reachable),
        "reachable_stops": [e for _, e in reachable],
        "unreliable_stops": unreliable,
        "catchment_area_m2": metres(_hull_area_m2(pts, lat, lon)),
        "assumptions": {"walk_speed": f"{WALK_SPEED_MS} m/s (about 4.9 km/h)",
                        "area_method": "convex hull of reachable footpath nodes",
                        "clipped_to_study_area": True},
        "data_gaps": ["timetables", "service_frequency", "real_time_departures", "fares"],
    }
    if explain:
        payload["summary"] = llm.ask(system=_SYSTEM, user=(
            f"Within about a {minutes}-minute walk ({payload['walk_budget_m']} m) "
            f"{len(reachable)} stops are reachable with a reliable footpath "
            f"connection, and {len(unreliable)} nearby stops have no reliable "
            f"connection under strategy {STRATEGY}. Walkable area about "
            f"{payload['catchment_area_m2']} square metres, clipped to the study area. "
            "Service frequency and timetables are not available."))
    return respond(payload, sources=_sources())


# --- helpers ------------------------------------------------------------------

def _locate_pair(o_lat: float, o_lon: float, d_lat: float, d_lon: float) -> dict:
    """Validate and snap two points. Returns a structured decline, or the nodes."""
    for lat, lon, label in ((o_lat, o_lon, "origin"), (d_lat, d_lon, "destination")):
        if not in_seq(lat, lon):
            return out_of_scope(
                f"This agent covers South East Queensland; the {label} "
                f"{lat}, {lon} is outside it.", sources=_sources())
    o_node, o_d = _snap(o_lat, o_lon)
    d_node, d_d = _snap(d_lat, d_lon)
    for node, dist, label in ((o_node, o_d, "origin"), (d_node, d_d, "destination")):
        if node is None:
            return out_of_scope(
                f"This agent covers the pinned walk network for {_study_area()}. "
                f"The nearest mapped footpath to the {label} is {dist:.0f} m away, "
                "so it lies outside the study area.", sources=_sources())
    return {"o_node": o_node, "o_d": o_d, "d_node": d_node, "d_d": d_d}


def _hull_area_m2(points: list[tuple[float, float]], lat0: float, lon0: float) -> float:
    """Area of the convex hull of (lat, lon) points, in square metres.

    Projects to a local flat plane around (lat0, lon0) - accurate to well under
    1 % across a few kilometres - then uses Andrew's monotone chain and the
    shoelace formula. No geospatial dependency is needed.
    """
    import math
    if len(points) < 3:
        return 0.0
    ky = 111_320.0
    kx = 111_320.0 * math.cos(math.radians(lat0))
    xy = sorted({((lon - lon0) * kx, (lat - lat0) * ky) for lat, lon in points})

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in xy:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(xy):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        return 0.0
    return abs(sum(hull[i][0] * hull[(i + 1) % len(hull)][1]
                   - hull[(i + 1) % len(hull)][0] * hull[i][1]
                   for i in range(len(hull)))) / 2.0



def _closest_usable(lat: float, lon: float, from_node: str, index: dict):
    """Nearest stop that has a usable access point, by network walking distance."""
    cands = sorted(
        ((s, M.haversine_m(lat, lon, s["lat"], s["lon"])) for s in _stops()),
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
        ((s, M.haversine_m(lat, lon, s["lat"], s["lon"])) for s in _stops()),
        key=lambda t: t[1],
    )[:8]
    return [{"stop_id": s["stop_id"], "stop_name": s["stop_name"],
             "match_confidence": index[s["stop_id"]].public()}
            for s, _ in cands if not index[s["stop_id"]].matched][:k]


# Separate prompt for find_walking_route. With the stop-access prompt the model
# described a point-to-point walk as "the walking route to the public transport
# stop" - prose framing that was not in the facts it was given (v0.3.0 test).
_SYSTEM_WALK = (
    "You summarise a walking route between two points. Use only the facts you "
    "are given. Never invent distances, places or public transport. At most "
    "two sentences."
)

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