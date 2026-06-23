from __future__ import annotations
import httpx
from typing import Optional
from app.models import SupplierResult
from app.suppliers.base import SupplierClient, effective_price

_SEARCH_URL = "https://wmsc.lcsc.com/ftps/wm/search/v3/global"
_HOMEPAGE = "https://www.lcsc.com/"
_TIMEOUT = 20.0

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.lcsc.com",
    "Referer": "https://www.lcsc.com/",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


class LCSCClient(SupplierClient):
    async def lookup(self, mpn: str, qty: int) -> Optional[SupplierResult]:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
                # Fetch homepage to obtain session cookie
                try:
                    await client.get(_HOMEPAGE, headers={
                        "User-Agent": _HEADERS["User-Agent"],
                        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    })
                except Exception:
                    pass

                payload = {
                    "keyword": mpn,
                    "secondKeyword": "",
                    "brandIdList": [],
                    "catalogIdList": [],
                    "isStock": False,
                    "isAsianBrand": False,
                    "isDeals": False,
                    "isEnvironment": False,
                }
                resp = await client.post(_SEARCH_URL, json=payload, headers=_HEADERS)
                resp.raise_for_status()
                data = resp.json()

            if data.get("code") != 200:
                return None

            result = data.get("result") or {}
            # Products are in exactMatchResult when LCSC finds an exact MPN match
            candidates = result.get("exactMatchResult") or []
            if not candidates:
                return None

            # Prefer exact manufacturer model match
            mpn_lower = mpn.lower()
            target = None
            for p in candidates:
                if str(p.get("productModel") or "").lower() == mpn_lower:
                    target = p
                    break
            if target is None:
                target = candidates[0]

            price_list = target.get("productPriceList") or []
            breaks: list[tuple[int, float]] = []
            for pb in price_list:
                try:
                    ladder = int(pb.get("ladder") or 1)
                    price = float(pb.get("usdPrice") or 0)
                    if price > 0:
                        breaks.append((ladder, price))
                except (ValueError, TypeError):
                    continue

            if not breaks:
                return None

            unit_price = effective_price(breaks, qty)
            return SupplierResult(supplier="LCSC", unit_price_usd=unit_price, qty_break=qty)

        except Exception:
            return None
