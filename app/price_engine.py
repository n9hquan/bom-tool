from __future__ import annotations
import asyncio
from app.models import BOMRow, Job, JobStatus, SupplierResult
from app.suppliers.mouser import MouserClient
from app.suppliers.digikey import DigiKeyClient
from app.suppliers.lcsc import LCSCClient
from app.utils.currency import get_usd_to_vnd
from app.utils.excel_writer import write_excel

_mouser = MouserClient()
_digikey = DigiKeyClient()
_lcsc = LCSCClient()

_CONCURRENT_LIMIT = 5  # max parallel part lookups at once


async def _lookup_row(row: BOMRow, semaphore: asyncio.Semaphore) -> None:
    if row.no_part_number:
        return
    async with semaphore:
        mouser_res, digikey_res, lcsc_res = await asyncio.gather(
            _mouser.lookup(row.part_number, row.quantity),
            _digikey.lookup(row.part_number, row.quantity),
            _lcsc.lookup(row.part_number, row.quantity),
            return_exceptions=True,
        )

        row.mouser = mouser_res if isinstance(mouser_res, SupplierResult) else None
        row.digikey = digikey_res if isinstance(digikey_res, SupplierResult) else None
        row.lcsc = lcsc_res if isinstance(lcsc_res, SupplierResult) else None

        candidates = [r for r in [row.mouser, row.digikey, row.lcsc] if r is not None]
        if candidates:
            row.best = min(candidates, key=lambda r: r.unit_price_usd)
        else:
            row.not_found = True


async def process_job(job: Job) -> None:
    job.status = JobStatus.RUNNING
    job.progress = 0

    try:
        usd_to_vnd = await get_usd_to_vnd()
        job.usd_to_vnd = usd_to_vnd

        semaphore = asyncio.Semaphore(_CONCURRENT_LIMIT)
        total = len(job.rows)
        job.total = total
        done = 0

        tasks = []
        for row in job.rows:
            tasks.append(_lookup_row(row, semaphore))

        # Process with progress tracking
        for coro in asyncio.as_completed(tasks):
            await coro
            done += 1
            job.progress = int(done / total * 100)

        job.not_found_parts = [r.part_number for r in job.rows if r.not_found and not r.no_part_number]
        job.result_path = write_excel(job.rows, usd_to_vnd, job.job_id)
        job.status = JobStatus.DONE
        job.progress = 100

    except Exception as exc:
        job.status = JobStatus.ERROR
        job.error = str(exc)
