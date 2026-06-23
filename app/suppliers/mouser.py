from __future__ import annotations
import asyncio
import httpx
from typing import Optional
from app.config import settings
from app.models import SupplierResult
from app.suppliers.base import SupplierClient, effective_price

_URL = "https://api.mouser.com/api/v1/search/partnumber"
_TIMEOUT = 15.0
_MAX_RETRIES = 3
_RETRY_DELAYS = [1.0, 2.0, 4.0]

# Mouser free API triggers 429 on bursts — force serial requests with a throttle delay
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
            await asyncio.sleep(0.4)  # throttle: max ~2 req/s to Mouser
            for attempt in range(_MAX_RETRIES):
                try:
                    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                        resp = await client.post(
                            _URL,
                            params={"apiKey": settings.mouser_api_key},
                            json=payload,
                        )
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

                # Mouser sometimes returns 200 with Errors list instead of Parts
                errors = data.get("Errors") or []
                if errors:
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
                        price = float(str(pb["Price"]).replace(",", "").replace("$", "").strip())
                        breaks.append((min_qty, price))
                    except (KeyError, ValueError, TypeError):
                        continue

                if not breaks:
                    return None

                unit_price = effective_price(breaks, qty)
                return SupplierResult(supplier="Mouser", unit_price_usd=unit_price, qty_break=qty)

        return None
