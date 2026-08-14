"""
agents/public_transport.py - your Public Transport agent.

    python agents/public_transport.py     # serves on :8001

The server wiring is done. Fill in the tools.

Note on the data: stop_times.txt in the GTFS archive is 164 MB uncompressed.
Reading it inside a tool call will exceed the 45-second budget.

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
AGENT_NAME = "smac-pt-changeme"
VERSION = "0.1.0"

check_identity(AGENT_NAME, VERSION)
mcp = MCPServer(name=AGENT_NAME, version=VERSION)

# health and geocode_place come from common.py. geocode_place is optional
# and counts towards your five tools - drop it if your tools take no lat/lon.
common.register(mcp, agent_name=AGENT_NAME, version=VERSION,
                data_sources=[data.GTFS_LICENCE])


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
def find_nearest_stops(
    lat: Annotated[float, Field(description="WGS84 latitude of the search point, in South East Queensland.")],
    lon: Annotated[float, Field(description="WGS84 longitude of the search point, in South East Queensland.")],
    max_results: Annotated[int, Field(description="How many of the closest stops to return, 1 to 10.")] = 5,
) -> dict:
    """TODO: describe what this returns, what it covers, and what it does not."""
    if not in_seq(lat, lon):
        return out_of_scope(
            f"This agent covers South East Queensland; {lat}, {lon} is outside it.",
            sources=[data.GTFS_LICENCE],
        )

    # TODO: your logic here. data.gtfs_table("stops.txt") returns the 13,098 SEQ
    # stops; haversine_m() in smac.py measures distance.
    return out_of_scope(
        "find_nearest_stops is not implemented yet.",
        sources=[data.GTFS_LICENCE],
    )


# TODO: add your remaining tools here, up to five including geocode_place.


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0",
            port=int(os.environ.get("PORT", "8001")))
