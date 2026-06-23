from __future__ import annotations
import time
import httpx

_cached_rate: float = 0.0
_cached_at: float = 0.0
_TTL = 3600.0  # 1 hour


async def get_usd_to_vnd() -> float:
    global _cached_rate, _cached_at
    if _cached_rate and time.time() - _cached_at < _TTL:
        return _cached_rate
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://api.exchangerate-api.com/v4/latest/USD")
            resp.raise_for_status()
            rate = float(resp.json()["rates"]["VND"])
            _cached_rate = rate
            _cached_at = time.time()
            return rate
    except Exception:
        # Fallback to approximate rate if API is unavailable
        return _cached_rate if _cached_rate else 25000.0
