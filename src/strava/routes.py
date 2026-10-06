"""Group activities (typically rides) into route clusters based on GPS track
overlap, independent of (often inconsistent) activity names.

Approach:
  1. Reduce each activity's track to a "fingerprint": the set of grid cells
     (~25m squares) its GPS points pass through. This makes comparison
     robust to GPS noise and minor route deviations without needing exact
     point-to-point matching.
  2. Build an inverted index (grid cell -> activity ids passing through it)
     so we only ever compare pairs of activities that share at least one
     cell, rather than all O(n^2) pairs -- important once you have hundreds
     of rides.
  3. For each candidate pair, compute an overlap coefficient
     (|A ∩ B| / min(|A|, |B|)) -- this asks "does the shorter of the two
     routes mostly lie within the longer one?", which handles rides that
     are subsets/supersets of each other (e.g. an out-and-back that someone
     also once rode partway).
  4. Union-find (connected components): any two activities whose overlap
     meets the threshold are joined into the same cluster.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

DEFAULT_CELL_SIZE_METERS = 25.0
DEFAULT_OVERLAP_THRESHOLD = 0.5

_METERS_PER_DEGREE_LAT = 111_320.0


def _cell_size_degrees(cell_size_meters: float, latitude: float) -> tuple[float, float]:
    """Return (lat_step, lon_step) in degrees for a roughly-square cell."""
    lat_step = cell_size_meters / _METERS_PER_DEGREE_LAT
    meters_per_degree_lon = _METERS_PER_DEGREE_LAT * max(math.cos(math.radians(latitude)), 1e-6)
    lon_step = cell_size_meters / meters_per_degree_lon
    return lat_step, lon_step


def fingerprint(
    points: list[tuple[float, float]], cell_size_meters: float = DEFAULT_CELL_SIZE_METERS
) -> frozenset[tuple[int, int]]:
    """Reduce a list of (lat, lon) points to a set of grid cell ids."""
    if not points:
        return frozenset()

    # Use the track's average latitude for a consistent longitude scale
    # across the whole route (good enough at city/regional scale).
    avg_lat = sum(p[0] for p in points) / len(points)
    lat_step, lon_step = _cell_size_degrees(cell_size_meters, avg_lat)

    cells = {(int(lat // lat_step), int(lon // lon_step)) for lat, lon in points}
    return frozenset(cells)


def overlap_coefficient(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    return intersection / min(len(a), len(b))


def jaccard_similarity(a: frozenset, b: frozenset) -> float:
    """Intersection-over-union similarity.

    Unlike `overlap_coefficient` (which only asks whether the *shorter*
    route lies mostly within the longer one), Jaccard penalizes routes that
    only share a small common segment (e.g. both leaving from the same
    house) relative to their full length. This matters a lot in practice:
    overlap_coefficient tends to chain together otherwise-unrelated routes
    transitively through such shared segments (single-linkage chaining),
    while Jaccard requires the routes to substantially coincide overall.
    """
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union


class _UnionFind:
    def __init__(self, items: list) -> None:
        self._parent = {item: item for item in items}

    def find(self, item):
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a, b) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


@dataclass
class RouteCluster:
    cluster_id: int
    activity_ids: list[str] = field(default_factory=list)


def cluster_by_route(
    fingerprints: dict[str, frozenset[tuple[int, int]]],
    threshold: float = DEFAULT_OVERLAP_THRESHOLD,
) -> dict[str, int]:
    """Cluster activities by GPS track overlap.

    Args:
        fingerprints: activity id -> fingerprint (from `fingerprint()`).
        threshold: minimum overlap coefficient to join two activities into
            the same cluster.

    Returns:
        Mapping of activity id -> cluster id (0-based, arbitrary order).
        Activities with an empty fingerprint (no GPS data) are omitted.
    """
    activity_ids = [aid for aid, fp in fingerprints.items() if fp]
    uf = _UnionFind(activity_ids)

    # Inverted index: grid cell -> activities passing through it.
    cell_index: dict[tuple[int, int], list[str]] = defaultdict(list)
    for aid in activity_ids:
        for cell in fingerprints[aid]:
            cell_index[cell].append(aid)

    # Only compare pairs that share at least one cell.
    compared: set[tuple[str, str]] = set()
    for aids_sharing_cell in cell_index.values():
        if len(aids_sharing_cell) < 2:
            continue
        for i in range(len(aids_sharing_cell)):
            for j in range(i + 1, len(aids_sharing_cell)):
                a, b = aids_sharing_cell[i], aids_sharing_cell[j]
                pair = (a, b) if a < b else (b, a)
                if pair in compared:
                    continue
                compared.add(pair)
                if uf.find(a) == uf.find(b):
                    continue  # already in the same cluster, skip the math
                if overlap_coefficient(fingerprints[a], fingerprints[b]) >= threshold:
                    uf.union(a, b)

    # Assign compact 0-based cluster ids to the resulting connected components.
    root_to_cluster_id: dict[str, int] = {}
    result: dict[str, int] = {}
    for aid in activity_ids:
        root = uf.find(aid)
        if root not in root_to_cluster_id:
            root_to_cluster_id[root] = len(root_to_cluster_id)
        result[aid] = root_to_cluster_id[root]

    return result
