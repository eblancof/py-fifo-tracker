from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Iterable
from unicodedata import normalize


def normalize_text(value: str) -> str:
    normalized = normalize("NFKD", value or "")
    ascii_only = "".join(char for char in normalized if ord(char) < 128)
    return " ".join(ascii_only.strip().lower().split())


def parse_decimal(value: str | None, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default

    text = value.strip().replace('"', "")
    if not text:
        return default

    text = text.replace(" ", "")
    has_comma = "," in text
    has_dot = "." in text

    if has_comma and has_dot:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_comma:
        text = text.replace(",", ".")

    return Decimal(text)


def parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.strip())


def parse_degiro_datetime(date_value: str, time_value: str) -> datetime:
    return datetime.strptime(
        f"{date_value.strip()} {time_value.strip()}", "%d-%m-%Y %H:%M"
    )


def resolve_header_map(
    headers: list[str],
    header_aliases: dict[str, list[str]],
    required_fields: Iterable[str],
    broker_label: str,
) -> dict[str, str]:
    normalized_to_original = {
        normalize_text(header): header for header in headers if header is not None
    }

    resolved: dict[str, str] = {}
    required_set = set(required_fields)

    for canonical_field, aliases in header_aliases.items():
        for alias in aliases:
            original_header = normalized_to_original.get(normalize_text(alias))
            if original_header:
                resolved[canonical_field] = original_header
                break

        if canonical_field in required_set and canonical_field not in resolved:
            raise ValueError(f"Missing required {broker_label} column for '{canonical_field}'")

    return resolved


def resolve_transaction_side(
    raw_type: str,
    transaction_type_aliases: dict[str, list[str]],
) -> str | None:
    normalized = normalize_text(raw_type)
    for side, aliases in transaction_type_aliases.items():
        if normalized in {normalize_text(alias) for alias in aliases}:
            return side
    return None
