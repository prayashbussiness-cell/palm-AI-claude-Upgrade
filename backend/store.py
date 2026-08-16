"""
store.py

Minimal persistence layer for report records (one per /analyze submission).

Each record tracks the generated report + PDF for a report_id, and whether
the ₹9 unlock payment has been received for it. Backed by a single JSON
file on disk (reports/store.json) guarded by a thread lock — good enough
for a single-instance deployment (e.g. one Render web service). Swap this
out for a real database if you outgrow that.

NOTE: on free/ephemeral hosting tiers the filesystem can be wiped on
redeploy or restart, which would lose in-progress (unpaid) records. For
production durability, back this with Supabase/Postgres instead.
"""

import json
import os
import threading
import time
from typing import Any, Dict, Optional

BASE_DIR = os.path.dirname(__file__)
STORE_PATH = os.path.join(BASE_DIR, "reports", "store.json")

_lock = threading.Lock()


def _read_all() -> Dict[str, Any]:
    if not os.path.exists(STORE_PATH):
        return {}
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_all(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    tmp_path = STORE_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp_path, STORE_PATH)


def create_report(report_id: str, record: Dict[str, Any]) -> None:
    record = dict(record)
    record["report_id"] = report_id
    record.setdefault("paid", False)
    record.setdefault("created_at", time.time())
    with _lock:
        data = _read_all()
        data[report_id] = record
        _write_all(data)


def get_report(report_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        data = _read_all()
        return data.get(report_id)


def mark_paid(report_id: str, payment_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with _lock:
        data = _read_all()
        record = data.get(report_id)
        if record is None:
            return None
        record["paid"] = True
        record["paid_at"] = time.time()
        if payment_id:
            record["razorpay_payment_id"] = payment_id
        data[report_id] = record
        _write_all(data)
        return record


def find_by_reference(reference_id: str) -> Optional[Dict[str, Any]]:
    """Look up a report by report_id (used as the Razorpay reference_id)."""
    return get_report(reference_id)
