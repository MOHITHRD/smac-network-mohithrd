## Tool 1 - `find_nearest_accessible_stops`

### v1 - initial draft
_Recorded 8 October 2026 from the docstring served at the Week 7 snapshot (unchanged since)._

> Find the public transport stops nearest a point, with the walking distance to each and how reliably each stop connects to the footpath network.
>
> Answers "which stop can I actually walk to from here" rather than "which stop
> is closest as the crow flies". Walking distances are computed over the
> OpenStreetMap pedestrian network, so a stop across an uncrossable road
> reports the real detour, not the straight line.
>
> Every stop carries a match_confidence object reporting how its coordinate was
> joined to the footpath network and whether that join is trustworthy. Some
> stops return no reliable access point at all: where the surrounding
> pedestrian network is severed by an untagged or absent crossing, which side
> of the barrier the stop sits on cannot be determined from its coordinate, and
> the stop is reported as unmatched rather than given a confident-looking
> nearest node.
>
> Coverage is one pinned South East Queensland study area only - see the
> study_area field. Points outside it are declined. Data is a fixed dated
> extract of OpenStreetMap and TransLink GTFS, NOT live: no timetables, no
> real-time departures, no service alerts, no fares, and no vehicle positions.

### v2 - refined (this is what's served live)
> _Not yet written. See V2_PLAN Phase 7A._

### What changed and why

| # | Change | Evidence that prompted it |
|---|---|---|
| 1 | | |

### Parameter descriptions

| Parameter | v1 | v2 |
|---|---|---|
| `lat` | WGS84 latitude of the starting point, inside the agent's study area. | |
| `lon` | WGS84 longitude of the starting point, inside the agent's study area. | |
| `max_results` | How many stops to return, 1 to 5. | |
| `explain` | Include a short written summary of the access quality. | |

---

## Tool 2 - `find_multimodal_route`

### v1 - initial draft
_Recorded 8 October 2026 from the docstring served at the Week 7 snapshot (unchanged since)._

> Plan a walk-and-transit journey between two points, reporting the boarding and alighting stops, the walking legs over the real footpath network, and how reliably each stop connects to it.
>
> Composes the pedestrian half of a multi-modal trip: walk from the origin to a
> boarding stop, and from an alighting stop to the destination, with both walks
> routed over the OpenStreetMap pedestrian network rather than measured in a
> straight line. Returns the GTFS stop IDs for the transit leg so a timetable
> agent can complete it.
>
> Each stop carries a match_confidence object. Where the pedestrian network
> around a stop is severed by an untagged or absent crossing, no reliable
> access point exists, and the route is refused rather than returned with an
> access point that may be on the wrong side of the road.
>
> Coverage is one pinned South East Queensland study area only. Does NOT
> provide the transit leg itself: no departure times, journey durations,
> interchanges, route numbers, fares or real-time information - those come
> from schedule data this agent does not carry. Also does not plan driving,
> cycling or wheelchair-specific routes.

### v2 - refined (this is what's served live)
> _Not yet written. See V2_PLAN Phase 7A._

### What changed and why

| # | Change | Evidence that prompted it |
|---|---|---|
| 1 | | |

### Parameter descriptions

| Parameter | v1 | v2 |
|---|---|---|
| `origin_lat` | WGS84 latitude of the trip origin, inside the agent's study area. | |
| `origin_lon` | WGS84 longitude of the trip origin, inside the agent's study area. | |
| `destination_lat` | WGS84 latitude of the trip destination, inside the agent's study area. | |
| `destination_lon` | WGS84 longitude of the trip destination, inside the agent's study area. | |
| `explain` | Include a short written summary of the route and its reliability. | |

---

## Tool 3 - `geocode_place` (starter-kit tool, registered via `common.register`)

Its description lives in `common.py`, which is kit code and is not edited, so v1 = v2 by design. It counts towards the five-tool cap. Changes to how it is used are made in the descriptions of Tools 1 and 2.

