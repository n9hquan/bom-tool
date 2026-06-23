from __future__ import annotations
import os
from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.bom_parser import detect_columns, parse_bom, build_bom_rows
from app.job_store import create_job, get_job, delete_old_jobs
from app.models import JobStatus
from app.price_engine import process_job

app = FastAPI(title="BOM Price Tool")

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/upload")
async def upload_bom(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    filename = file.filename or "upload"
    ext = filename.lower().split(".")[-1]
    if ext not in ("csv", "xlsx", "xls"):
        raise HTTPException(400, "Only CSV and Excel files are supported.")

    content = await file.read()
    try:
        columns, df = parse_bom(content, filename)
    except Exception as exc:
        raise HTTPException(400, f"Could not parse file: {exc}")

    if len(df) == 0:
        raise HTTPException(400, "The file appears to be empty.")

    part_col, qty_col = detect_columns(columns, df)

    if not part_col or not qty_col:
        missing = []
        if not part_col:
            missing.append("Part Number")
        if not qty_col:
            missing.append("Quantity")
        raise HTTPException(
            422,
            f"Could not detect column(s): {', '.join(missing)}. "
            "Please rename your columns to something like 'Part Number' and 'Quantity'."
        )

    rows = build_bom_rows(df, part_col, qty_col)
    if not rows:
        raise HTTPException(400, "No valid rows found after parsing.")

    delete_old_jobs()
    job = create_job()
    job.columns = columns
    job.part_col = part_col
    job.qty_col = qty_col
    job.rows = rows
    job.total = len(rows)

    background_tasks.add_task(process_job, job)

    return JSONResponse({
        "job_id": job.job_id,
        "total": job.total,
        "detected_part_col": part_col,
        "detected_qty_col": qty_col,
    })


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")

    response: dict = {
        "job_id": job_id,
        "status": job.status,
        "progress": job.progress,
        "total": job.total,
    }

    if job.status == JobStatus.DONE:
        response["usd_to_vnd"] = job.usd_to_vnd
        response["not_found_parts"] = [p for p in job.not_found_parts if p]

        preview = []
        for row in job.rows[:20]:
            if row.no_part_number:
                preview.append({
                    "part_number": "",
                    "quantity": "",
                    "best_supplier": "No Part Number",
                    "best_unit_price_usd": "N/A",
                    "best_unit_price_vnd": "N/A",
                    "total_line_usd": "N/A",
                    "mouser": "N/A",
                    "digikey": "N/A",
                    "lcsc": "N/A",
                    "no_part_number": True,
                })
                continue
            best = row.best
            preview.append({
                "part_number": row.part_number,
                "quantity": row.quantity,
                "best_supplier": best.supplier if best else "Not Found",
                "best_unit_price_usd": f"${best.unit_price_usd:.4f}" if best else "N/A",
                "best_unit_price_vnd": f"{best.unit_price_usd * job.usd_to_vnd:,.0f} ₫" if best else "N/A",
                "total_line_usd": f"${best.unit_price_usd * row.quantity:.4f}" if best else "N/A",
                "mouser": f"${row.mouser.unit_price_usd:.4f}" if row.mouser else "N/A",
                "digikey": f"${row.digikey.unit_price_usd:.4f}" if row.digikey else "N/A",
                "lcsc": f"${row.lcsc.unit_price_usd:.4f}" if row.lcsc else "N/A",
                "no_part_number": False,
            })
        response["preview"] = preview

        total_usd = sum(
            r.best.unit_price_usd * r.quantity for r in job.rows if r.best
        )
        response["grand_total_usd"] = f"${total_usd:.2f}"
        response["grand_total_vnd"] = f"{total_usd * job.usd_to_vnd:,.0f} ₫"

    elif job.status == JobStatus.ERROR:
        response["error"] = job.error

    return JSONResponse(response)


@app.get("/api/download/{job_id}")
async def download_result(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    if job.status != JobStatus.DONE:
        raise HTTPException(400, "Job not complete yet.")
    if not job.result_path or not os.path.exists(job.result_path):
        raise HTTPException(500, "Result file not found.")
    return FileResponse(
        job.result_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="BOM_Pricing_Result.xlsx",
    )


# Serve frontend — must be last to avoid catching API routes
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
