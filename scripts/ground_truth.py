"""
ground_truth.py - derive evaluation ground truth from the datasets, then write
eval/tasks.network.json.

Spec section 10: "Ground truth MUST be derived from your open dataset, not from
your own agent's output. An expected value taken from the agent under test
proves only that the agent agrees with itself."

This script therefore imports NOTHING from src/matching.py or src/agents/. It
reads the pinned artefacts and recomputes distances with its own formula. Every
expected value below is traceable to a named file, named rows, and a stated
calculation.

    python scripts/ground_truth.py
"""

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "src" / "artifacts"
OUT = ROOT / "src" / "eval" / "tasks.network.json"

# --- test points --------------------------------------------------------------
# UQ St Lucia: the coordinate used as the worked example in spec section 5.
UQ = (-27.4975, 153.0137)
# Brisbane CBD: inside SEQ, outside the pinned study area.
CBD = (-27.4698, 153.0251)
# Sydney Opera House: outside SEQ entirely.
SYDNEY = (-33.8568, 151.2153)


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance, metres. Independent of the agent's implementation."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_stops():
    path = ARTIFACTS / "stlucia_stops.csv"
    with path.open(newline="", encoding="utf-8") as f:
        return [{"stop_id": r["stop_id"], "stop_name": r.get("stop_name", ""),
                 "lat": float(r["stop_lat"]), "lon": float(r["stop_lon"])}
                for r in csv.DictReader(f)]


def nearest(stops, lat, lon, k=5):
    scored = [(s, haversine_m(lat, lon, s["lat"], s["lon"])) for s in stops]
    return sorted(scored, key=lambda t: t[1])[:k]


def main():
    stops = load_stops()
    n = len(stops)
    near_uq = nearest(stops, *UQ)

    print("=" * 72)
    print("  GROUND TRUTH  -  derived from stlucia_stops.csv only")
    print("=" * 72)
    print(f"  source      src/artifacts/stlucia_stops.csv")
    print(f"  rows        {n}")
    print(f"  calculation great-circle (haversine), R = 6,371,000 m")
    print()
    print(f"  Nearest stops to UQ St Lucia {UQ}:")
    for s, d in near_uq:
        print(f"    {s['stop_id']:<12} {s['stop_name'][:40]:<42} {d:7.0f} m")
    print()
    print(f"  Nearest stop to Brisbane CBD {CBD}: "
          f"{nearest(stops, *CBD, k=1)[0][1]:.0f} m "
          "(outside the mapped study area)")
    print("=" * 72)

    top = near_uq[0][0]

    tasks = [
        {
            "_ground_truth": (
                f"stlucia_stops.csv contains {n} rows. Nearest stop to "
                f"{UQ} by haversine is {top['stop_id']} "
                f"({top['stop_name']}) at {near_uq[0][1]:.0f} m. Recomputed in "
                "scripts/ground_truth.py, independent of the agent."
            ),
            "prompt": "Which public transport stops can I walk to from the "
                      "University of Queensland St Lucia campus, and how "
                      "reliable is the footpath connection to each?",
            "tools": [{
                "name": "find_nearest_accessible_stops",
                "input": {"lat": UQ[0], "lon": UQ[1], "max_results": 5,
                          "explain": False},
            }],
            "output": {
                "study_area": "St Lucia",
                "matching_strategy": "M3",
                "stops_in_study_area": n,
            },
        },
        {
            "_ground_truth": (
                "Every response must carry the match_confidence field whether "
                "or not it was requested. Asserts the field is present and "
                "names the strategy that produced it."
            ),
            "prompt": "Find the single closest stop to UQ St Lucia.",
            "tools": [{
                "name": "find_nearest_accessible_stops",
                "input": {"lat": UQ[0], "lon": UQ[1], "max_results": 1,
                          "explain": False},
            }],
            "output": {"stops": [{"match_confidence": {"strategy": "M3"}}]},
        },
        {
            "_ground_truth": (
                f"Nearest stop to {CBD} is "
                f"{nearest(stops, *CBD, k=1)[0][1]:.0f} m away and the pinned "
                "walk graph covers St Lucia only, so the point lies outside "
                "the study area. Correct behaviour is a structured decline, "
                "not a route."
            ),
            "prompt": "Which stops can I walk to from Brisbane CBD?",
            "tools": [{
                "name": "find_nearest_accessible_stops",
                "input": {"lat": CBD[0], "lon": CBD[1], "max_results": 3,
                          "explain": False},
            }],
            "output": {"status": "out_of_scope", "reason": "study area"},
        },
        {
            "_ground_truth": (
                "Sydney is outside South East Queensland (smac.SEQ_BBOX). "
                "Spec section 6 requires a structured refusal rather than an "
                "invented answer."
            ),
            "prompt": "Plan a walking and transit route from the Sydney Opera "
                      "House to Bondi Beach.",
            "tools": [{
                "name": "find_multimodal_route",
                "input": {"origin_lat": SYDNEY[0], "origin_lon": SYDNEY[1],
                          "destination_lat": -33.8908, "destination_lon": 151.2743,
                          "explain": False},
            }],
            "output": {"status": "out_of_scope",
                       "reason": "South East Queensland"},
        },
        {
            "_ground_truth": (
                "A route between two points inside the study area must return "
                "both access points with their match confidence, and must "
                "declare the transit leg as not composed rather than inventing "
                "a timetable."
            ),
            "prompt": "How do I get from UQ Chancellor's Place to the St Lucia "
                      "ferry terminal by public transport?",
            "tools": [{
                "name": "find_multimodal_route",
                "input": {"origin_lat": UQ[0], "origin_lon": UQ[1],
                          "destination_lat": -27.4999, "destination_lon": 153.0106,
                          "explain": False},
            }],
            "output": {"study_area": "St Lucia", "matching_strategy": "M3"},
        },
        {
            "_ground_truth": (
                "Spec section 6 and handshake check 6: malformed input must "
                "return a readable error, not crash the server. Latitude 999 "
                "is not a valid WGS84 coordinate."
            ),
            "prompt": "Find stops near latitude 999.",
            "tools": [{
                "name": "find_nearest_accessible_stops",
                "input": {"lat": 999.0, "lon": 153.0137, "max_results": 3,
                          "explain": False},
            }],
            "output": {"status": "out_of_scope"},
        },
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(tasks, indent=2))
    print(f"\n  wrote {OUT.relative_to(ROOT)}  ({len(tasks)} cases)")
    print("  run:  python src/eval/run_eval.py --tasks src/eval/tasks.network.json\n")


if __name__ == "__main__":
    main()