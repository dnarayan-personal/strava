# Design: Downloading Personal Strava Data

## Goal
Build scripts to download all of a single Strava account's activity data
locally, and re-run periodically to pick up new activities (incremental
sync). This is the foundation for later parsing, search, and summarization
work, which is out of scope for now.

## Data source options (in preference order)

1. **Strava API v3 (official, documented) — not available to us**
   - OAuth2-authenticated REST API: https://developers.strava.com
   - As of 2026, registering a "Standard Tier" API app (the self-service
     tier needed for a personal script) requires an active paid Strava
     subscription (~$12/month). Free registration is no longer offered.
   - We don't have a subscription, so this path is **not used**. If that
     changes in the future, this is the preferred mechanism (structured
     JSON, natural pagination/filtering, no manual steps) and this design
     should be revisited.

2. **Strava bulk account export (official, GDPR-style) — primary mechanism**
   - Available via Settings → My Account → "Download or Delete Your Account"
     → "Request Your Archive". Strava emails a ZIP within a few hours.
   - Contains `activities.csv` (one summary row per activity: id, date,
     name, type, distance, heart rate, power, etc.) plus an `activities/`
     folder with the original GPX/TCX/FIT file per activity (sometimes
     gzip-compressed), plus profile/gear/routes data.
   - Free, requires no app registration/subscription.
   - Cannot be triggered or polled programmatically — it's a manual,
     email-delivered action initiated from the Strava website. "Periodic
     sync" therefore means: the user periodically re-requests a fresh
     archive (it always contains full history) and re-runs our ingestion
     script, which only copies what's new since the last ingestion.
   - This is what the scripts in this repo implement.

3. **Web scraping (last resort, not used)**
   - Only relevant if the export is missing data we need later. Fragile,
     against Strava's ToS in spirit, and unnecessary given the export
     covers activity summaries and original files. Not implemented unless
     a specific gap is found and explicitly approved.

**Decision:** Ingest Strava's manual bulk-export archive. No API, no
scraping.

## Ingestion workflow

1. User manually requests an archive from Strava (see link above) and
   downloads the resulting ZIP once Strava emails a link (can take a few
   hours). This step cannot be automated.
2. User runs `uv run strava-ingest <path-to-export.zip-or-directory>`.
3. The script:
   - Opens the export (either the `.zip` directly, via Python's `zipfile`,
     or an already-extracted directory — both are supported transparently).
   - Locates `activities.csv` inside it and parses it row by row.
   - For each row, resolves the activity's original file (using the CSV's
     `Filename` column if present, else falling back to a filename-prefix
     match on the activity id) and copies/decompresses it into local
     storage — **unless a file for that activity id is already stored
     locally**, in which case it's skipped (idempotent, incremental).
   - Writes the CSV row as JSON metadata for every activity (cheap, always
     refreshed, so edits/renames in Strava are picked up on re-ingestion
     even though the original file itself is treated as immutable).
   - Regenerates a flat `activities_index.csv` from all locally stored
     metadata, sorted by activity id (descending — a reliable proxy for
     recency since Strava activity ids are assigned in increasing order).
   - Updates a local state file recording the last ingestion time and which
     export path was last processed (informational; ingestion itself is
     re-derived from what's on disk each run, not from the state file).
- Since manually-entered activities (e.g. logged without a device) have a
  CSV row but no original file, this is expected and tracked separately
  (`files_missing` in the ingestion summary) rather than treated as an
  error.
- Re-running ingestion against the same or a newer export is always safe:
  existing files are left untouched unless `--force` is passed.

## Local storage layout

```
data/
  raw/
    activities/{activity_id}.{gpx,tcx,fit,...}   # original per-activity file
    activity_meta/{activity_id}.json              # that activity's activities.csv row
  activities_index.csv                            # flat summary table, regenerated
                                                    # from activity_meta/ on every run
  state.json                                       # last ingest time / export path
```

- Original per-activity files under `data/raw/activities/` are the closest
  thing to a source of truth we control locally (Strava's export is the
  actual source of truth, but isn't re-fetchable on demand).
- `activities_index.csv` is a convenience denormalized view; it is always
  regenerated from `activity_meta/`, never hand-maintained.
- `data/` is git-ignored — this is personal data, not something to commit
  to the repo.

## Project setup & script structure

The project is managed with [uv](https://docs.astral.sh/uv/) and a standard
`src/` layout:

```
pyproject.toml           # uv-managed project + dependency manifest
uv.lock                  # locked dependency versions (committed)
src/strava/
  __init__.py
  config.py              # shared paths/constants
  ingest.py              # main entrypoint: parses + ingests an export archive
.gitignore                # excludes data/, .venv/
```

- `pyproject.toml` declares a console-script entry point `strava-ingest`,
  runnable via `uv run strava-ingest <export path>` (uv handles creating/
  using the project virtualenv automatically).
- `uv add <package>` / `uv add --dev <package>` are used to add any new
  runtime/dev dependency, keeping `pyproject.toml`/`uv.lock` in sync. The
  ingestion script currently only needs the Python standard library.
- Logging to stdout with counts of activities seen, files copied/skipped/
  missing, and metadata rows written.

## Out of scope for this phase
- Parsing/analyzing activity data (future work).
- Multi-athlete/shared use (this is single-user/personal only).
- Automating the request/download of the export itself (Strava does not
  offer a way to trigger or poll this programmatically).
- The Strava API (revisit if a paid subscription is obtained later).
