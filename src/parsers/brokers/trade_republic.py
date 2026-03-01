from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from src.models import NormalizedTransaction
from src.parsers.base import BrokerParser
from src.parsers.common import (
    parse_decimal,
    parse_iso_datetime,
    resolve_header_map,
    resolve_transaction_side,
)
from src.parsers.config import load_broker_schema


class TradeRepublicParser(BrokerParser):
    SCHEMA = load_broker_schema("trade_republic")
    DELIMITER = SCHEMA["delimiter"]
    HEADER_ALIASES = SCHEMA["header_aliases"]
    REQUIRED_FIELDS = SCHEMA["required_fields"]
    TRANSACTION_TYPE_ALIASES = SCHEMA["transaction_type_aliases"]

    def parse_file(self, file_path: str | Path) -> list[NormalizedTransaction]:
        path = Path(file_path)
        with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file, delimiter=self.DELIMITER)
            header_map = self._resolve_header_map(reader.fieldnames or [])
            transactions: list[NormalizedTransaction] = []

            for row_number, row in enumerate(reader, start=2):
                side = resolve_transaction_side(
                    row.get(header_map["type"], ""), self.TRANSACTION_TYPE_ALIASES
                )
                if side is None:
                    continue

                isin = (row.get(header_map["isin"], "") or "").strip()
                quantity = parse_decimal(row.get(header_map["quantity"]), Decimal("0"))
                if not isin or quantity == 0:
                    continue

                total_amount = parse_decimal(row.get(header_map["total_amount"]), Decimal("0"))
                commissions = parse_decimal(row.get(header_map.get("commissions", "")), Decimal("0"))
                taxes = parse_decimal(row.get(header_map.get("taxes", "")), Decimal("0"))

                gross_trade_amount = total_amount - commissions
                price_per_share = abs(gross_trade_amount / quantity)

                transactions.append(
                    NormalizedTransaction(
                        timestamp=parse_iso_datetime(row.get(header_map["datetime"], "")),
                        name=(row.get(header_map["name"], "") or "").strip(),
                        isin=isin,
                        quantity=quantity,
                        price_per_share=price_per_share,
                        commissions=commissions,
                        total_amount=total_amount,
                        broker="trade_republic",
                        currency="EUR",
                        transaction_type=side,
                        taxes=taxes,
                        source_row=row_number,
                    )
                )

        return transactions

    def _resolve_header_map(self, headers: list[str]) -> dict[str, str]:
        return resolve_header_map(
            headers=headers,
            header_aliases=self.HEADER_ALIASES,
            required_fields=self.REQUIRED_FIELDS,
            broker_label="Trade Republic",
        )
