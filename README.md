# BOM Price Tool

An internal web tool for looking up component prices from multiple suppliers. Upload a BOM (Bill of Materials) as a CSV or Excel file and get back the best available price from Mouser, DigiKey, and LCSC — exported as a formatted Excel report with USD and VND totals.

## Features

- **Multi-supplier pricing**: Queries Mouser, DigiKey, and LCSC in parallel for each component
- **Best price selection**: Automatically picks the lowest unit price across all suppliers
- **Price breaks**: Respects quantity-based price tiers from each supplier
- **Currency conversion**: Converts USD to VND using live exchange rates (cached 1 hour)
- **Smart column detection**: Auto-detects Part Number and Quantity columns by alias matching and heuristics — no manual mapping needed
- **Handles incomplete BOMs**: Rows without a part number are preserved in output (gray rows) rather than dropped
- **Excel export**: Full results with color-coded rows (green = multiple suppliers, yellow = single supplier, red = not found, gray = no part number)

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, uvicorn |
| HTTP client | httpx (async) |
| BOM parsing | pandas, openpyxl |
| Frontend | Vanilla HTML / CSS / JS (no framework) |
| Deployment | Render.com (free tier) |

## Supported File Formats

`.csv`, `.xlsx`, `.xls`

The tool scans the first 15 rows to find the header. Columns are detected automatically — common aliases like `MPN`, `Part Number`, `Qty`, `Số lượng`, etc. are recognized out of the box.

## API Keys Required

| Variable | Where to get it |
|---|---|
| `MOUSER_API_KEY` | [mouser.com/api](https://www.mouser.com/api-hub/) — free, 1,000 calls/day |
| `DIGIKEY_CLIENT_ID` | [developer.digikey.com](https://developer.digikey.com/) — free sandbox |
| `DIGIKEY_CLIENT_SECRET` | Same as above |

> **Note:** LCSC does not require an API key.

## Local Setup

```bash
# 1. Clone the repo
git clone https://github.com/n9hquan/bom-tool.git
cd bom-tool

# 2. Create your .env file
cp .env.example .env
# Edit .env and fill in your API keys

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the dev server
python -m uvicorn app.main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

## Deploy to Render.com

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → **New → Web Service**
3. Connect your GitHub repo — Render will auto-detect `render.yaml`
4. Add the three environment variables (`MOUSER_API_KEY`, `DIGIKEY_CLIENT_ID`, `DIGIKEY_CLIENT_SECRET`) in the **Environment** tab
5. Click **Deploy**

The free tier sleeps after 15 minutes of inactivity (cold start ~30s).

## Output Excel Format

The exported file keeps all original BOM columns and appends:

| Column | Description |
|---|---|
| Best Supplier | Supplier with the lowest unit price |
| Best Unit Price (USD) | Lowest unit price in USD |
| Best Unit Price (VND) | Converted at live exchange rate |
| Total Line (USD) | Unit price × quantity |
| Total Line (VND) | Converted total |
| Mouser Price (USD) | Mouser unit price (or N/A) |
| DigiKey Price (USD) | DigiKey unit price (or N/A) |
| LCSC Price (USD) | LCSC unit price (or N/A) |

A **Grand Total** row is added at the bottom. The exchange rate used is noted in a cell comment.

## Rate Limits

| Supplier | Limit |
|---|---|
| Mouser | 30 calls/min, 1,000 calls/day |
| DigiKey | Generous sandbox limits |
| LCSC | No published limit |

The tool serializes Mouser requests (1 at a time, 2s apart) to stay within the 30 req/min cap. For a 100-part BOM, expect Mouser lookups to take ~3-4 minutes; DigiKey and LCSC run in parallel and finish much faster.

## Project Structure

```
app/
  main.py            # FastAPI routes
  config.py          # Environment variable loading
  models.py          # Dataclasses (Job, BOMRow, SupplierResult)
  job_store.py       # In-memory job state (auto-cleans after 50 jobs)
  bom_parser.py      # CSV/Excel parsing + column detection
  price_engine.py    # Parallel supplier orchestration
  suppliers/
    mouser.py        # Mouser REST API
    digikey.py       # DigiKey OAuth2 + v4 search API
    lcsc.py          # LCSC search API
  utils/
    currency.py      # USD/VND exchange rate (1-hour cache)
    excel_writer.py  # Excel report generation
static/
  index.html
  style.css
  app.js
```

## License

Internal use only. Not licensed for public distribution.
