#!/usr/bin/env python3
"""
build_graph.py - offline study-area builder for smac-network-mohithrd

Run ONCE, on your own machine, outside Docker. Produces three pinned artefacts:

    src/artifacts/stlucia_walk.graphml   pedestrian-walkable network G_w
    src/artifacts/stlucia_stops.csv      GTFS stops inside the suburb boundary
    src/artifacts/manifest.json          provenance: dates, counts, versions

The agent NEVER runs this. It loads the artefacts. That keeps every tool call
well inside the 45 s budget (MCP spec s6) and makes the matching statistics
reproducible - OpenStreetMap changes daily, so an unpinned graph means MRR and
mean-matching-distance figures that move under you and cannot be re-derived
(MCP spec s10: ground truth must be traceable).

Usage:
    pip install osmnx pandas shapely requests
    python scripts/build_graph.py
    python scripts/build_graph.py --place "Toowong, Queensland, Australia"
    python scripts/build_graph.py --gtfs /path/to/SEQ_GTFS.zip
"""

import argparse
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# --- defaults -----------------------------------------------------------------

PLACE = "St Lucia, Queensland, Australia"
NETWORK_TYPE = "walk"
SLUG = "stlucia"

# TransLink SEQ static GTFS. Verify this against docs/datasets.md in the kit -
# if data.py already fetches the feed, point --gtfs at the cached copy instead
# so your agent and this script are provably using the same snapshot.
GTFS_URL = "https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip"

OUT_DIR = Path(__file__).resolve().parent.parent / "src" / "artifacts"

OSM_LICENCE = "OpenStreetMap contributors, ODbL 1.0"
GTFS_LICENCE = "TransLink SEQ GTFS, CC BY 4.0"


# --- helpers ------------------------------------------------------------------

def log(msg):
    print(f"  {msg}", flush=True)


def section(msg):
    print(f"\n[{msg}]", flush=True)


def fetch_gtfs_bytes(gtfs_arg):
    """Return the raw bytes of the GTFS zip, from disk or from the network."""
    if gtfs_arg:
        p = Path(gtfs_arg)
        if not p.exists():
            sys.exit(f"ERROR: --gtfs path does not exist: {p}")
        log(f"reading local GTFS: {p}")
        return p.read_bytes(), f"local file {p.name}"

    import requests
    log(f"downloading GTFS: {GTFS_URL}")
    r = requests.get(GTFS_URL, timeout=180)
    r.raise_for_status()
    log(f"downloaded {len(r.content) / 1e6:.1f} MB")
    return r.content, GTFS_URL


