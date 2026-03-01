from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class NormalizedTransaction:
    timestamp: datetime
    name: str
    isin: str
    quantity: Decimal
    price_per_share: Decimal
    commissions: Decimal
    total_amount: Decimal
    broker: str
    currency: str = "EUR"
    transaction_type: str | None = None
    taxes: Decimal | None = None
    fees_other: Decimal | None = None
    fx_rate: Decimal | None = None
    source_row: int | None = None
    source_id: str | None = None


@dataclass(slots=True)
class OpenLot:
    timestamp: datetime
    isin: str
    name: str
    quantity_total: Decimal
    quantity_remaining: Decimal
    unit_cost: Decimal
    source_transaction: NormalizedTransaction


@dataclass(frozen=True, slots=True)
class FifoMatch:
    isin: str
    name: str
    quantity: Decimal
    buy_timestamp: datetime
    sell_timestamp: datetime
    buy_unit_cost: Decimal
    sell_unit_net: Decimal
    cost_basis: Decimal
    proceeds: Decimal
    realized_gain: Decimal
    buy_broker: str = "Unknown"


@dataclass(frozen=True, slots=True)
class RealizedSaleReport:
    isin: str
    name: str
    sell_transaction: NormalizedTransaction
    matches: list[FifoMatch]
    total_quantity: Decimal
    total_cost_basis: Decimal
    total_proceeds: Decimal
    total_realized_gain: Decimal


@dataclass(frozen=True, slots=True)
class AssetFifoReport:
    isin: str
    name: str
    realized_sales: list[RealizedSaleReport]
    open_lots: list[OpenLot]
    realized_gain_total: Decimal
    open_quantity_total: Decimal
    open_cost_total: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioFifoReport:
    generated_at: datetime
    assets: list[AssetFifoReport]
    realized_sales: list[RealizedSaleReport]
    total_realized_gain: Decimal
    total_cost_basis: Decimal
    total_proceeds: Decimal
