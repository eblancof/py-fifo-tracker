from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from src.models import NormalizedTransaction
from src.parsers.base import BrokerParser
from src.parsers.common import parse_decimal, parse_degiro_datetime, resolve_header_map
from src.parsers.config import load_broker_schema


class DeGiroParser(BrokerParser):
    SCHEMA = load_broker_schema("degiro")
    DELIMITER = SCHEMA["delimiter"]
    HEADER_ALIASES = SCHEMA["header_aliases"]
    REQUIRED_FIELDS = SCHEMA["required_fields"]

    def parse_file(self, file_path: str | Path) -> list[NormalizedTransaction]:
        path = Path(file_path)
        with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file, delimiter=self.DELIMITER)
            header_map = self._resolve_header_map(reader.fieldnames or [])
            transactions: list[NormalizedTransaction] = []

            for row_number, row in enumerate(reader, start=2):
                isin = (row.get(header_map["isin"], "") or "").strip()
                name = (row.get(header_map["name"], "") or "").strip()
                quantity = parse_decimal(row.get(header_map["quantity"]), Decimal("0"))

                if not isin or not name or quantity == 0:
                    continue

                total_amount = parse_decimal(row.get(header_map["total_amount"]), Decimal("0"))
                broker_fee = parse_decimal(row.get(header_map["commissions"]), Decimal("0"))
                auto_fx_fee = parse_decimal(row.get(header_map.get("auto_fx_fee", "")), Decimal("0"))
                commissions = broker_fee + auto_fx_fee
                value_eur = parse_decimal(row.get(header_map["value_eur"]), Decimal("0"))
                fx_rate = parse_decimal(row.get(header_map.get("fx_rate", "")), Decimal("0"))

                gross_trade_amount = value_eur if value_eur != 0 else total_amount - commissions
                price_per_share = abs(gross_trade_amount / quantity)
                side = "buy" if total_amount < 0 else "sell"

                transactions.append(
                    NormalizedTransaction(
                        timestamp=parse_degiro_datetime(
                            row.get(header_map["date"], ""), row.get(header_map["time"], "")
                        ),
                        name=name,
                        isin=isin,
                        quantity=quantity,
                        price_per_share=price_per_share,
                        commissions=commissions,
                        total_amount=total_amount,
                        broker="degiro",
                        currency="EUR",
                        transaction_type=side,
                        fees_other=auto_fx_fee if auto_fx_fee != 0 else None,
                        fx_rate=fx_rate if fx_rate != 0 else None,
                        source_row=row_number,
                        source_id=(row.get(header_map.get("order_id", ""), "") or "").strip() or None,
                    )
                )

        return transactions

    def _resolve_header_map(self, headers: list[str]) -> dict[str, str]:
        return resolve_header_map(
            headers=headers,
            header_aliases=self.HEADER_ALIASES,
            required_fields=self.REQUIRED_FIELDS,
            broker_label="DEGIRO",
        )
