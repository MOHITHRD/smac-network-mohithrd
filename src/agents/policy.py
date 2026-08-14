"""
agents/policy.py - your Policy & Patronage agent.

    python agents/policy.py     # serves on :8002

The server wiring is done. Fill in the tools.

Note on the data: the series is monthly totals with no geography, which is why
geocode_place is not registered below. Patronage moved after the 50c fare, but
so did the school term and the weather - report the change, not a cause.

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
from smac import check_identity, guard, out_of_scope, respond

# Change {slot} to your approved capability slot.
AGENT_NAME = "smac-policy-changeme"
VERSION = "0.1.0"

check_identity(AGENT_NAME, VERSION)
mcp = MCPServer(name=AGENT_NAME, version=VERSION)

# health comes from common.py. No geocode_place here: this data has no
# geography, and an unused tool only attracts calls meant for another agent.
common.register(mcp, agent_name=AGENT_NAME, version=VERSION,
                data_sources=[data.PATRONAGE_LICENCE], geocode=False)


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
def get_patronage(
    start_month: Annotated[str, Field(description="First month to report, as YYYY-MM, e.g. '2024-07'.")],
    end_month: Annotated[str, Field(description="Last month to report, as YYYY-MM, e.g. '2025-06'.")],
) -> dict:
    """TODO: describe what this returns, what period it covers, and what it does not."""
    # TODO: your logic here. data.patronage_seq() returns 116 monthly records.
    # Months outside that range have no data.
    return out_of_scope(
        "get_patronage is not implemented yet.",
        sources=[data.PATRONAGE_LICENCE],
    )


# TODO: add your remaining tools here, up to five in total.


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0",
            port=int(os.environ.get("PORT", "8002")))
