"""
matching.py - OSM-to-GTFS stop matching for smac-network-mohithrd.

Implements the function M: S -> N u {None} three ways, over the pinned study
area artefacts built by scripts/build_graph.py.

    M1  naive nearest node          no constraint; never fails, sometimes lies
    M2  distance-constrained        nearest node within tau, else None
    M3  severance-verified          M2, plus reject where the local pedestrian
                                    network is severed and the stop's true side
                                    of the barrier cannot be determined

Run it directly to print the comparison table:

    python src/matching.py

Everything here is arithmetic and graph search. No model is asked for a number.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path

import networkx as nx

# --- configuration ------------------------------------------------------------

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
SLUG = "stlucia"

# tau: maximum straight-line matching distance, metres.
# 400 m follows Hillsman & Barbeau's empirically chosen threshold for GTFS-OSM
# conflict detection in Tampa.
TAU = 400

# rho: severance ratio. If two candidate nodes near a stop are RHO times further
# apart across the walk network than in a straight line, the network there is
# severed by an untagged or absent crossing, and which side the stop sits on
# cannot be resolved from its coordinate alone.
RHO = 8.0

# Straight-line separation below which two candidates are treated as "opposite
# sides of the same barrier" rather than genuinely different locations, metres.
SEVERANCE_PAIR_MAX_M = 60

# Bounded Dijkstra cutoff for the severance check, metres. Anything beyond this
# is severed for practical walking purposes regardless of the exact figure.
NETWORK_CUTOFF_M = 1500

# How many nearest candidates to consider when testing for severance.
K_CANDIDATES = 6

STRATEGIES = ("M1", "M2", "M3")


# --- geometry -----------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres, float precision.

    Mirrors smac.haversine_m but does not round - matching statistics are
    computed at full precision and rounded only at the response boundary,
    where the spec requires integer metres.
    """
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --- artefact loading ---------------------------------------------------------

@lru_cache(maxsize=1)
def load_graph(slug: str = SLUG) -> nx.MultiDiGraph:
    """Load the pinned walk network.

    Read with plain networkx rather than osmnx: the agent image carries
    networkx only, so Overpass and the geospatial stack stay offline-only and
    a tool call never leaves the machine.
    """
    path = ARTIFACTS / f"{slug}_walk.graphml"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run: python scripts/build_graph.py"
        )
    G = nx.read_graphml(path)

    # osmnx writes GraphML attributes as strings; cast the ones we use.
    for _, attrs in G.nodes(data=True):
        attrs["x"] = float(attrs["x"])
        attrs["y"] = float(attrs["y"])
    for _, _, attrs in G.edges(data=True):
        try:
            attrs["length"] = float(attrs.get("length", 0.0))
        except (TypeError, ValueError):
            attrs["length"] = 0.0
    return G


@lru_cache(maxsize=1)
def load_stops(slug: str = SLUG) -> tuple[dict, ...]:
    """Load the GTFS stops inside the study area boundary."""
    path = ARTIFACTS / f"{slug}_stops.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run: python scripts/build_graph.py"
        )
    with path.open(newline="", encoding="utf-8") as f:
        rows = []
        for r in csv.DictReader(f):
            rows.append({
                "stop_id": r["stop_id"],
                "stop_name": r.get("stop_name", ""),
                "lat": float(r["stop_lat"]),
                "lon": float(r["stop_lon"]),
            })
    return tuple(rows)


@lru_cache(maxsize=1)
def load_manifest() -> dict:
    path = ARTIFACTS / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else {}


# --- candidate search ---------------------------------------------------------

@lru_cache(maxsize=1)
def _node_coords(slug: str = SLUG) -> tuple[tuple[str, float, float], ...]:
    G = load_graph(slug)
    return tuple((n, a["y"], a["x"]) for n, a in G.nodes(data=True))


def nearest_nodes(lat: float, lon: float, k: int = 1, slug: str = SLUG):
    """The k nearest graph nodes to a point, as [(node_id, distance_m), ...].

    Brute force over ~2,200 nodes is well under a millisecond, so no spatial
    index is needed and no extra dependency is introduced.
    """
    scored = ((n, haversine_m(lat, lon, ny, nx_)) for n, ny, nx_ in _node_coords(slug))
    return sorted(scored, key=lambda t: t[1])[:k]


def network_distance(source: str, target: str, slug: str = SLUG) -> float | None:
    """Shortest walking distance between two nodes, metres, or None if beyond
    the cutoff."""
    G = load_graph(slug)
    try:
        lengths = nx.single_source_dijkstra_path_length(
            G.to_undirected(as_view=True), source,
            cutoff=NETWORK_CUTOFF_M, weight="length",
        )
    except nx.NodeNotFound:
        return None
    return lengths.get(target)


# --- the match record ---------------------------------------------------------

