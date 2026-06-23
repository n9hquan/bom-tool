from __future__ import annotations
import asyncio
import time
import httpx
from typing import Optional
from app.config import settings
from app.models import SupplierResult
from app.suppliers.base import SupplierClient, effective_price

_TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
_SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"
_TIMEOUT = 15.0

_token: str = ""
_token_expires_at: float = 0.0
_lock = asyncio.Lock()


async def _get_token() -> str:
    global _token, _token_expires_at
    async with _lock:
        if _token and time.time() < _token_expires_at - 60:
            return _token
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.digikey_client_id,
                    "client_secret": settings.digikey_client_secret,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            _token = body["access_token"]
            _token_expires_at = time.time() + int(body.get("expires_in", 1800))
    return _token


class DigiKeyClient(SupplierClient):
    async def lookup(self, mpn: str, qty: int) -> Optional[SupplierResult]:
        if not settings.digikey_client_id or not settings.digikey_client_secret:
            return None
        try:
            token = await _get_token()
            return await self._search(token, mpn, qty)
        except Exception:
            return None

    async def _search(self, token: str, mpn: str, qty: int) -> Optional[SupplierResult]:
        headers = {
            "Authorization": f"Bearer {token}",
            "X-DIGIKEY-Client-Id": settings.digikey_client_id,
            "X-DIGIKEY-Locale-Site": "US",
            "X-DIGIKEY-Locale-Language": "en",
            "X-DIGIKEY-Locale-Currency": "USD",
        }
        payload = {"keywords": mpn, "limit": 10}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(_SEARCH_URL, json=payload, headers=headers)
            if resp.status_code == 401:
                global _token, _token_expires_at
                _token = ""
                _token_expires_at = 0.0
                return None
            resp.raise_for_status()
            data = resp.json()

        products = data.get("Products") or []
        if not products:
            return None

        # API v4 uses ManufacturerProductNumber (not ManufacturerPartNumber)
        mpn_lower = mpn.lower()
        target = None
        for p in products:
            if p.get("ManufacturerProductNumber", "").lower() == mpn_lower:
                target = p
                break
        if target is None:
            target = products[0]

        # Pricing lives in ProductVariations[].StandardPricing (not top-level)
        # Only consider variations where MinimumOrderQuantity <= qty (can actually order)
        best_price: Optional[float] = None
        variations = target.get("ProductVariations") or []
        for variation in variations:
            moq = variation.get("MinimumOrderQuantity") or 1
            if qty < moq:
                continue
            pricing = variation.get("StandardPricing") or []
            if not pricing:
                continue
            breaks: list[tuple[int, float]] = []
            for pb in pricing:
                try:
                    breaks.append((int(pb["BreakQuantity"]), float(pb["UnitPrice"])))
                except (KeyError, ValueError, TypeError):
                    continue
            if not breaks:
                continue
            price = effective_price(breaks, qty)
            if best_price is None or price < best_price:
                best_price = price

        # Fall back to top-level UnitPrice (qty=1 price) if no variation pricing
        if best_price is None:
            unit = target.get("UnitPrice")
            if unit:
                best_price = float(unit)

        if best_price is None:
            return None

        return SupplierResult(supplier="DigiKey", unit_price_usd=best_price, qty_break=qty)
