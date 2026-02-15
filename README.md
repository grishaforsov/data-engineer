# Data Loader

Internal Streamlit app for quick data loading between files and databases.

## What It Does

- Load data from `Excel (.xlsx)` or `CSV (.csv)` into a destination DB table.
- Run SQL on a source DB and stream results into a destination DB table.
- Support column mapping from source columns to destination columns.
- Show preview, progress, and run logs in UI.

Supported databases:
- MySQL
- ClickHouse
- Greenplum

## Run

Windows:

1. Install Python (3.11+ recommended).
2. Open project folder.
3. Run `run.bat`.
4. Wait for dependencies to install.
5. Open `http://localhost:8501`.

## Main Modes

1. `File -> DB`
- Read uploaded file.
- Build mapping between source and destination columns.
- Load in batches.

2. `Query(DB) -> DB`
- Configure source and destination connections.
- Run source SQL.
- Stream/load in chunks into destination.

## Features

- Connection test for source and destination.
- Optional destination clear before load (`DELETE`/`TRUNCATE`).
- MySQL insert mode: `insert`, `insert ignore`, `replace`.
- ClickHouse type casting to destination schema.
- Greenplum `COPY`-based loading.
- Cancel flag for long-running load.
- Role-based access (`loader`, `admin`) when auth is enabled.
- SQL guardrails for query mode (single statement, read-only keywords policy, row/time caps).
- Destination clear confirmation (must type table name exactly).
- Audit events to JSONL file.

## Project Structure

- `app.py` - Streamlit UI and orchestration.
- `data_loader/adapters/` - DB adapters (MySQL, ClickHouse, Greenplum).
- `data_loader/pipeline/` - file/query source, mapping, casting.
- `data_loader/core/` - models, safety checks, UI logging.

## Notes

- This tool is intended for internal team use.
- Review `SECURITY_NOTES.md` before broader rollout.

## Environment Variables

- `DL_AUTH_REQUIRED` (`0/1`): enable login flow.
- `DL_USERS`: comma-separated users in format `user:password:role`.
  - Example: `alice:secret:admin,bob:secret:loader`
- `DL_ALLOWED_SOURCE_HOSTS`: optional source host allowlist (`host1,host2`).
- `DL_ALLOWED_DEST_HOSTS`: optional destination host allowlist.
- `DL_ALLOWED_SOURCE_DBS`: optional source DB allowlist.
- `DL_ALLOWED_DEST_DBS`: optional destination DB allowlist.
- `DL_MAX_QUERY_ROWS`: hard cap for query load row-limit input.
- `DL_MAX_QUERY_SECONDS`: timeout for query-load runs.
- `DL_QUERY_ALLOW_ONLY_SELECT` (`0/1`): restrict query mode to `SELECT/WITH`.
- `DL_AUDIT_PATH`: path to JSONL audit log file (default: `audit.log.jsonl`).