@dataclass
class Match:
    """One stop, matched by one strategy. This IS the confidence object."""
    stop_id: str
    stop_name: str
    strategy: str
    matched: bool
    node: str | None = None
    straight_line_m: float | None = None
    threshold_m: int = TAU
    severance_ratio: float | None = None
    quality: str = "unmatched"      # high | borderline | severed | unmatched
    reason: str = ""

    def public(self) -> dict:
        """Response-safe form: integer metres, spec section 5."""
        d = asdict(self)
        if d["straight_line_m"] is not None:
            d["straight_line_m"] = int(round(d["straight_line_m"]))
        if d["severance_ratio"] is not None:
            d["severance_ratio"] = round(d["severance_ratio"], 1)
        return d


# --- M1: naive nearest node ---------------------------------------------------

def match_m1(stop: dict, slug: str = SLUG) -> Match:
    """Nearest node, unconditionally. The unconstrained control condition.

    Never returns None, which is precisely the problem: a stop 900 m from any
    footpath still gets a confident-looking match.
    """
    node, dist = nearest_nodes(stop["lat"], stop["lon"], k=1, slug=slug)[0]
    return Match(
        stop_id=stop["stop_id"], stop_name=stop["stop_name"], strategy="M1",
        matched=True, node=node, straight_line_m=dist,
        quality="high" if dist <= TAU else "borderline",
        reason=("matched to nearest node; no distance or reachability constraint applied"
                if dist <= TAU else
                f"nearest node is {dist:.0f} m away, beyond tau={TAU} m, "
                "but M1 applies no constraint and matched it anyway"),
    )


# --- M2: distance-constrained -------------------------------------------------

def match_m2(stop: dict, slug: str = SLUG) -> Match:
    """Nearest node within tau, otherwise refuse rather than force a bad match."""
    node, dist = nearest_nodes(stop["lat"], stop["lon"], k=1, slug=slug)[0]
    if dist > TAU:
        return Match(
            stop_id=stop["stop_id"], stop_name=stop["stop_name"], strategy="M2",
            matched=False, straight_line_m=dist, quality="unmatched",
            reason=(f"nearest walkable node is {dist:.0f} m away, beyond the "
                    f"{TAU} m threshold; no reliable pedestrian access point exists"),
        )
    borderline = dist > 0.75 * TAU
    return Match(
        stop_id=stop["stop_id"], stop_name=stop["stop_name"], strategy="M2",
        matched=True, node=node, straight_line_m=dist,
        quality="borderline" if borderline else "high",
        reason=(f"matched within threshold at {dist:.0f} m"
                + (f", close to the {TAU} m limit" if borderline else "")),
    )


# --- M3: severance-verified ---------------------------------------------------

def match_m3(stop: dict, slug: str = SLUG) -> Match:
    """M2, then reject where the surrounding network is severed.

    Rationale. The failure M3 targets is a stop whose nearest node lies across
    an untagged or absent crossing: metres away in a straight line, hundreds of
    metres away on foot. A single node cannot reveal this. Two nearby nodes can:
    if candidates that are close in a straight line are far apart across the
    network, a barrier runs between them, and the stop's true side of that
    barrier cannot be resolved from its coordinate alone.

    This operationalises R(si) for a node-based graph, where a pure reachability
    test is vacuous because the St Lucia walk network is fully connected
    (1 component, 2239/2239 nodes).
    """
    base = match_m2(stop, slug=slug)
    if not base.matched:
        base.strategy = "M3"
        return base

    cands = [(n, d) for n, d in
             nearest_nodes(stop["lat"], stop["lon"], k=K_CANDIDATES, slug=slug)
             if d <= TAU]
    primary, primary_d = cands[0]

    worst_ratio = None
    worst_node = None
    for node, straight in cands[1:]:
        pair_sep = _pair_separation(primary, node, slug)
        if pair_sep is None or pair_sep > SEVERANCE_PAIR_MAX_M:
            continue
        net = network_distance(primary, node, slug=slug)
        if net is None:                       # beyond cutoff: fully severed
            worst_ratio, worst_node = float("inf"), node
            break
        if pair_sep < 1.0:
            continue
        ratio = net / pair_sep
        if worst_ratio is None or ratio > worst_ratio:
            worst_ratio, worst_node = ratio, node

    if worst_ratio is not None and worst_ratio >= RHO:
        shown = None if worst_ratio == float("inf") else worst_ratio
        return Match(
            stop_id=stop["stop_id"], stop_name=stop["stop_name"], strategy="M3",
            matched=False, straight_line_m=primary_d, severance_ratio=shown,
            quality="severed",
            reason=(f"nearest node is {primary_d:.0f} m away, but the pedestrian "
                    f"network around this stop is severed: a neighbouring access "
                    f"point is "
                    + ("unreachable within 1500 m on foot"
                       if worst_ratio == float("inf")
                       else f"{worst_ratio:.0f}x further on foot than in a straight line")
                    + ". The stop's side of the barrier cannot be determined from "
                      "its coordinate, so no reliable match is returned."),
        )

    return Match(
        stop_id=stop["stop_id"], stop_name=stop["stop_name"], strategy="M3",
        matched=True, node=primary, straight_line_m=primary_d,
        severance_ratio=None if worst_ratio in (None, float("inf")) else worst_ratio,
        quality=base.quality,
        reason=(f"matched within threshold at {primary_d:.0f} m; surrounding "
                "pedestrian network is continuous, so the access point is "
                "reachable without an undocumented crossing"),
    )


