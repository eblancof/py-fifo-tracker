from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from src.core import (
    FifoEngine,
    InvalidSimulationIdError,
    SimulationNotFoundError,
    SimulationService,
    SimulationValidationError,
)
from src.models import PortfolioFifoReport
from src.models import NormalizedTransaction

app = FastAPI(title="FIFO Tracker")

_report_cache: dict[str, Any] = {}


def _decimal(v: Decimal) -> float:
    return float(round(v, 4))


def _serialize_report(report: PortfolioFifoReport) -> dict[str, Any]:
    assets = []
    for a in report.assets:
        realized_sales = []
        for s in a.realized_sales:
            matches = [
                {
                    "quantity": _decimal(m.quantity),
                    "buy_timestamp": m.buy_timestamp.isoformat(),
                    "sell_timestamp": m.sell_timestamp.isoformat(),
                    "buy_unit_cost": _decimal(m.buy_unit_cost),
                    "sell_unit_net": _decimal(m.sell_unit_net),
                    "cost_basis": _decimal(m.cost_basis),
                    "proceeds": _decimal(m.proceeds),
                    "realized_gain": _decimal(m.realized_gain),
                }
                for m in s.matches
            ]
            realized_sales.append(
                {
                    "sell_timestamp": s.sell_transaction.timestamp.isoformat(),
                    "broker": s.sell_transaction.broker,
                    "quantity": _decimal(s.total_quantity),
                    "cost_basis": _decimal(s.total_cost_basis),
                    "proceeds": _decimal(s.total_proceeds),
                    "realized_gain": _decimal(s.total_realized_gain),
                    "matches": matches,
                }
            )
        open_lots = [
            {
                "timestamp": lot.timestamp.isoformat(),
                "quantity_remaining": _decimal(lot.quantity_remaining),
                "unit_cost": _decimal(lot.unit_cost),
                "broker": lot.source_transaction.broker,
            }
            for lot in a.open_lots
            if lot.quantity_remaining > 0
        ]
        assets.append(
            {
                "isin": a.isin,
                "name": a.name,
                "realized_gain_total": _decimal(a.realized_gain_total),
                "open_quantity_total": _decimal(a.open_quantity_total),
                "open_cost_total": _decimal(a.open_cost_total),
                "realized_sales": realized_sales,
                "open_lots": open_lots,
            }
        )

    return {
        "generated_at": report.generated_at.isoformat(),
        "total_realized_gain": _decimal(report.total_realized_gain),
        "total_cost_basis": _decimal(report.total_cost_basis),
        "total_proceeds": _decimal(report.total_proceeds),
        "realized_sales_count": len(report.realized_sales),
        "assets": assets,
    }


def _simulation_service() -> SimulationService:
    service: SimulationService | None = _report_cache.get("simulation_service")
    if service is None:
        raise HTTPException(status_code=500, detail="Application not initialized")
    return service


def _raise_http_for_simulation_error(exc: Exception) -> None:
    if isinstance(exc, InvalidSimulationIdError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, SimulationNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, SimulationValidationError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


def init_app(data_dir: Path, brokers: list[str]) -> None:
    from src.cli import _load_transactions_from_data_dir

    transactions = _load_transactions_from_data_dir(data_dir, brokers)
    engine = FifoEngine()
    full_report = engine.build_report(transactions)

    _report_cache["engine"] = engine
    _report_cache["transactions"] = transactions
    _report_cache["full_report"] = full_report
    _report_cache["simulation_service"] = SimulationService(data_dir)

    years = sorted(
        {s.sell_transaction.timestamp.year for s in full_report.realized_sales}
    )
    _report_cache["fiscal_years"] = years


@app.get("/api/report")
def api_report(
    fiscal_year: int | None = Query(None),
    simulation_id: str | None = Query(None),
) -> dict[str, Any]:
    engine: FifoEngine = _report_cache["engine"]
    base_transactions: list[NormalizedTransaction] = _report_cache.get("transactions", [])
    full_report: PortfolioFifoReport = _report_cache["full_report"]

    try:
        report: PortfolioFifoReport = _simulation_service().build_report_with_simulation(
            engine=engine,
            base_transactions=base_transactions,
            full_report=full_report,
            simulation_id=simulation_id,
        )
    except Exception as exc:
        _raise_http_for_simulation_error(exc)
        raise

    years = sorted({s.sell_transaction.timestamp.year for s in report.realized_sales})

    if fiscal_year is not None:
        report = engine.filter_report_by_fiscal_year(report, fiscal_year)

    data = _serialize_report(report)
    data["fiscal_years"] = years
    data["selected_fiscal_year"] = fiscal_year
    data["selected_simulation"] = simulation_id
    return data


@app.get("/api/simulations")
def api_list_simulations() -> dict[str, Any]:
    return {"simulations": _simulation_service().list_simulations()}


@app.get("/api/assets")
def api_assets() -> dict[str, Any]:
    transactions: list[NormalizedTransaction] = _report_cache.get("transactions", [])
    return {"assets": _simulation_service().available_assets(transactions)}


@app.post("/api/simulations")
def api_create_simulation(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        simulation = _simulation_service().create_simulation(str(payload.get("name", "")))
    except Exception as exc:
        _raise_http_for_simulation_error(exc)
        raise
    return {"simulation": simulation}


@app.get("/api/simulations/{simulation_id}")
def api_get_simulation(simulation_id: str) -> dict[str, Any]:
    try:
        simulation = _simulation_service().simulation_details(simulation_id)
    except Exception as exc:
        _raise_http_for_simulation_error(exc)
        raise
    return {"simulation": simulation}


@app.delete("/api/simulations/{simulation_id}")
def api_delete_simulation(simulation_id: str) -> dict[str, Any]:
    try:
        _simulation_service().delete_simulation(simulation_id)
    except Exception as exc:
        _raise_http_for_simulation_error(exc)
        raise
    return {"ok": True}


@app.post("/api/simulations/{simulation_id}/transactions")
def api_add_simulation_transaction(simulation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    engine: FifoEngine = _report_cache["engine"]
    base_transactions: list[NormalizedTransaction] = _report_cache.get("transactions", [])

    try:
        simulation = _simulation_service().add_transaction(
            simulation_id=simulation_id,
            payload=payload,
            engine=engine,
            base_transactions=base_transactions,
        )
    except Exception as exc:
        _raise_http_for_simulation_error(exc)
        raise

    return {"simulation": simulation}


@app.delete("/api/simulations/{simulation_id}/transactions/{transaction_index}")
def api_delete_simulation_transaction(simulation_id: str, transaction_index: int) -> dict[str, Any]:
    try:
        simulation = _simulation_service().delete_transaction(simulation_id, transaction_index)
    except Exception as exc:
        _raise_http_for_simulation_error(exc)
        raise
    return {"simulation": simulation}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html_path = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
