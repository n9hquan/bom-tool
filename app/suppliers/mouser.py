from __future__ import annotations
import asyncio
import httpx
from typing import Optional
from app.config import settings
from app.models import SupplierResult
from app.suppliers.base import SupplierClient, effective_price

_URL = "https://api.mouser.com/api/v1/search/partnumber"
_TIMEOUT = 15.0
_MAX_RETRIES = 2
_RATE_SLEEP = 2.0  # 30 req/min limit → 1 req/2s; serial requests stay ~20 req/min

# Serial requests: semaphore(1) ensures we never exceed rate limit
_mouser_sem = asyncio.Semaphore(1)


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
        async with _mouser_sem:
            for attempt in range(_MAX_RETRIES):
                try:
                    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                        resp = await client.post(
                            _URL,
                            params={"apiKey": settings.mouser_api_key},
                            json=payload,
                        )
                    await asyncio.sleep(_RATE_SLEEP)  # always sleep after HTTP call
                except Exception:
                    await asyncio.sleep(_RATE_SLEEP)
                    if attempt < _MAX_RETRIES - 1:
                        continue
                    return None

                if resp.status_code == 403:
                    return None  # daily quota exceeded — no point retrying
                if resp.status_code == 429:
                    if attempt < _MAX_RETRIES - 1:
                        continue
                    return None
                try:
                    resp.raise_for_status()
                    data = resp.json()
                except Exception:
                    if attempt < _MAX_RETRIES - 1:
                        continue
                    return None

                if data.get("Errors"):
                    return None

                parts = (data.get("SearchResults") or {}).get("Parts") or []
                if not parts:
                    return None

                price_breaks_raw = parts[0].get("PriceBreaks") or []
                if not price_breaks_raw:
                    return None

                breaks: list[tuple[int, float]] = []
                for pb in price_breaks_raw:
                    try:
                        min_qty = int(pb["Quantity"])
                        price = float(
                            str(pb["Price"]).replace(",", "").replace("$", "").strip()
                        )
                        breaks.append((min_qty, price))
                    except (KeyError, ValueError, TypeError):
                        continue

                if not breaks:
                    return None

                unit_price = effective_price(breaks, qty)
                return SupplierResult(
                    supplier="Mouser", unit_price_usd=unit_price, qty_break=qty
                )

        return None