# --- main ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--place", default=PLACE, help="OSM place name for the study area")
    ap.add_argument("--slug", default=SLUG, help="filename prefix for artefacts")
    ap.add_argument("--gtfs", default=None, help="path to a local SEQ_GTFS.zip")
    ap.add_argument("--out", default=str(OUT_DIR), help="output directory")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    import osmnx as ox
    import pandas as pd
    from shapely.geometry import Point

    # OSMnx 1.x and 2.x differ; ox.settings exists in both recent lines.
    try:
        ox.settings.use_cache = True
        ox.settings.log_console = False
    except AttributeError:
        pass

    started = datetime.now(timezone.utc)
    print(f"\nStudy area: {args.place}")
    print(f"OSMnx {ox.__version__} | started {started.isoformat()}")

    # -- 1. boundary polygon ---------------------------------------------------
    section("1/5 boundary")
    boundary_gdf = ox.geocode_to_gdf(args.place)
    polygon = boundary_gdf.loc[0, "geometry"]
    minx, miny, maxx, maxy = polygon.bounds
    log(f"bbox lon {minx:.5f}..{maxx:.5f}  lat {miny:.5f}..{maxy:.5f}")
    log(f"area {boundary_gdf.to_crs(3577).area.iloc[0] / 1e6:.2f} km2")

    # -- 2. walk network -------------------------------------------------------
    section("2/5 walk network (Overpass - this is the slow step)")
    G = ox.graph_from_polygon(polygon, network_type=NETWORK_TYPE, simplify=True)
    n_nodes, n_edges = G.number_of_nodes(), G.number_of_edges()
    log(f"nodes {n_nodes}  edges {n_edges}")

    # Connectivity matters: a fragmented graph produces routing failures that
    # look exactly like legitimate M3 rejections, which would corrupt results.
    try:
        import networkx as nx
        UG = G.to_undirected()
        comps = sorted(nx.connected_components(UG), key=len, reverse=True)
        largest = len(comps[0])
        log(f"connected components {len(comps)}; "
            f"largest holds {largest}/{n_nodes} nodes ({100 * largest / n_nodes:.1f}%)")
        if len(comps) > 1:
            log("NOTE: graph is fragmented. Islands are a real OSM tagging "
                "artefact and are part of what M3 is meant to expose - "
                "record this, do not silently repair it.")
    except Exception as e:  # noqa: BLE001
        log(f"connectivity check skipped: {e}")

    graphml_path = out_dir / f"{args.slug}_walk.graphml"
    ox.save_graphml(G, graphml_path)
    log(f"saved {graphml_path.name} ({graphml_path.stat().st_size / 1e6:.1f} MB)")

    # -- 3. GTFS stops ---------------------------------------------------------
    section("3/5 GTFS stops")
    gtfs_bytes, gtfs_origin = fetch_gtfs_bytes(args.gtfs)
    with zipfile.ZipFile(io.BytesIO(gtfs_bytes)) as z:
        with z.open("stops.txt") as f:
            stops = pd.read_csv(f, dtype={"stop_id": str, "stop_code": str})
    log(f"feed contains {len(stops)} stops")

    # -- 4. filter to boundary -------------------------------------------------
    section("4/5 filter to study area")
    stops = stops.dropna(subset=["stop_lat", "stop_lon"])

    # cheap bbox prefilter, then exact point-in-polygon
    box = stops[
        (stops.stop_lon >= minx) & (stops.stop_lon <= maxx)
        & (stops.stop_lat >= miny) & (stops.stop_lat <= maxy)
    ].copy()
    log(f"{len(box)} stops in bbox")

    inside = box[box.apply(
        lambda r: polygon.contains(Point(r.stop_lon, r.stop_lat)), axis=1
    )].copy()

    keep = [c for c in
            ["stop_id", "stop_code", "stop_name", "stop_lat", "stop_lon",
             "location_type", "parent_station", "wheelchair_boarding"]
            if c in inside.columns]
    inside = inside[keep].sort_values("stop_id")

    stops_path = out_dir / f"{args.slug}_stops.csv"
    inside.to_csv(stops_path, index=False)
    log(f"{len(inside)} stops inside the boundary -> {stops_path.name}")

    # -- 5. manifest -----------------------------------------------------------
    section("5/5 manifest")
    manifest = {
        "study_area": args.place,
        "slug": args.slug,
        "built_utc": started.isoformat(),
        "osm": {
            "source": "OpenStreetMap via Overpass API (OSMnx)",
            "licence": OSM_LICENCE,
            "network_type": NETWORK_TYPE,
            "simplified": True,
            "osmnx_version": ox.__version__,
            "nodes": n_nodes,
            "edges": n_edges,
            "file": graphml_path.name,
        },
        "gtfs": {
            "source": "TransLink SEQ static GTFS",
            "licence": GTFS_LICENCE,
            "origin": gtfs_origin,
            "stops_in_feed": int(len(stops)),
            "stops_in_study_area": int(len(inside)),
            "file": stops_path.name,
        },
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    log(f"wrote {manifest_path.name}")

    # -- summary ---------------------------------------------------------------
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    print(f"""
================================================================
  STUDY AREA BUILT   ({elapsed:.0f}s)

  {args.place}
  walk network     {n_nodes} nodes, {n_edges} edges
  GTFS stops       {len(inside)} inside boundary (of {len(stops)} in feed)
  extract date     {started.date().isoformat()}

  Quote these figures in section 3.2.1 with the extract date.
  Commit src/artifacts/ - the agent loads these, never Overpass.
================================================================
""")


if __name__ == "__main__":
    main()