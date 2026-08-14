"""
agents/charging.py - your EV Charging Infrastructure agent.

    python agents/charging.py     # serves on :8000

The server wiring is done, and find_nearest_charger is written out as a
worked example. Read it, then build tools of your own.

Import note: use `from mcp.server import MCPServer`. Most tutorials show
`FastMCP`, which is not in the SDK version this course requires.
"""
import os
import sys
from pathlib import Path
from typing import Annotated

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server import MCPServer
from pydantic import Field

import common
import data
import llm                                 # llm.ask() writes prose about your results
from smac import check_identity, guard, haversine_m, in_seq, out_of_scope, respond

# Change {slot} to your approved capability slot.
AGENT_NAME = "smac-charging-changeme"
VERSION = "0.1.0"

check_identity(AGENT_NAME, VERSION)
mcp = MCPServer(name=AGENT_NAME, version=VERSION)

# health and geocode_place come from common.py. geocode_place is optional
# and counts towards your five tools - drop it if your tools take no lat/lon.
common.register(mcp, agent_name=AGENT_NAME, version=VERSION,
                data_sources=[data.QLD_LICENCE])


# YOUR TOOLS: one to five, verb-first snake_case.
#
# The docstring and parameter descriptions are the only things the Orchestrator
# sees when deciding whether to call you, and their quality is graded.
#
# Compute your numbers in code. When you cannot answer, say so in a structured
# response rather than inventing one - how you express that is your design.
# Every response needs sources.
#
# The tool below is written out as a worked example. Read it, then replace it
# with tools of your own - an agent that only serves this one is a copy of the
# starter kit.

@mcp.tool()
@guard
def find_nearest_charger(
    lat: Annotated[float, Field(description="WGS84 latitude of the trip origin, in South East Queensland.")],
    lon: Annotated[float, Field(description="WGS84 longitude of the trip origin, in South East Queensland.")],
    max_results: Annotated[int, Field(description="How many of the closest stations to return, 1 to 5.")] = 3,
    explain: Annotated[bool, Field(description="Include short written range-planning advice.")] = True,
) -> dict:
    """Find the closest Queensland Electric Super Highway charging stations to a point.

    Answers range-planning questions for electric vehicle trips starting in South
    East Queensland - where the next public charging site is, how far away, and
    which sites lie onward along the highway network. Uses the Queensland
    Government's published station list, so it covers intercity corridors rather
    than every kerbside charger in a suburb.

    Origin must be in South East Queensland; returned stations may be anywhere in
    Queensland, since onward stations matter on long trips. Plug and connector
    types are NOT available - the source publishes that column empty. Does not
    report live availability or pricing, and does not plan a route.
    """
    # Outside the coverage this agent claims, so it declines rather than
    # answering from data that does not apply.
    if not in_seq(lat, lon):
        return out_of_scope(
            f"This agent covers trips starting in South East Queensland; {lat}, {lon} is outside it.",
            sources=[data.QLD_LICENCE],
        )

    # Every number here is arithmetic on the dataset. Nothing is asked of a model.
    stations = data.charging_stations()
    max_results = max(1, min(int(max_results), 5))
    nearest = sorted(
        ({**s, "distance_m": haversine_m(lat, lon, s["lat"], s["lon"])} for s in stations),
        key=lambda s: s["distance_m"],
    )[:max_results]

    payload = {
        "origin": {"lat": lat, "lon": lon},
        "nearest": nearest,
        "stations_in_dataset": len(stations),
        # What this dataset cannot tell you. The plug column exists but is empty
        # on every row, so reporting it would look like real detail.
        "data_gaps": ["plug_and_connector_types", "live_availability", "pricing"],
    }

    # The model only writes prose about numbers already computed above, and is
    # told plainly which fields do not exist so it cannot fill them in.
    if explain and nearest:
        closest = nearest[0]
        payload["advice"] = llm.ask(
            system=(
                "You advise electric vehicle drivers on range planning in Queensland. "
                "Use only the facts you are given. Never invent plug types, prices or "
                "availability; if something is missing, say it is not published. "
                "At most three sentences."
            ),
            user=(
                f"Closest station: {closest['name']}, {closest['distance_m'] / 1000:.1f} km away, "
                f"at {closest['address']}. Host: {closest['host']}. Status: {closest['status']}. "
                f"Onward from there: {closest['onward_stations'] or 'not published'}. "
                "Plug types, live availability and pricing are not published."
            ),
        )

    return respond(payload, sources=[data.QLD_LICENCE])


# TODO: add your remaining tools here, up to five including geocode_place.


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0",
            port=int(os.environ.get("PORT", "8000")))
