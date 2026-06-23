from __future__ import annotations
import asyncio
import httpx
from typing import Optional
from app.config import settings
from app.models import SupplierResult
from app.suppliers.base import SupplierClient, effective_price

_URL = "https://api.mouser.com/api/v1/search/partnumber"
_TIMEOUT = 15.0
_MAX_RETRIES = 4
_RETRY_DELAYS = [0.5, 1.0, 2.0, 3.0]

# Cap at 3 concurrent; 0.2s spacing before each slot to soften bursts
_mouser_sem = asyncio.Semaphore(3)


class MouserClient(SupplierClient):
    async def lookup(self, mpn: str, qty: int) -> Optional[SupplierResult]:
        if not settings.mouser_api_key:
            return None
        payload = {
            "SearchByPartRequest": {
                "mouserPartNumber": mpn,
                "partSearchOptions": "",
            }
        }
        params = {"apiKey": settings.mouser_api_key}

        async with _mouser_sem:
            await asyncio.sleep(0.2)  # soft burst spacing inside semaphore slot
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                for attempt in range(_MAX_RETRIES):
                    try:
                        resp = await client.post(_URL, params=params, json=payload)
                        if resp.status_code == 429:
                            if attempt < _MAX_RETRIES - 1:
                                await asyncio.sleep(_RETRY_DELAYS[attempt])
                                continue
                            return None
                        resp.raise_for_status()
                        data = resp.json()
                    except Exception:
                        if attempt < _MAX_RETRIES - 1:
                            await asyncio.sleep(_RETRY_DELAYS[attempt])
                            continue
                        return None

                    # JSON-level errors can be transient (rate-limit variants) — retry
                    if data.get("Errors"):
                        if attempt < _MAX_RETRIES - 1:
                            await asyncio.sleep(_RETRY_DELAYS[attempt])
                            continue
                        return None

                    parts = (data.get("SearchResults") or {}).get("Parts") or []
                    if not parts:
                        # Empty result can be a transient API glitch — retry
                        if attempt < _MAX_RETRIES - 1:
                            await asyncio.sleep(_RETRY_DELAYS[attempt])
                            continue
                        return None

                    price_breaks_raw = parts[0].get("PriceBreaks") or []
                    if not price_breaks_raw:
                        # Part found but no pricing yet — retry once
                        if attempt < _MAX_RETRIES - 1:
                            await asyncio.sleep(_RETRY_DELAYS[attempt])
                            continue
                        return None

                    breaks: list[tuple[int, float]] = []
                    for pb in price_breaks_raw:
                        try:
                            min_qty = int(pb["Quantity"])
                            price = float(
                                str(pb["Price"]).replace(",", "").replace("$", "").strip()
                            )
                            if price > 0:
                                breaks.append((min_qty, price))
                        except (KeyError, ValueError, TypeError):
                            continue

                    if not breaks:
                        if attempt < _MAX_RETRIES - 1:
                            await asyncio.sleep(_RETRY_DELAYS[attempt])
                            continue
                        return None

                    unit_price = effective_price(breaks, qty)
                    return SupplierResult(
                        supplier="Mouser", unit_price_usd=unit_price, qty_break=qty
                    )

        return None
