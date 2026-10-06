"""
agents/network.py - your Network & Routing agent.

    python agents/network.py     # serves on :8000

The server wiring is done. Fill in the tools.

Note on the data: the spec suggests OpenStreetMap via the Overpass API or OSMnx.
Add your dataset to data.py, cached - a tool call must return within 45
seconds, and Overpass is slow and rate-limited.

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
from smac import check_identity, guard, in_seq, out_of_scope, respond

# Change {slot} to your approved capability slot.
AGENT_NAME = "smac-network-changeme"
VERSION = "0.1.0"

check_identity(AGENT_NAME, VERSION)
mcp = MCPServer(name=AGENT_NAME, version=VERSION)

# health and geocode_place come from common.py. geocode_place is optional
# and counts towards your five tools - drop it if your tools take no lat/lon.
# Add your dataset's licence to data_sources once you have one.
common.register(mcp, agent_name=AGENT_NAME, version=VERSION,
                data_sources=[])


# YOUR TOOLS: one to five, verb-first snake_case.
#
# The docstring and parameter descriptions are the only things the Orchestrator
# sees when deciding whether to call you, and their quality is graded.
#
# Compute your numbers in code. When you cannot answer, say so in a structured
# response rather than inventing one - how you express that is your design.
# Every response needs sources.

@mcp.tool()
@guard
def estimate_route_distance(
    origin_lat: Annotated[float, Field(description="WGS84 latitude of the start, in South East Queensland.")],
    origin_lon: Annotated[float, Field(description="WGS84 longitude of the start, in South East Queensland.")],
    destination_lat: Annotated[float, Field(description="WGS84 latitude of the destination, in South East Queensland.")],
    destination_lon: Annotated[float, Field(description="WGS84 longitude of the destination, in South East Queensland.")],
) -> dict:
    """TODO: describe what this returns, what it covers, and what it does not."""
    if not (in_seq(origin_lat, origin_lon) and in_seq(destination_lat, destination_lon)):
        return out_of_scope(
            "This agent covers South East Queensland; one of those points is outside it.",
            sources=[data.OSM_LICENCE],
        )

    # TODO: your logic here, e.g. a road-network distance from OpenStreetMap.
    return out_of_scope(
        "estimate_route_distance is not implemented yet.",
        sources=[data.OSM_LICENCE],
    )


# TODO: add your remaining tools here, up to five including geocode_place.


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0",
            port=int(os.environ.get("PORT", "8000")))
