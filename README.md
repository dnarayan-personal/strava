# strava
Download and analyze personal strava data

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

## Usage

Strava's API now requires a paid subscription for personal ("Standard
Tier") apps, so this project instead uses Strava's free manual bulk-export
feature:

1. On strava.com, go to Settings → My Account →
   "Download or Delete Your Account" → "Request Your Archive". Strava
   emails you a link to a ZIP archive (can take a few hours).
2. Download the ZIP (no need to unzip it).
3. Ingest it:

   ```sh
   uv run strava-ingest ~/Downloads/export_12345.zip
   ```

   This is safe and cheap to re-run: it only copies activity files that
   aren't already stored locally. To periodically pick up new activities,
   just repeat steps 1–3 with a fresh archive whenever you like.

   Useful flags: `--force` (re-copy activity files even if already stored
   locally), `-v` (debug logging).

Downloaded data is stored under `data/` (git-ignored): original per-activity
GPX/TCX/FIT files under `data/raw/activities`, per-activity metadata (from
`activities.csv`) under `data/raw/activity_meta`, plus a flat
`data/activities_index.csv` summary regenerated on every ingestion.

See [docs/data-download-design.md](docs/data-download-design.md) for the
full design.

## Tests

```sh
uv run pytest
```
