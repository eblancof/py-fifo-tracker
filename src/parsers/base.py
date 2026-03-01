from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.models import NormalizedTransaction


class BrokerParser(ABC):
    @abstractmethod
    def parse_file(self, file_path: str | Path) -> list[NormalizedTransaction]:
        raise NotImplementedError
