"""
common.py - tools every agent gets, so nobody writes them twice.

    import common
    common.register(mcp, agent_name=AGENT_NAME, version=VERSION,
                    data_sources=[data.GTFS_LICENCE])

Two tools live here.

`health` is mandatory and its shape is fixed across the cohort, so there
is nothing to gain from fifty-five separate copies drifting apart. Only the
identity and the source list differ, and those are arguments.

`geocode_place` is here because almost every spatial tool needs a coordinate,
people ask questions using place names, and a model that guesses a coordinate
produces a number with no source that cannot be cited. Asked to locate UQ
St Lucia, one returned a point 261 m from OpenStreetMap's. Any agent whose
tools take a lat/lon should register it.

Registering it is opt-in. A tool nobody in your domain needs still costs you: it
sits in the Orchestrator's menu and attracts calls that should have gone
elsewhere. The policy agent turns it off because its data has no geography.

These count towards the limit of five domain tools, same as anything else.
`health` does not.
"""

from __future__ import annotations

from typing import Annotated, Iterable

from pydantic import Field

import data
import llm
from smac import guard, in_seq, out_of_scope, respond


def register(
    mcp,
    *,
    agent_name: str,
    version: str,
    data_sources: Iterable[str],
    geocode: bool = True,
) -> None:
    """Attach the shared tools to an agent.

    `data_sources` is what this agent's `health` reports. Pass every licence you
    actually read from; if `geocode` is on, the OpenStreetMap licence is added
    for you, because the moment that tool can answer, you are using OSM data.
    """
    # Every agent runs on the Claude API, so none starts without a working key.
    try:
        llm.check()
    except Exception as exc:  # noqa: BLE001 - one readable line, not a traceback
        raise SystemExit(f"{agent_name} cannot start: {exc}") from None

    sources = list(data_sources)
    if geocode and data.OSM_LICENCE not in sources:
        sources.append(data.OSM_LICENCE)

    @mcp.tool()
    def health() -> dict:
        """Liveness probe. Returns this agent's identity, data sources and model backend."""
        return {
            "status": "ok",
            "agent": agent_name,
            "version": version,
            "data_sources": sources,
            "llm_backend": llm.model_name(),
        }

    if not geocode:
        return

    @mcp.tool()
    @guard
    def geocode_place(
        place: Annotated[
            str,
            Field(description="Place name, landmark, suburb or address to locate, e.g. 'Toowong Village Brisbane'."),
        ],
    ) -> dict:
        """Convert a South East Queensland place name or address into WGS84 coordinates.

        Use this before any tool that needs a lat/lon when you were given a place name
        instead of numbers. Do not guess coordinates - a recalled coordinate has no
        source and cannot be cited. Returns the matched address and the OpenStreetMap
        feature type, so you can judge how precise the match is.

        Covers South East Queensland; a place resolving outside SEQ is reported as out
        of scope. Returns the single best match and does not disambiguate between
        places sharing a name.
        """
        hit = data.geocode(place)
        if hit is None:
            # Do NOT echo the unmatched input back. Whatever was passed in is
            # untrusted free text, and your response is read by the Orchestrator's
            # model - echoing it verbatim is an indirect prompt-injection path.
            # Reporting the failure without replaying the payload costs nothing.
            return out_of_scope(
                "OpenStreetMap has no Australian match for the requested place name.",
                sources=[data.OSM_LICENCE],
            )
        if not in_seq(hit["lat"], hit["lon"]):
            # Safe to name the match here: it came from OpenStreetMap, not the caller.
            return out_of_scope(
                f"That place resolves to {hit['matched_name']}, which is outside South East Queensland.",
                sources=[data.OSM_LICENCE],
            )
        return respond({"query": place, **hit}, sources=[data.OSM_LICENCE])
