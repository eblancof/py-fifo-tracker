from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


@lru_cache(maxsize=None)
def load_broker_schema(broker_name: str) -> dict[str, Any]:
    schema_path = SCHEMA_DIR / f"{broker_name}.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Broker schema not found: {schema_path}")

    with schema_path.open("r", encoding="utf-8") as schema_file:
        return json.load(schema_file)
