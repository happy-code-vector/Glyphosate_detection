"""Runtime configuration for the ResidueIQ API, read from environment.

All settings have local-dev defaults so the server runs out of the box against
the repo's data/residueiq.db. Production (Cloud Run) overrides via --set-env-vars.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# --- import bootstrap --------------------------------------------------------
# The detection engine uses repo-root-qualified imports (`data.*`, `detect.*`)
# plus a few legacy flat imports that need data/ on sys.path. Make both
# importable before anything imports the engine.
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
for _p in (str(REPO_ROOT), str(DATA_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# --- settings ----------------------------------------------------------------
DB_PATH: str = os.getenv("DB_PATH", str(DATA_DIR / "residueiq.db"))
# Read-only connection (file: URI, mode=ro). Off by default for local dev because
# a WAL-mode DB needs its -shm sidecar; CI checkpoints to DELETE journal before
# enabling this in production.
DB_READ_ONLY: bool = _env_bool("DB_READ_ONLY", False)

# Firebase App Check
FIREBASE_PROJECT_ID: str | None = os.getenv("FIREBASE_PROJECT_ID")
# When false, App Check verification is skipped (monitor/log mode). Flip to true
# once attestation traffic looks healthy in the Firebase console.
REQUIRE_APPCHECK: bool = _env_bool("REQUIRE_APPCHECK", False)

# GCS URI the container entrypoint downloads to DB_PATH before uvicorn starts.
DB_GCS_URI: str | None = os.getenv("DB_GCS_URI")

# CORS (browser-based dev/testing/Swagger; the RN app is not browser-origin).
_origins = os.getenv("CORS_ORIGINS", "*")
CORS_ORIGINS: list[str] = [o.strip() for o in _origins.split(",") if o.strip()]
