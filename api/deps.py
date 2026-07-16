"""Thread-local DetectionEngine instances (read-only, thread-safe).

FastAPI runs sync endpoints in a threadpool; each thread gets its own engine +
SQLite connection. sqlite3's default check_same_thread=True is satisfied because a
connection is only ever touched on the thread that created it. This avoids a
global Lock that would serialize — and stall on the Open Food Facts network calls
inside scan_barcode. Engine construction is <10ms.
"""
from __future__ import annotations

import threading

from data.datastore import create_datastore
from detect.engine import DetectionEngine

from api.config import DB_PATH, DB_READ_ONLY

_tls = threading.local()


def get_engine() -> DetectionEngine:
    eng: DetectionEngine | None = getattr(_tls, "engine", None)
    if eng is None:
        store = create_datastore(db_path=DB_PATH, read_only=DB_READ_ONLY)
        eng = DetectionEngine.from_datastore(store)
        _tls.engine = eng
    return eng
