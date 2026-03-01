# py-fifo-tracker

A small toolkit to parse broker CSV exports, compute FIFO (first-in-first-out) cost basis, and run interactive simulations.

**Main features**
- Parse multiple broker CSV formats using JSON schemas in [src/parsers/schemas](src/parsers/schemas).
- Compute realized gains/losses using a FIFO engine that matches oldest buys to sells by ISIN.
- Produce per-asset and portfolio-level reports, including detailed FIFO match lines and remaining open lots.
- Run an interactive web UI (FastAPI + simple frontend) that lists assets, fiscal years, and allows creating/tweaking simulations.
- Keep sanitized sample broker exports in `data/degiro/` and `data/trade-republic/` for quick testing.

## Getting started

1. Create and activate a virtual environment (recommended):

```bash
uv venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv sync
```

By default the CLI reads CSVs from `data/<broker>/` directories (those sample files are included in the repo). You should rename `degiro-mock` to `degiro` and `trade-republic-mock` to `trade-republic` to match the expected structure, or place your own exports in those folders.

- To export from Degiro: Inbox -> Transactions -> Select date range -> Download button -> CSV.
- To export from Trade Republic: Use tools like `pytr` (https://github.com/pytr-org/pytr) to download transaction history as CSV.

You can override the data directory with the `FIFO_DATA_DIR` environment variable.

## CLI usage

Run the report generator (reads CSVs, builds FIFO report, prints results):

```powershell
python -m src.cli report
```

Or (after installing the package entrypoint):

```powershell
py-fifo-tracker report
```

Options:
- `--brokers`: comma-separated list of brokers to include (e.g. `degiro,trade-republic`).
- `--fiscal-year`: filter report by sell-year (integer).
- `--detailed`: include full FIFO match details per sale.

Examples:

```powershell
python -m src.cli report --brokers=degiro --fiscal-year=2025 --detailed
```

## Web UI

The project includes a small FastAPI web app that serves a single-page frontend and REST API endpoints.

- Start the UI (development): `python -m src.web.app` or use the provided entrypoint (py-fifo-tracker ui`) if installed.
- The UI endpoints (JSON):
	- `GET /api/report` — returns the current report data (optionally filtered by `fiscal_year` and `simulation_id`).
	- `GET /api/simulations` — list saved simulations.
	- `POST /api/simulations` — create a new simulation (payload: `{ "name": "My sim" }`).
	- `POST /api/simulations/{id}/transactions` — add a transaction to a simulation.

The UI allows creating simulations that apply hypothetical buy/sell transactions on top of your imported data, then recomputes the FIFO matches.

## Parsers and schemas

Broker parsers are configured via JSON schemas in `src/parsers/schemas` (one schema per broker). Schemas define:

- `delimiter`: CSV delimiter for that export.
- `header_aliases`: map of canonical field names to possible column header names found in broker CSVs.
- `required_fields`: fields the parser expects to find.
- `transaction_type_aliases` (optional): map buy/sell type aliases.

To add a new broker:
1. Add `<broker>.json` in `src/parsers/schemas/` with the schema shape above.
2. Ensure the schema's `header_aliases` map matches the broker's CSV headers.

The parser implementation in `src/parsers` handles normalization and uses the schema to load CSVs into `NormalizedTransaction` objects consumed by the FIFO engine.

## Simulations

Simulations live in the app service and allow you to:
- Create named simulation sessions.
- Add or remove synthetic transactions (buys/sells) that are applied on top of imported data.
- Inspect how simulated trades would affect realized gains and open lots.

Simulation management endpoints are available under `/api/simulations`. Use the web UI or the API directly for automated testing.

## Data files included

- `data/degiro-mock/mock.csv` — small sanitized example for Degiro exports.
- `data/trade-republic-mock/mock.csv` — small sanitized example for Trade Republic exports.

These sample files are tracked in the repository to make it easy to try the app without needing broker exports. Real exports should be stored outside the repo or in a private branch.

## Development notes

- The FIFO logic is implemented in `src/core/fifo.py` and the domain models in `src/core/fifo_models.py`.
- Parser helpers are in `src/parsers/common.py` and broker-specific code in `src/parsers/brokers`.
- The web UI is a minimal SPA served from `src/web/templates/index.html` and backed by `src/web/app.py`.
