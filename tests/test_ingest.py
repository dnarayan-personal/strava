"""Tests for strava.ingest: parsing exports and merging into local storage."""

from __future__ import annotations

import csv
import gzip
import io
import json
import zipfile

from strava import ingest


ACTIVITIES_CSV_HEADER = [
    "Activity ID",
    "Activity Date",
    "Activity Name",
    "Activity Type",
    "Filename",
    "Distance",
]


def _write_csv_rows(rows: list[list[str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(ACTIVITIES_CSV_HEADER)
    writer.writerows(rows)
    return buf.getvalue()


def _make_zip_export(tmp_path, rows, files: dict[str, bytes]) -> "type":
    tmp_path.mkdir(parents=True, exist_ok=True)
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("activities.csv", _write_csv_rows(rows))
        for name, data in files.items():
            zf.writestr(name, data)
    return zip_path


def _make_dir_export(tmp_path, rows, files: dict[str, bytes]):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / "activities.csv").write_text(_write_csv_rows(rows))
    activities_dir = export_dir / "activities"
    activities_dir.mkdir()
    for name, data in files.items():
        (activities_dir / name).write_bytes(data)
    return export_dir


def test_ingest_from_zip_copies_files_and_metadata(isolated_config, tmp_path):
    rows = [["111", "2024-01-01", "Morning Run", "Run", "activities/111.gpx", "5000"]]
    files = {"activities/111.gpx": b"<gpx>fake</gpx>"}
    zip_path = _make_zip_export(tmp_path, rows, files)

    stats = ingest.ingest(zip_path)

    assert stats["activities_seen"] == 1
    assert stats["files_copied"] == 1
    assert stats["meta_written"] == 1

    stored = isolated_config.ACTIVITIES_DIR / "111.gpx"
    assert stored.read_bytes() == b"<gpx>fake</gpx>"

    meta = json.loads((isolated_config.ACTIVITY_META_DIR / "111.json").read_text())
    assert meta["Activity Name"] == "Morning Run"


def test_ingest_from_directory_works_same_as_zip(isolated_config, tmp_path):
    rows = [["222", "2024-01-02", "Evening Ride", "Ride", "activities/222.fit", "10000"]]
    files = {"222.fit": b"FITDATA"}
    export_dir = _make_dir_export(tmp_path, rows, files)

    stats = ingest.ingest(export_dir)

    assert stats["files_copied"] == 1
    assert (isolated_config.ACTIVITIES_DIR / "222.fit").read_bytes() == b"FITDATA"


def test_ingest_decompresses_gzipped_activity_files(isolated_config, tmp_path):
    raw = b"<gpx>gzipped</gpx>"
    compressed = gzip.compress(raw)
    rows = [["333", "2024-01-03", "Trail Run", "Run", "activities/333.gpx.gz", "3000"]]
    files = {"activities/333.gpx.gz": compressed}
    zip_path = _make_zip_export(tmp_path, rows, files)

    ingest.ingest(zip_path)

    stored = isolated_config.ACTIVITIES_DIR / "333.gpx"
    assert stored.exists()
    assert stored.read_bytes() == raw


def test_ingest_handles_activity_with_no_original_file(isolated_config, tmp_path):
    # Manually-entered activities have a CSV row but no device file.
    rows = [["444", "2024-01-04", "Manual Walk", "Walk", "", "1000"]]
    zip_path = _make_zip_export(tmp_path, rows, files={})

    stats = ingest.ingest(zip_path)

    assert stats["files_missing"] == 1
    assert stats["meta_written"] == 1
    assert not list(isolated_config.ACTIVITIES_DIR.glob("444.*"))


def test_re_ingest_skips_existing_files_unless_forced(isolated_config, tmp_path):
    rows = [["555", "2024-01-05", "Run", "Run", "activities/555.gpx", "2000"]]
    files = {"activities/555.gpx": b"original"}
    zip_path = _make_zip_export(tmp_path, rows, files)
    ingest.ingest(zip_path)

    # Simulate a second export where the file content changed (shouldn't happen
    # in practice for past activities, but verifies skip-by-default behavior).
    zip_path2 = _make_zip_export(tmp_path / "reexport", rows, {"activities/555.gpx": b"changed"})
    stats = ingest.ingest(zip_path2)
    assert stats["files_skipped_existing"] == 1
    assert (isolated_config.ACTIVITIES_DIR / "555.gpx").read_bytes() == b"original"

    stats_forced = ingest.ingest(zip_path2, force=True)
    assert stats_forced["files_copied"] == 1
    assert (isolated_config.ACTIVITIES_DIR / "555.gpx").read_bytes() == b"changed"


def test_regenerate_index_sorts_by_activity_id_descending(isolated_config, tmp_path):
    rows = [
        ["1", "2024-01-01", "First", "Run", "activities/1.gpx", "1"],
        ["2", "2024-01-02", "Second", "Run", "activities/2.gpx", "2"],
    ]
    files = {"activities/1.gpx": b"a", "activities/2.gpx": b"b"}
    zip_path = _make_zip_export(tmp_path, rows, files)

    ingest.ingest(zip_path)

    with isolated_config.INDEX_FILE.open() as f:
        index_rows = list(csv.DictReader(f))
    assert [r["Activity ID"] for r in index_rows] == ["2", "1"]


def test_state_file_updated_after_ingest(isolated_config, tmp_path):
    rows = [["666", "2024-01-06", "Run", "Run", "activities/666.gpx", "1"]]
    files = {"activities/666.gpx": b"a"}
    zip_path = _make_zip_export(tmp_path, rows, files)

    ingest.ingest(zip_path)

    state = ingest.load_state()
    assert state["total_activities"] == 1
    assert state["last_export_path"] == str(zip_path)
    assert state["last_ingest_at"] is not None
