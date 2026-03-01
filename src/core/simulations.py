from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import re
from typing import Any

from src.core.fifo import FifoEngine
from src.models import PortfolioFifoReport
from src.models import NormalizedTransaction

SIMULATION_HEADERS = [
    "timestamp",
    "name",
    "isin",
    "transaction_type",
    "quantity",
    "price_per_share",
    "commissions",
    "broker",
    "currency",
]


class SimulationError(ValueError):
    pass


class InvalidSimulationIdError(SimulationError):
    pass


class SimulationNotFoundError(SimulationError):
    pass


class SimulationValidationError(SimulationError):
    pass


class SimulationService:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def list_simulations(self) -> list[dict[str, Any]]:
        return [self._serialize_simulation(file_path) for file_path in self._list_simulation_files()]

    def create_simulation(self, name: str) -> dict[str, Any]:
        raw_name = name.strip()
        if not raw_name:
            raise SimulationValidationError("Simulation name is required")

        slug = self._slugify_name(raw_name)
        date_part = datetime.now().strftime("%Y-%m-%d")
        base_name = f"{slug}__{date_part}"

        candidate = self._simulations_dir() / f"{base_name}.csv"
        suffix = 2
        while candidate.exists():
            candidate = self._simulations_dir() / f"{base_name}_{suffix}.csv"
            suffix += 1

        self._write_rows(candidate, [])
        return self.simulation_details(candidate.name)

    def simulation_details(self, simulation_id: str) -> dict[str, Any]:
        simulation_file = self._resolve_simulation_file(simulation_id)
        rows = self._read_rows(simulation_file)
        simulation = self._serialize_simulation(simulation_file)
        simulation["transactions"] = self._serialize_rows(rows)
        return simulation

    def delete_simulation(self, simulation_id: str) -> None:
        simulation_file = self._resolve_simulation_file(simulation_id)
        simulation_file.unlink(missing_ok=False)

    def add_transaction(
        self,
        simulation_id: str,
        payload: dict[str, Any],
        engine: FifoEngine,
        base_transactions: list[NormalizedTransaction],
    ) -> dict[str, Any]:
        simulation_file = self._resolve_simulation_file(simulation_id)
        existing_rows = self._read_rows(simulation_file)

        timestamp = str(payload.get("timestamp") or datetime.now().replace(microsecond=0).isoformat()).strip()
        if len(timestamp) == 16:
            timestamp = f"{timestamp}:00"

        new_row = {
            "timestamp": timestamp,
            "name": str(payload.get("name", "")).strip(),
            "isin": str(payload.get("isin", "")).strip(),
            "transaction_type": str(payload.get("transaction_type", "")).strip().lower(),
            "quantity": str(payload.get("quantity", "")).strip(),
            "price_per_share": str(payload.get("price_per_share", "")).strip(),
            "commissions": str(payload.get("commissions", "0")).strip() or "0",
            "broker": str(payload.get("broker", "simulation")).strip() or "simulation",
            "currency": str(payload.get("currency", "EUR")).strip() or "EUR",
        }

        updated_rows = [*existing_rows, new_row]
        simulation_transactions = self._rows_to_transactions(updated_rows)

        try:
            engine.build_report(base_transactions + simulation_transactions)
        except ValueError as exc:
            raise SimulationValidationError(str(exc)) from exc

        self._write_rows(simulation_file, updated_rows)
        return self.simulation_details(simulation_id)

    def delete_transaction(self, simulation_id: str, transaction_index: int) -> dict[str, Any]:
        simulation_file = self._resolve_simulation_file(simulation_id)
        rows = self._read_rows(simulation_file)

        if transaction_index < 0 or transaction_index >= len(rows):
            raise SimulationNotFoundError("Transaction not found")

        rows.pop(transaction_index)
        self._write_rows(simulation_file, rows)
        return self.simulation_details(simulation_id)

    def build_report_with_simulation(
        self,
        engine: FifoEngine,
        base_transactions: list[NormalizedTransaction],
        full_report: PortfolioFifoReport,
        simulation_id: str | None,
    ) -> PortfolioFifoReport:
        if not simulation_id:
            return full_report

        simulation_file = self._resolve_simulation_file(simulation_id)
        simulation_rows = self._read_rows(simulation_file)
        simulation_transactions = self._rows_to_transactions(simulation_rows)

        try:
            return engine.build_report(base_transactions + simulation_transactions)
        except ValueError as exc:
            raise SimulationValidationError(str(exc)) from exc

    def available_assets(self, transactions: list[NormalizedTransaction]) -> list[dict[str, str]]:
        by_isin: dict[str, str] = {}

        for tx in transactions:
            isin = tx.isin.strip()
            name = tx.name.strip()
            if not isin or not name:
                continue
            if isin not in by_isin:
                by_isin[isin] = name

        return [
            {"isin": isin, "name": name}
            for isin, name in sorted(by_isin.items(), key=lambda item: (item[1].lower(), item[0]))
        ]

    def _simulations_dir(self) -> Path:
        simulations_path = self._data_dir / "simulations"
        simulations_path.mkdir(parents=True, exist_ok=True)
        return simulations_path

    def _list_simulation_files(self) -> list[Path]:
        return sorted(
            [path for path in self._simulations_dir().iterdir() if path.is_file() and path.suffix.lower() == ".csv"],
            key=lambda p: p.name.lower(),
        )

    def _resolve_simulation_file(self, simulation_id: str) -> Path:
        file_name = Path(simulation_id).name
        if file_name != simulation_id or not file_name.endswith(".csv"):
            raise InvalidSimulationIdError("Invalid simulation id")

        file_path = self._simulations_dir() / file_name
        if not file_path.exists() or not file_path.is_file():
            raise SimulationNotFoundError("Simulation not found")
        return file_path

    def _read_rows(self, file_path: Path) -> list[dict[str, str]]:
        if not file_path.exists():
            return []

        with file_path.open("r", encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            rows: list[dict[str, str]] = []
            for row in reader:
                rows.append({key: (row.get(key) or "") for key in SIMULATION_HEADERS})
            return rows

    def _write_rows(self, file_path: Path, rows: list[dict[str, str]]) -> None:
        with file_path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=SIMULATION_HEADERS)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in SIMULATION_HEADERS})

    def _rows_to_transactions(self, rows: list[dict[str, str]]) -> list[NormalizedTransaction]:
        transactions: list[NormalizedTransaction] = []
        for row in rows:
            try:
                timestamp = datetime.fromisoformat((row.get("timestamp") or "").strip())
                name = (row.get("name") or "").strip()
                isin = (row.get("isin") or "").strip()
                transaction_type = (row.get("transaction_type") or "").strip().lower()
                quantity = Decimal((row.get("quantity") or "0").strip())
                price_per_share = Decimal((row.get("price_per_share") or "0").strip())
                commissions = Decimal((row.get("commissions") or "0").strip())
                broker = (row.get("broker") or "simulation").strip() or "simulation"
                currency = (row.get("currency") or "EUR").strip() or "EUR"
            except Exception as exc:
                raise SimulationValidationError(f"Invalid simulation CSV format: {exc}") from exc

            if not isin or not name:
                raise SimulationValidationError("Simulation transaction requires name and ISIN")
            if transaction_type not in {"buy", "sell"}:
                raise SimulationValidationError("Simulation transaction_type must be buy or sell")
            if quantity <= 0:
                raise SimulationValidationError("Simulation quantity must be positive")
            if price_per_share <= 0:
                raise SimulationValidationError("Simulation price_per_share must be positive")

            total_amount = quantity * price_per_share

            transactions.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    name=name,
                    isin=isin,
                    quantity=quantity,
                    price_per_share=price_per_share,
                    commissions=commissions,
                    total_amount=total_amount,
                    broker=broker,
                    currency=currency,
                    transaction_type=transaction_type,
                )
            )

        return sorted(transactions, key=lambda tx: tx.timestamp)

    def _serialize_simulation(self, file_path: Path) -> dict[str, Any]:
        rows = self._read_rows(file_path)
        parts = file_path.stem.split("__", 1)
        date_part = parts[1] if len(parts) > 1 else ""
        return {
            "id": file_path.name,
            "name": self._display_name_from_file(file_path),
            "date": date_part,
            "transactions_count": len(rows),
        }

    def _serialize_rows(self, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
        payload_rows: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            payload_rows.append(
                {
                    "index": index,
                    "timestamp": row.get("timestamp", ""),
                    "name": row.get("name", ""),
                    "isin": row.get("isin", ""),
                    "transaction_type": row.get("transaction_type", ""),
                    "quantity": row.get("quantity", ""),
                    "price_per_share": row.get("price_per_share", ""),
                    "commissions": row.get("commissions", ""),
                    "broker": row.get("broker", ""),
                    "currency": row.get("currency", ""),
                }
            )
        return payload_rows

    def _slugify_name(self, raw_name: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", raw_name.strip().lower()).strip("-")
        return slug or "simulation"

    def _display_name_from_file(self, file_path: Path) -> str:
        stem = file_path.stem
        name_part = stem.split("__", 1)[0]
        return name_part.replace("-", " ").strip() or "simulation"