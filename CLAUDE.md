# BOM Price Tool

Internal web tool cho phép nhân viên upload BOM List (CSV/Excel) và tự động tra giá linh kiện trên Mouser, DigiKey, và LCSC. Kết quả xuất ra file Excel với giá rẻ nhất, nhà cung cấp tương ứng, và tổng chi phí theo USD và VND.

## Chạy local

```bash
# Tạo .env từ template (chỉ lần đầu)
cp .env.example .env   # rồi điền API keys vào .env

pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Truy cập: http://localhost:8000

## Cấu trúc thư mục

```
app/
  main.py            # FastAPI routes: POST /api/upload, GET /api/jobs/{id}, GET /api/download/{id}
  config.py          # Đọc env vars (MOUSER_API_KEY, DIGIKEY_CLIENT_ID, DIGIKEY_CLIENT_SECRET)
  models.py          # Dataclasses: Job, BOMRow, SupplierResult, JobStatus
  job_store.py       # In-memory dict lưu trạng thái job; tự dọn khi quá 50 jobs
  bom_parser.py      # Parse CSV/Excel + detect cột Part Number và Quantity
  price_engine.py    # Orchestrate query song song 3 supplier, pick giá rẻ nhất
  suppliers/
    base.py          # ABC SupplierClient + hàm effective_price() tính price break
    mouser.py        # Mouser REST API (POST, auth bằng apiKey query param)
    digikey.py       # DigiKey OAuth2 client_credentials + v4 search API
    lcsc.py          # LCSC unofficial API (wwwapi.lcsc.com)
  utils/
    currency.py      # Fetch tỷ giá USD/VND từ exchangerate-api.com, cache 1 giờ
    excel_writer.py  # Xuất .xlsx với openpyxl, lưu vào /tmp/{job_id}.xlsx
static/
  index.html / style.css / app.js   # Frontend thuần HTML/CSS/JS, không framework
```

## Flow xử lý

1. User upload file → `POST /api/upload`
2. `parse_bom()` thử lần lượt row 0–14 làm header cho đến khi detect được cả 2 cột
3. `detect_columns()` chạy 2 bước: khớp alias trước, rồi heuristic (score data thực tế) nếu alias không match
4. Job được tạo, `process_job()` chạy trong `BackgroundTasks`
5. Frontend poll `GET /api/jobs/{id}` mỗi 2 giây để cập nhật progress
6. Mỗi BOM row: `asyncio.gather()` gọi cả 3 supplier song song (semaphore giới hạn 5 concurrent)
7. Best = `min(candidates, key=unit_price_usd)` — supplier và giá luôn từ cùng 1 object
8. Kết quả ghi vào `/tmp/{job_id}.xlsx`, user tải qua `GET /api/download/{id}`

## Detect cột (bom_parser.py)

**Pass 1 — alias match** (case-insensitive): so sánh header với danh sách tên phổ biến như `mpn`, `qty`, `part number`, `số lượng`, v.v.

**Pass 2 — heuristic** (khi alias không match):
- Cột Quantity: ≥60% giá trị là số nguyên dương trong khoảng 1–100 000
- Cột Part Number: ≥50% giá trị là chuỗi alphanumeric không phải số thuần

Để thêm alias mới, chỉnh `PART_NUMBER_ALIASES` hoặc `QUANTITY_ALIASES` trong `bom_parser.py`.

## Price break

```python
# suppliers/base.py
def effective_price(breaks: list[tuple[int, float]], qty: int) -> float:
    best = breaks[0][1]
    for min_qty, price in sorted(breaks, key=lambda x: x[0]):
        if qty >= min_qty:
            best = price
    return best
```

Mỗi supplier trả về list `(min_qty, unit_price)`. Hàm này chọn mức giá áp dụng cho số lượng đặt.

## Supplier API

| Supplier | Auth | Endpoint chính |
|---|---|---|
| Mouser | `apiKey` query param | `POST api.mouser.com/api/v1/search/partnumber` |
| DigiKey | OAuth2 client_credentials, token cache in-memory, refresh on 401 | `POST api.digikey.com/products/v4/search/keyword` |
| LCSC | Homepage cookie + browser headers | `POST wmsc.lcsc.com/ftps/wm/search/v3/global` (JSON body) |

Tất cả supplier client đều trả về `SupplierResult | None` — lỗi network hoặc không tìm thấy đều trả `None` (không crash job).

## Output Excel

Giữ nguyên toàn bộ cột gốc của BOM, thêm vào cuối:
`Best Supplier`, `Best Unit Price (USD)`, `Best Unit Price (VND)`, `Total Line (USD)`, `Total Line (VND)`, `Mouser Price (USD)`, `DigiKey Price (USD)`, `LCSC Price (USD)`

Màu hàng: xanh = tìm thấy ở nhiều supplier, vàng = chỉ 1 supplier, đỏ = không tìm thấy.
Hàng cuối: Grand Total. Cell note: tỷ giá tại thời điểm tra.

## Deploy lên Render.com

```bash
git init && git add . && git commit -m "init"
# Push lên GitHub repo (private)
```

Trên Render: New → Web Service → chọn repo → Runtime: Docker → thêm 3 env var:
`MOUSER_API_KEY`, `DIGIKEY_CLIENT_ID`, `DIGIKEY_CLIENT_SECRET`

File `render.yaml` đã có sẵn cấu hình. Free tier sleep sau 15 phút không dùng.

## Biến môi trường

```
MOUSER_API_KEY          # Mouser API key
DIGIKEY_CLIENT_ID       # DigiKey OAuth2 client ID
DIGIKEY_CLIENT_SECRET   # DigiKey OAuth2 client secret
```

Không commit file `.env`. File `.env.example` là template an toàn để commit.

## Quy tắc cứng

- **Chỉ 3 nhà cung cấp**: Mouser, DigiKey, LCSC. Không thêm nhà cung cấp khác (JLCPCB, Octopart, v.v.) dù API của LCSC tạm thời không hoạt động.

## Lưu ý kỹ thuật

- **Job store in-memory**: reset khi restart container. Chấp nhận được cho free tier (single instance). Tự dọn khi vượt 50 jobs (`job_store.delete_old_jobs()`).
- **LCSC**: Dùng `POST wmsc.lcsc.com/ftps/wm/search/v3/global` với JSON body `{keyword, secondKeyword, brandIdList, catalogIdList, isStock, ...}`. Fetch `https://www.lcsc.com/` trước để lấy cookie session. Products nằm trong `result.exactMatchResult[]` (không phải `productSearchResultVO`). Pricing: `exactMatchResult[0].productPriceList[].{ladder, usdPrice}`.
- **DigiKey API v4**: Field là `ManufacturerProductNumber` (không phải `ManufacturerPartNumber`). Pricing nằm trong `ProductVariations[].StandardPricing`, không phải top-level.
- **Concurrency**: `_CONCURRENT_LIMIT = 5` trong `price_engine.py` — tăng nếu cần nhanh hơn, giảm nếu bị rate limit.
- **Header scan**: `_MAX_HEADER_SCAN = 15` trong `bom_parser.py` — số dòng tối đa tìm header.
