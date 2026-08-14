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
        "id": "charging",
        "name": "EV Charging",
        "blurb": "Queensland Electric Super Highway stations, from the Department of Transport and Main Roads.",
    },
    {
        "id": "public_transport",
        "name": "Public Transport",
        "blurb": "13,098 stops and 926 routes from the Translink South East Queensland GTFS feed.",
    },
    {
        "id": "policy",
        "name": "Policy & Patronage",
        "blurb": "Monthly passenger trips by mode, spanning the August 2024 50 cent fare change.",
    },
]

QUERIES = [
    {
        "id": "chg-nearest-named-place",
        "domain": "charging",
        "text": "Where is the nearest EV charger to Toowong Village in Brisbane?",
        "why": "No coordinates in the question. The agent has to look the place up before it can measure anything, so this takes two tool calls.",
        "plan": [
            {"agent": "charging", "tool": "geocode_place",
             "arguments": {"place": "Toowong Village, Brisbane"}},
            {"agent": "charging", "tool": "find_nearest_charger",
             "arguments": {"lat": "$0.lat", "lon": "$0.lon", "max_results": 3}},
        ],
    },
    {
        "id": "chg-energy",
        "domain": "charging",
        "text": "How much energy does a 92 km trip need in a car that uses 18 kWh per 100 km, and what will it cost?",
        "why": "The energy is arithmetic, so the agent computes it exactly. The cost is not in the dataset, and the agent says so rather than guessing a tariff.",
        "plan": [
            {"agent": "charging", "tool": "estimate_energy_required",
             "arguments": {"distance_m": 92000, "consumption_kwh_per_100km": 18.0}},
        ],
    },
    {
        "id": "chg-feasibility",
        "domain": "charging",
        "text": "I am at UQ St Lucia with 250 km of range left. Can I reach a charger?",
        "why": "A different question about the same place. Rather than the closest station, this reports how much of the network is inside the stated range, and it is explicit that the measurement is straight-line.",
        "plan": [
            {"agent": "charging", "tool": "assess_trip_feasibility",
             "arguments": {"lat": -27.4975, "lon": 153.0137, "range_km": 250}},
        ],
    },
    {
        "id": "chg-out-of-scope",
        "domain": "charging",
        "text": "Where is the nearest charger to the Sydney Opera House?",
        "why": "Outside Queensland. A refusal that still cites its source is the correct answer here, and it is what the specification requires.",
        "plan": [
            {"agent": "charging", "tool": "find_nearest_charger",
             "arguments": {"lat": -33.8568, "lon": 151.2153, "max_results": 3}},
        ],
    },
    {
        "id": "pt-cross-agent",
        "domain": "public_transport",
        "text": "I am driving an EV to the Queensland Museum. Where can I charge near there, and what public transport serves it?",
        "why": "One question, two domains. Charging stations and transport stops sit in different agents, on different datasets, under different licences. Neither agent can answer this alone, so both get called and the answer cites both sources.",
        "plan": [
            {"agent": "public_transport", "tool": "geocode_place",
             "arguments": {"place": "Queensland Museum, South Brisbane"}},
            {"agent": "charging", "tool": "find_nearest_charger",
             "arguments": {"lat": "$0.lat", "lon": "$0.lon", "max_results": 2}},
            {"agent": "public_transport", "tool": "find_nearest_stops",
             "arguments": {"lat": "$0.lat", "lon": "$0.lon", "max_results": 3}},
        ],
    },
    {
        "id": "pt-route",
        "domain": "public_transport",
        "text": "Which bus routes serve Doomben?",
        "why": "A straight lookup against the live GTFS feed, returning the real Translink route_id the conventions require.",
        "plan": [
            {"agent": "public_transport", "tool": "find_route",
             "arguments": {"query": "Doomben", "max_results": 5}},
        ],
    },
    {
        "id": "pt-data-gap",
        "domain": "public_transport",
        "text": "What time is the next bus from UQ Chancellor's Place?",
        "why": "The timetable file is 164 MB and this agent does not load it. Departure times are declared as a known gap, so a good model will say it cannot answer, sometimes without calling anything at all.",
        "plan": [
            {"agent": "public_transport", "tool": "find_nearest_stops",
             "arguments": {"lat": -27.4975, "lon": 153.0137, "max_results": 3}},
        ],
    },
    {
        "id": "pol-fare-change",
        "domain": "policy",
        "text": "Did the 50 cent flat fare change public transport patronage?",
        "why": "The numbers are real and the jump is large. Watch the answer refuse to call it causation: there is no control group, so the agent reports the change and names what it could not control for.",
        "plan": [
            {"agent": "policy", "tool": "assess_policy_impact",
             "arguments": {"policy_month": "2024-08", "window_months": 12}},
        ],
    },
    {
        "id": "pol-series",
        "domain": "policy",
        "text": "Show me ferry patronage for the first half of 2025.",
        "why": "A plain series query. The month and mode filters come straight from the question.",
        "plan": [
            {"agent": "policy", "tool": "get_patronage",
             "arguments": {"mode": "Ferry", "from_month": "2025-01", "to_month": "2025-06"}},
        ],
    },
    {
        "id": "pol-out-of-scope",
        "domain": "policy",
        "text": "How many helicopter trips were taken last year?",
        "why": "Not a mode in this series. The agent refuses and lists the modes it does hold, which is more useful than an apology.",
        "plan": [
            {"agent": "policy", "tool": "get_patronage",
             "arguments": {"mode": "Helicopter", "from_month": "", "to_month": ""}},
        ],
    },
]


def by_id(query_id: str) -> dict | None:
    return next((q for q in QUERIES if q["id"] == query_id), None)
