"""Build route clusters for Ride activities from local GPX tracks.

Reads every locally-ingested "Ride" activity's GPX file, computes a
grid-cell fingerprint for clustering (see strava.routes) and a downsampled
point list for fast map rendering, clusters rides by GPS overlap, and writes
everything the viewer app needs to `data/routes.json` so the app doesn't
have to re-parse hundreds of GPX files on every load.

Re-run this whenever you ingest a new export to pick up new rides.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging

from strava import config, gpx_utils
from strava.routes import DEFAULT_CELL_SIZE_METERS, DEFAULT_OVERLAP_THRESHOLD, cluster_by_route, fingerprint

logger = logging.getLogger(__name__)

ROUTES_FILE = config.DATA_DIR / "routes.json"

# Cap points kept per ride for map display; a simple uniform stride keeps
# the overall route shape without sending huge point arrays to the browser.
MAX_DISPLAY_POINTS = 400


def _downsample(points: list[tuple[float, float]], max_points: int) -> list[tuple[float, float]]:
    if len(points) <= max_points:
        return points
    stride = max(1, len(points) // max_points)
    return points[::stride]


def _load_index_rows() -> list[dict]:
    with config.INDEX_FILE.open() as f:
        return list(csv.DictReader(f))


def build(
    activity_type: str = "Ride",
    cell_size_meters: float = DEFAULT_CELL_SIZE_METERS,
    threshold: float = DEFAULT_OVERLAP_THRESHOLD,
) -> dict:
    rows = _load_index_rows()
    candidates = [r for r in rows if r.get("Activity Type") == activity_type]
    logger.info("Found %d %s activities in the index", len(candidates), activity_type)

    fingerprints: dict[str, frozenset] = {}
    display_tracks: dict[str, list[tuple[float, float]]] = {}
    skipped_no_gpx = 0
    skipped_no_points = 0

    for row in candidates:
        activity_id = row["Activity ID"]
        gpx_path = config.ACTIVITIES_DIR / f"{activity_id}.gpx"
        if not gpx_path.exists():
            skipped_no_gpx += 1
            continue

        points = gpx_utils.read_track_points(gpx_path)
        if not points:
            skipped_no_points += 1
            continue

        fingerprints[activity_id] = fingerprint(points, cell_size_meters=cell_size_meters)
        display_tracks[activity_id] = _downsample(points, MAX_DISPLAY_POINTS)

    logger.info(
        "Fingerprinted %d activities (%d had no .gpx file, %d had no track points)",
        len(fingerprints),
        skipped_no_gpx,
        skipped_no_points,
    )

    assignments = cluster_by_route(fingerprints, threshold=threshold)
    num_clusters = len(set(assignments.values()))
    logger.info("Formed %d route clusters from %d activities", num_clusters, len(assignments))

    output = {
        "activity_type": activity_type,
        "cell_size_meters": cell_size_meters,
        "overlap_threshold": threshold,
        "clusters": {
            activity_id: {
                "cluster_id": cluster_id,
                "track": [list(p) for p in display_tracks[activity_id]],
            }
            for activity_id, cluster_id in assignments.items()
        },
    }

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    ROUTES_FILE.write_text(json.dumps(output))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build GPS-based route clusters for Ride activities."
    )
    parser.add_argument(
        "--activity-type",
        default="Ride",
        help="Activity type to cluster (default: Ride).",
    )
    parser.add_argument(
        "--cell-size-meters",
        type=float,
        default=DEFAULT_CELL_SIZE_METERS,
        help=f"Grid cell size in meters for the route fingerprint (default: {DEFAULT_CELL_SIZE_METERS}).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_OVERLAP_THRESHOLD,
        help=f"Minimum overlap coefficient to merge two rides into one cluster (default: {DEFAULT_OVERLAP_THRESHOLD}).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    output = build(
        activity_type=args.activity_type,
        cell_size_meters=args.cell_size_meters,
        threshold=args.threshold,
    )
    num_clusters = len(set(c["cluster_id"] for c in output["clusters"].values()))
    print(
        f"Wrote {len(output['clusters'])} clustered activities into "
        f"{num_clusters} route clusters to {ROUTES_FILE}"
    )


if __name__ == "__main__":
    main()
