"""Parse GPX track files into simple (lat, lon) point lists.

Strava's exported GPX files are simple: a single <trk> with one <trkseg>
containing <trkpt lat=.. lon=..> elements. This avoids pulling in a full GPX
parsing library for what is, for our purposes, a very small subset of the
format.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

_GPX_NS = "{http://www.topografix.com/GPX/1/1}"


def read_track_points(gpx_path: Path) -> list[tuple[float, float]]:
    """Return the list of (lat, lon) points in a GPX file's first track.

    Returns an empty list if the file has no track points (e.g. a strength
    activity with a GPX file that has no GPS data), rather than raising.
    """
    tree = ET.parse(gpx_path)
    root = tree.getroot()

    points: list[tuple[float, float]] = []
    for trkpt in root.iter(f"{_GPX_NS}trkpt"):
        lat = trkpt.get("lat")
        lon = trkpt.get("lon")
        if lat is not None and lon is not None:
            points.append((float(lat), float(lon)))
    return points
