"""Provider interface. Swap data sources by writing another class with the same methods."""
from __future__ import annotations
from abc import ABC, abstractmethod

from ..models import ChainSnapshot


class ProviderError(Exception):
    """kind: auth | plan | rate_limit | network | schema | not_found | server"""

    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind, self.status = kind, status


class OptionsProvider(ABC):
    name = "provider"

    @abstractmethod
    def fetch_chain(self, underlying: str, *, max_dte: int, strike_window: float) -> ChainSnapshot:
        """Return a normalized chain. Raise ProviderError on failure."""
