from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import typer

from src.core import FifoEngine
from src.models import NormalizedTransaction
from src.parsers import DeGiroParser, TradeRepublicParser

app = typer.Typer(help="FIFO tracker CLI")


@app.callback()
def app_callback() -> None:
    return None


def fmt(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


BROKER_PARSERS = {
    "degiro": DeGiroParser,
    "trade-republic": TradeRepublicParser,
}

BROKER_FOLDER_ALIASES = {
    "degiro": ["degiro"],
    "trade-republic": ["trade-republic", "trade_republic", "traderepublic"],
}


def _normalize_broker_name(raw_value: str) -> str:
    return raw_value.strip().lower().replace("_", "-")


def _parse_brokers_option(brokers: str) -> list[str]:
    normalized = _normalize_broker_name(brokers)
    if normalized in {"all", "*"}:
        return sorted(BROKER_PARSERS.keys())

    selected = [_normalize_broker_name(item) for item in brokers.split(",") if item.strip()]
    invalid = sorted(set(selected) - set(BROKER_PARSERS.keys()))
    if invalid:
        supported = ", ".join(sorted(BROKER_PARSERS.keys()))
        invalid_joined = ", ".join(invalid)
        raise typer.BadParameter(
            f"Unsupported broker(s): {invalid_joined}. Supported values: {supported}, all"
        )

    if not selected:
        raise typer.BadParameter("--brokers cannot be empty")

    return sorted(set(selected))


def _discover_csv_files(data_dir: Path, broker: str) -> list[Path]:
    files: list[Path] = []
    for folder_alias in BROKER_FOLDER_ALIASES[broker]:
        broker_dir = data_dir / folder_alias
        if not broker_dir.exists() or not broker_dir.is_dir():
            continue

        discovered = [
            path
            for path in broker_dir.rglob("*")
            if path.is_file() and path.suffix.lower() == ".csv"
        ]
        files.extend(discovered)

    return sorted(set(files))


def _load_transactions_from_data_dir(data_dir: Path, brokers: list[str]) -> list[NormalizedTransaction]:
    transactions: list[NormalizedTransaction] = []

    for broker in brokers:
        parser = BROKER_PARSERS[broker]()
        broker_files = _discover_csv_files(data_dir, broker)
        for csv_file in broker_files:
            transactions.extend(parser.parse_file(csv_file))

    return sorted(transactions, key=lambda tx: tx.timestamp)


@app.command("report")
def report_command(
    data_dir: Path = typer.Option(
        Path("data"),
        "--data-dir",
        help="Base folder containing broker subfolders with CSV files",
        envvar="FIFO_DATA_DIR",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
    brokers: str = typer.Option(
        "all",
        "--brokers",
        help="Comma-separated brokers to include, e.g. degiro,trade-republic or all",
    ),
    fiscal_year: int | None = typer.Option(
        None,
        "--fiscal-year",
        help="Filter realized sales by fiscal year (sell date year)",
    ),
    detailed: bool = typer.Option(
        False,
        "--detailed",
        help="Print detailed FIFO match lines for each sell",
    ),
) -> None:
    selected_brokers = _parse_brokers_option(brokers)
    transactions = _load_transactions_from_data_dir(data_dir, selected_brokers)
    if not transactions:
        broker_text = ", ".join(selected_brokers)
        raise typer.BadParameter(
            f"No CSV transactions found in {data_dir} for brokers: {broker_text}. "
            "Expected files under data_dir/<broker>/*.csv"
        )

    engine = FifoEngine()
    report = engine.build_report(transactions)

    if fiscal_year is not None:
        report = engine.filter_report_by_fiscal_year(report, fiscal_year)

    title = "FIFO Report Summary"
    if fiscal_year is not None:
        title = f"FIFO Report Summary (fiscal year {fiscal_year})"

    typer.echo(title)
    typer.echo("=" * len(title))
    typer.echo(f"Realized sales: {len(report.realized_sales)}")
    typer.echo(f"Total proceeds: {fmt(report.total_proceeds)} EUR")
    typer.echo(f"Total cost basis: {fmt(report.total_cost_basis)} EUR")
    typer.echo(f"Total realized gain: {fmt(report.total_realized_gain)} EUR")

    typer.echo("\nBy asset")
    typer.echo("--------")
    for asset in report.assets:
        if not asset.realized_sales and asset.open_quantity_total == 0:
            continue

        typer.echo(
            f"{asset.isin} | {asset.name} | "
            f"realized={fmt(asset.realized_gain_total)} EUR | "
            f"open_qty={asset.open_quantity_total} | "
            f"open_cost={fmt(asset.open_cost_total)} EUR"
        )

    typer.echo("\nRealized sales")
    typer.echo("--------------")
    for sale in report.realized_sales:
        typer.echo(
            f"SELL {sale.sell_transaction.timestamp.isoformat()} | {sale.isin} | {sale.name} | "
            f"qty={sale.total_quantity} | proceeds={fmt(sale.total_proceeds)} | "
            f"cost={fmt(sale.total_cost_basis)} | gain={fmt(sale.total_realized_gain)}"
        )

        if detailed:
            for match in sale.matches:
                typer.echo(
                    f"  MATCH buy={match.buy_timestamp.isoformat()} -> "
                    f"sell={match.sell_timestamp.isoformat()} | qty={match.quantity} | "
                    f"buy_u={fmt(match.buy_unit_cost)} | sell_u={fmt(match.sell_unit_net)} | "
                    f"cost={fmt(match.cost_basis)} | proceeds={fmt(match.proceeds)} | "
                    f"gain={fmt(match.realized_gain)}"
                )


@app.command("ui")
def ui_command(
    data_dir: Path = typer.Option(
        Path("data"),
        "--data-dir",
        help="Base folder containing broker subfolders with CSV files",
        envvar="FIFO_DATA_DIR",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
    brokers: str = typer.Option(
        "all",
        "--brokers",
        help="Comma-separated brokers to include, e.g. degiro,trade-republic or all",
    ),
    port: int = typer.Option(
        8050,
        "--port",
        help="Port for the web server",
    ),
    no_open: bool = typer.Option(
        False,
        "--no-open",
        help="Don't auto-open the browser",
    ),
) -> None:
    """Launch an interactive web UI in the browser."""
    import webbrowser

    import uvicorn

    from src.web.app import app as fastapi_app
    from src.web.app import init_app

    selected_brokers = _parse_brokers_option(brokers)
    init_app(data_dir, selected_brokers)

    url = f"http://localhost:{port}"
    typer.echo(f"Starting FIFO Tracker UI at {url}")

    if not no_open:
        webbrowser.open(url)

    uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="warning")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
