"""Shared pytest fixtures: redirect all Strava scripts' file I/O into a tmp dir."""

from __future__ import annotations

import pytest

from strava import config


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point all config paths at a temporary directory for the duration of a test."""
    data_dir = tmp_path / "data"

    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "RAW_DIR", data_dir / "raw")
    monkeypatch.setattr(config, "ACTIVITIES_DIR", data_dir / "raw" / "activities")
    monkeypatch.setattr(config, "ACTIVITY_META_DIR", data_dir / "raw" / "activity_meta")
    monkeypatch.setattr(config, "STATE_FILE", data_dir / "state.json")
    monkeypatch.setattr(config, "INDEX_FILE", data_dir / "activities_index.csv")

    return config
