from __future__ import annotations
import io
import re
import pandas as pd
from app.models import BOMRow

PART_NUMBER_ALIASES = {
    "part number", "partnumber", "part#", "p/n", "mpn",
    "manufacturer part number", "mfr part #", "mfr. part #",
    "component", "part", "item", "part no", "part no.",
    "linh kiện", "mã linh kiện", "manufacturer pn",
}

QUANTITY_ALIASES = {
    "quantity", "qty", "count", "amount", "số lượng", "sl",
    "quantity (pcs)", "qty.", "pcs", "pieces",
}

_MPN_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9\-_./ ]{1,}$')


def _normalize(s: str) -> str:
    return s.strip().lower()


def _qty_score(series: pd.Series) -> float:
    """Score 0–1: how likely this column contains quantities (positive integers)."""
    vals = series.dropna().astype(str).str.strip()
    vals = vals[vals.str.lower() != "nan"]
    if vals.empty:
        return 0.0
    hits = 0
    for v in vals:
        try:
            n = float(v.replace(",", ""))
            if n == int(n) and 1 <= n <= 100_000:
                hits += 1
        except ValueError:
            pass
    return hits / len(vals)


def _part_score(series: pd.Series) -> float:
    """Score 0–1: how likely this column contains part numbers (alphanumeric identifiers)."""
    vals = series.dropna().astype(str).str.strip()
    vals = vals[vals.str.lower() != "nan"]
    if vals.empty:
        return 0.0
    hits = sum(1 for v in vals if _MPN_PATTERN.match(v) and not v.replace(".", "").isdigit())
    return hits / len(vals)


def detect_columns(headers: list[str], df: pd.DataFrame | None = None) -> tuple[str | None, str | None]:
    part_col: str | None = None
    qty_col: str | None = None

    # Pass 1: exact alias match — headers already normalized to lowercase in _read_df
    for h in headers:
        if h in PART_NUMBER_ALIASES and part_col is None:
            part_col = h
        if h in QUANTITY_ALIASES and qty_col is None:
            qty_col = h

    if part_col and qty_col:
        return part_col, qty_col

    # Pass 2: heuristic — score every column by its actual data
    if df is None:
        return part_col, qty_col

    qty_scores = {h: _qty_score(df[h]) for h in headers}
    part_scores = {h: _part_score(df[h]) for h in headers}

    if qty_col is None:
        best_qty = max(qty_scores, key=qty_scores.get)  # type: ignore[arg-type]
        if qty_scores[best_qty] >= 0.6:
            qty_col = best_qty

    if part_col is None:
        exclude = {qty_col} if qty_col else set()
        candidates = {h: part_scores[h] for h in headers if h not in exclude}
        if candidates:
            best_part = max(candidates, key=candidates.get)  # type: ignore[arg-type]
            if part_scores[best_part] >= 0.5:
                part_col = best_part

    return part_col, qty_col


_MAX_HEADER_SCAN = 15
_UNNAMED_RE = re.compile(r'^unnamed:\s*\d+$')


def _mostly_unnamed(headers: list[str]) -> bool:
    """True when most columns are pandas auto-generated names (title/merged row)."""
    unnamed = sum(1 for h in headers if _UNNAMED_RE.match(str(h)))
    return unnamed > len(headers) / 2


def _read_df(file_bytes: bytes, filename: str, header_row: int) -> pd.DataFrame:
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, header=header_row)
    else:
        df = pd.read_excel(io.BytesIO(file_bytes), dtype=str, header=header_row)
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df.dropna(how="all").reset_index(drop=True)


def parse_bom(file_bytes: bytes, filename: str) -> tuple[list[str], pd.DataFrame]:
    """Try each of the first _MAX_HEADER_SCAN rows as the header until both
    Part Number and Quantity columns can be detected."""
    last_df: pd.DataFrame | None = None

    for row_idx in range(_MAX_HEADER_SCAN):
        try:
            df = _read_df(file_bytes, filename, row_idx)
        except Exception:
            continue

        if df.empty:
            continue

        last_df = df
        columns = list(df.columns)
        # Skip heuristic when all column names are auto-generated (title/merged row).
        # Alias match is always attempted; heuristic only runs on real header rows.
        df_for_heuristic = None if _mostly_unnamed(columns) else df
        part_col, qty_col = detect_columns(columns, df_for_heuristic)
        if part_col and qty_col:
            return columns, df

    # Nothing matched — return row 0 so the caller can produce a useful error
    if last_df is None:
        raise ValueError("File is empty or could not be read.")
    df = _read_df(file_bytes, filename, 0)
    df.columns = [str(c) for c in df.columns]
    return list(df.columns), df.dropna(how="all").reset_index(drop=True)


def build_bom_rows(df: pd.DataFrame, part_col: str, qty_col: str) -> list[BOMRow]:
    rows = []
    for _, row in df.iterrows():
        mpn = str(row.get(part_col, "")).strip()
        qty_raw = str(row.get(qty_col, "0")).strip()
        if not mpn or mpn.lower() in ("nan", "none", ""):
            rows.append(BOMRow(original=row.to_dict(), part_number="", quantity=0, no_part_number=True))
            continue
        try:
            qty = int(float(qty_raw))
        except (ValueError, TypeError):
            qty = 1
        if qty <= 0:
            qty = 1
        rows.append(BOMRow(original=row.to_dict(), part_number=mpn, quantity=qty))
    return rows
