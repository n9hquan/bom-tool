from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
from app.models import SupplierResult


def effective_price(breaks: list[tuple[int, float]], qty: int) -> float:
    """Return unit price after applying quantity break for the given qty."""
    best = breaks[0][1]
    for min_qty, price in sorted(breaks, key=lambda x: x[0]):
        if qty >= min_qty:
            best = price
    return best


class SupplierClient(ABC):
    @abstractmethod
    async def lookup(self, mpn: str, qty: int) -> Optional[SupplierResult]:
        ...
