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

## Project Structure

- `app.py` - Streamlit UI and orchestration.
- `data_loader/adapters/` - DB adapters (MySQL, ClickHouse, Greenplum).
- `data_loader/pipeline/` - file/query source, mapping, casting.
- `data_loader/core/` - models, safety checks, UI logging.

## Notes

- This tool is intended for internal team use.
- Review `SECURITY_NOTES.md` before broader rollout.
