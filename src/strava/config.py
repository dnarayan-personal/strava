"""Shared paths and constants for the Strava data ingestion scripts."""

from pathlib import Path

# Project root is three levels up from this file: src/strava/config.py -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
ACTIVITIES_DIR = RAW_DIR / "activities"  # original GPX/TCX/FIT files, by activity id
ACTIVITY_META_DIR = RAW_DIR / "activity_meta"  # one JSON per activity (its activities.csv row)
STATE_FILE = DATA_DIR / "state.json"
INDEX_FILE = DATA_DIR / "activities_index.csv"

# Column names used by Strava's bulk export activities.csv to identify each
# activity and its associated original file, as of 2026. Strava has changed
# these in the past, so ingestion falls back to case-insensitive matching.
CSV_ID_COLUMN = "Activity ID"
CSV_FILENAME_COLUMN = "Filename"


def ensure_dirs() -> None:
    """Create local storage directories if they don't already exist."""
    ACTIVITIES_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVITY_META_DIR.mkdir(parents=True, exist_ok=True)
