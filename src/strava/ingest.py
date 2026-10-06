"""Ingest a Strava bulk-export archive into local storage.

Strava's paid API tier is not available to us, so this project relies on the
free, manual "Download or Delete Your Account" -> "Request Your Archive"
export instead (see docs/data-download-design.md). That export is a ZIP
containing `activities.csv` (one summary row per activity) plus an
`activities/` folder with the original GPX/TCX/FIT file per activity.

This script can be re-run against successive exports (each of which
contains your *entire* history again) and only copies files/metadata that
aren't already stored locally, so it's safe and cheap to re-run whenever you
request a fresh archive.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import logging
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from strava import config

logger = logging.getLogger(__name__)

Opener = Callable[[], io.BufferedIOBase]


class ExportSource:
    """Uniform read-only view over an export, whether a .zip or a directory
    it's already been extracted to."""

    def __init__(self, entries: dict[str, Opener]) -> None:
        # Maps a forward-slash relative path (as it appears in the archive)
        # to a callable that opens that file for binary reading.
        self._entries = entries

    @classmethod
    def open(cls, path: Path) -> ExportSource:
        if path.is_dir():
            return cls._from_dir(path)
        if path.suffix.lower() == ".zip":
            return cls._from_zip(path)
        raise ValueError(f"Unsupported export path (expected a .zip or directory): {path}")

    @classmethod
    def _from_dir(cls, root: Path) -> ExportSource:
        entries: dict[str, Opener] = {}
        for file_path in root.rglob("*"):
            if file_path.is_file():
                rel = file_path.relative_to(root).as_posix()
                entries[rel] = (lambda p=file_path: p.open("rb"))
        return cls(entries)

    @classmethod
    def _from_zip(cls, zip_path: Path) -> ExportSource:
        zf = zipfile.ZipFile(zip_path)
        entries: dict[str, Opener] = {}
        for info in zf.infolist():
            if not info.is_dir():
                entries[info.filename] = (lambda zf=zf, name=info.filename: zf.open(name))
        return cls(entries)

    def names(self) -> list[str]:
        return list(self._entries.keys())

    def open_entry(self, name: str) -> io.BufferedIOBase:
        return self._entries[name]()

    def find_csv(self) -> str | None:
        candidates = [n for n in self._entries if n.lower().endswith("activities.csv")]
        if not candidates:
            return None
        # Prefer the shallowest match in case of nested export folders.
        return min(candidates, key=lambda n: n.count("/"))

    def find_activity_file(self, activity_id: str, filename_hint: str | None) -> str | None:
        if filename_hint:
            hint_name = Path(filename_hint).name.lower()
            for name in self._entries:
                if Path(name).name.lower() == hint_name:
                    return name

        prefix_dot = f"{activity_id}."
        prefix_underscore = f"{activity_id}_"
        for name in self._entries:
            base = Path(name).name
            if base.startswith(prefix_dot) or base.startswith(prefix_underscore):
                return name
        return None


def _get_field(row: dict[str, Any], canonical: str) -> str | None:
    """Case-insensitive lookup of a CSV column, tolerant of header drift."""
    if canonical in row:
        value = row[canonical]
        return value.strip() if value else None
    lowered = canonical.lower()
    for key, value in row.items():
        if key and key.lower() == lowered:
            return value.strip() if value else None
    return None


def _existing_activity_file(activity_id: str) -> Path | None:
    matches = list(config.ACTIVITIES_DIR.glob(f"{activity_id}.*"))
    return matches[0] if matches else None


def _store_activity_file(activity_id: str, source_name: str, data: bytes) -> Path:
    ext = "".join(Path(source_name).suffixes)
    if ext.lower().endswith(".gz"):
        data = gzip.decompress(data)
        ext = ext[: -len(".gz")]
    if not ext:
        ext = ".dat"
    dest = config.ACTIVITIES_DIR / f"{activity_id}{ext}"
    dest.write_bytes(data)
    return dest


def load_state() -> dict[str, Any]:
    if not config.STATE_FILE.exists():
        return {"last_ingest_at": None, "last_export_path": None}
    return json.loads(config.STATE_FILE.read_text())


def save_state(state: dict[str, Any]) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def ingest(export_path: Path, *, force: bool = False) -> dict[str, int]:
    """Ingest one export archive. Returns counts of what was done."""
    config.ensure_dirs()
    source = ExportSource.open(export_path)

    csv_name = source.find_csv()
    if csv_name is None:
        raise FileNotFoundError(f"Could not find activities.csv in {export_path}")
    logger.info("Using %s as the activity summary CSV", csv_name)

    with source.open_entry(csv_name) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig")
        rows = list(csv.DictReader(text))

    stats = {
        "activities_seen": 0,
        "files_copied": 0,
        "files_skipped_existing": 0,
        "files_missing": 0,
        "meta_written": 0,
    }

    for row in rows:
        activity_id = _get_field(row, config.CSV_ID_COLUMN)
        if not activity_id:
            logger.warning("Skipping CSV row with no %s: %r", config.CSV_ID_COLUMN, row)
            continue
        stats["activities_seen"] += 1

        filename_hint = _get_field(row, config.CSV_FILENAME_COLUMN)
        existing = _existing_activity_file(activity_id)
        if existing is not None and not force:
            stats["files_skipped_existing"] += 1
        else:
            entry_name = source.find_activity_file(activity_id, filename_hint)
            if entry_name is None:
                # Common for manually-entered activities with no device file.
                stats["files_missing"] += 1
            else:
                with source.open_entry(entry_name) as f:
                    data = f.read()
                dest = _store_activity_file(activity_id, entry_name, data)
                logger.debug("Stored %s -> %s", entry_name, dest)
                stats["files_copied"] += 1

        meta_path = config.ACTIVITY_META_DIR / f"{activity_id}.json"
        meta_path.write_text(json.dumps(row, indent=2) + "\n")
        stats["meta_written"] += 1

    regenerate_index()

    state = load_state()
    state["last_ingest_at"] = datetime.now(tz=UTC).isoformat()
    state["last_export_path"] = str(export_path)
    state["total_activities"] = stats["activities_seen"]
    save_state(state)

    return stats


def regenerate_index() -> None:
    """Rebuild the flat activities_index.csv from all locally stored metadata."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, Any]] = []
    fieldnames: list[str] = []
    for path in config.ACTIVITY_META_DIR.glob("*.json"):
        row = json.loads(path.read_text())
        all_rows.append(row)
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    def sort_key(row: dict[str, Any]) -> int:
        activity_id = _get_field(row, config.CSV_ID_COLUMN)
        try:
            return int(activity_id)
        except (TypeError, ValueError):
            return 0

    all_rows.sort(key=sort_key, reverse=True)

    with config.INDEX_FILE.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest a Strava bulk-export archive (.zip or already-extracted "
            "directory) into local storage. Request a fresh archive anytime "
            "from https://www.strava.com/settings/profile -> 'Download or "
            "Delete Your Account' -> 'Request Your Archive', then re-run "
            "this script to pick up anything new."
        )
    )
    parser.add_argument("export_path", type=Path, help="Path to the export .zip or directory")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-copy activity files even if already stored locally.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not args.export_path.exists():
        parser.error(f"Export path does not exist: {args.export_path}")

    stats = ingest(args.export_path, force=args.force)
    print(
        f"Seen {stats['activities_seen']} activities: "
        f"{stats['files_copied']} files copied, "
        f"{stats['files_skipped_existing']} already present, "
        f"{stats['files_missing']} with no original file, "
        f"{stats['meta_written']} metadata rows written."
    )


if __name__ == "__main__":
    main()
