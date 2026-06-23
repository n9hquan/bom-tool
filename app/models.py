from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class SupplierResult:
    supplier: str
    unit_price_usd: float
    qty_break: int


@dataclass
class BOMRow:
    original: dict
    part_number: str
    quantity: int
    mouser: Optional[SupplierResult] = None
    digikey: Optional[SupplierResult] = None
    lcsc: Optional[SupplierResult] = None
    best: Optional[SupplierResult] = None
    not_found: bool = False
    no_part_number: bool = False


@dataclass
class Job:
    job_id: str
    status: JobStatus = JobStatus.PENDING
    progress: int = 0
    total: int = 0
    columns: list[str] = field(default_factory=list)
    part_col: str = ""
    qty_col: str = ""
    rows: list[BOMRow] = field(default_factory=list)
    result_path: str = ""
    error: str = ""
    usd_to_vnd: float = 0.0
    not_found_parts: list[str] = field(default_factory=list)