def _pair_separation(a: str, b: str, slug: str) -> float | None:
    G = load_graph(slug)
    try:
        na, nb = G.nodes[a], G.nodes[b]
    except KeyError:
        return None
    return haversine_m(na["y"], na["x"], nb["y"], nb["x"])


# --- driver -------------------------------------------------------------------

MATCHERS = {"M1": match_m1, "M2": match_m2, "M3": match_m3}


def match_stop(stop: dict, strategy: str = "M3", slug: str = SLUG) -> Match:
    if strategy not in MATCHERS:
        raise ValueError(f"unknown strategy {strategy!r}; expected one of {STRATEGIES}")
    return MATCHERS[strategy](stop, slug=slug)


@lru_cache(maxsize=8)
def match_all(strategy: str = "M3", slug: str = SLUG) -> tuple[Match, ...]:
    """Every stop in the study area, matched. Computed once and cached, so a
    tool call is a dictionary lookup rather than a graph search."""
    return tuple(match_stop(s, strategy=strategy, slug=slug) for s in load_stops(slug))


def match_index(strategy: str = "M3", slug: str = SLUG) -> dict[str, Match]:
    return {m.stop_id: m for m in match_all(strategy, slug)}


# --- statistics ---------------------------------------------------------------

def statistics(strategy: str, slug: str = SLUG) -> dict:
    """MRR, unmatched rate and mean matching distance, per section 3.2.2."""
    matches = match_all(strategy, slug)
    total = len(matches)
    resolved = [m for m in matches if m.matched]
    dists = [m.straight_line_m for m in resolved if m.straight_line_m is not None]
    return {
        "strategy": strategy,
        "stops": total,
        "matched": len(resolved),
        "unmatched": total - len(resolved),
        "mrr": len(resolved) / total if total else 0.0,
        "unmatched_rate": (total - len(resolved)) / total if total else 0.0,
        "mean_matching_distance_m": sum(dists) / len(dists) if dists else None,
        "max_matching_distance_m": max(dists) if dists else None,
        "high": sum(1 for m in resolved if m.quality == "high"),
        "borderline": sum(1 for m in resolved if m.quality == "borderline"),
        "severed": sum(1 for m in matches if m.quality == "severed"),
    }


def _table() -> str:
    mani = load_manifest()
    osm, gtfs = mani.get("osm", {}), mani.get("gtfs", {})
    rows = [statistics(s) for s in STRATEGIES]

    out = []
    out.append("=" * 78)
    out.append("  OSM-to-GTFS STOP MATCHING  -  smac-network-mohithrd")
    out.append("=" * 78)
    out.append(f"  study area   {mani.get('study_area', '?')}")
    out.append(f"  walk network {osm.get('nodes', '?')} nodes, {osm.get('edges', '?')} edges")
    out.append(f"  GTFS stops   {gtfs.get('stops_in_study_area', '?')} "
               f"(of {gtfs.get('stops_in_feed', '?')} in feed)")
    out.append(f"  extract      {mani.get('built_utc', '?')[:10]}")
    out.append(f"  parameters   tau={TAU} m   rho={RHO}   k={K_CANDIDATES}")
    out.append("")
    out.append(f"  {'':4} {'MRR':>8} {'matched':>9} {'unmatched':>10} "
               f"{'mean d':>9} {'max d':>8} {'high':>6} {'bord':>6} {'sev':>5}")
    out.append("  " + "-" * 74)
    for r in rows:
        mean = f"{r['mean_matching_distance_m']:.1f}" if r["mean_matching_distance_m"] else "-"
        mx = f"{r['max_matching_distance_m']:.0f}" if r["max_matching_distance_m"] else "-"
        out.append(f"  {r['strategy']:4} {r['mrr'] * 100:7.1f}% {r['matched']:9} "
                   f"{r['unmatched']:10} {mean:>9} {mx:>8} "
                   f"{r['high']:6} {r['borderline']:6} {r['severed']:5}")
    out.append("")

    # The stops where the strategies disagree are the interesting ones.
    m1, m2, m3 = (match_index(s) for s in STRATEGIES)
    disagree = [sid for sid in m1 if not (m1[sid].matched == m2[sid].matched == m3[sid].matched)]
    out.append(f"  Strategies disagree on {len(disagree)} of {len(m1)} stops.")
    if disagree:
        out.append("")
        out.append(f"  {'stop_id':<10} {'name':<34} {'M1':>5} {'M2':>5} {'M3':>5}  why")
        out.append("  " + "-" * 74)
        for sid in disagree[:12]:
            name = (m1[sid].stop_name or "")[:33]
            mark = lambda m: "ok" if m.matched else "None"  # noqa: E731
            why = (m3[sid].reason if not m3[sid].matched else m2[sid].reason)[:100]
            out.append(f"  {sid:<10} {name:<34} {mark(m1[sid]):>5} "
                       f"{mark(m2[sid]):>5} {mark(m3[sid]):>5}")
            out.append(f"  {'':<10} -> {why}")
    out.append("=" * 78)
    return "\n".join(out)


if __name__ == "__main__":
    print(_table())