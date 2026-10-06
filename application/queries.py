"""
The demo query catalogue.

Each query is a question a person might actually ask, paired with a scripted
plan of tool calls that answers it. The plan is a fallback: when a model is
configured the router chooses the tools itself, and the scripted plan is only
used when no API key is set, or when someone ticks "scripted" to guarantee a
demo runs the same way twice.

An argument written as "$0.location.lat" means "take it from step 0's result",
which is how a query gets geocoded before it is answered.

Every domain includes at least one question the agents should refuse. Watching
an agent decline to answer is the most useful thing an observer can see: it is
the difference between a system that knows its coverage and one that invents.
"""

DOMAINS = [
    {
        "id": "network",
        "name": "Network & Routing",
        "blurb": "OpenStreetMap place lookup so far. Your road-network data goes in data.py.",
    },
]

QUERIES = [
    {
        "id": "net-place",
        "domain": "network",
        "text": "Where is Brisbane Airport?",
        "why": "The place lookup works before you write a line: it is shared by every agent.",
        "plan": [
            {"agent": "network", "tool": "geocode_place",
             "arguments": {"place": "Brisbane Airport"}},
        ],
    },
    {
        "id": "net-route",
        "domain": "network",
        "text": "How far is it by road from UQ St Lucia to Brisbane Airport?",
        "why": "This calls the stub, which declines until you build it. Building it is the work.",
        "plan": [
            {"agent": "network", "tool": "estimate_route_distance",
             "arguments": {"origin_lat": -27.4975, "origin_lon": 153.0137,
                           "destination_lat": -27.3842, "destination_lon": 153.1175}},
        ],
    },
    {
        "id": "net-out-of-scope",
        "domain": "network",
        "text": "Which roads are near the Sydney Opera House?",
        "why": "Outside South East Queensland. The place lookup itself declines.",
        "plan": [
            {"agent": "network", "tool": "geocode_place",
             "arguments": {"place": "Sydney Opera House"}},
        ],
    },
]


def by_id(query_id: str) -> dict | None:
    return next((q for q in QUERIES if q["id"] == query_id), None)
