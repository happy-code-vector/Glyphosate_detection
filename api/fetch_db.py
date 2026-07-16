"""Pull a fresh read-only DB from GCS at container startup (Cloud Run).

On Cloud Run, Application Default Credentials are exposed by the metadata
server: we fetch a short-lived access token and stream the object down with the
standard library only — no ``google-cloud-storage`` dependency and no ``gcloud``
binary baked into the image. Locally, leave ``DB_GCS_URI`` unset and the repo's
``data/residueiq.db`` is used directly, so this is a no-op.

Run:  python -m api.fetch_db [--force]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from api.config import DB_GCS_URI, DB_PATH

_METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1"
    "/instance/service-accounts/default/token"
)


def _access_token() -> str:
    """Return a GCP bearer token.

    Tries the metadata server first (Cloud Run / GCE). Falls back to
    ``gcloud auth print-access-token`` so the entrypoint can be exercised on a
    developer machine that has the gcloud SDK and ADC configured.
    """
    req = urllib.request.Request(
        _METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))["access_token"]
    except Exception:
        pass  # not on Cloud Run; try the gcloud fallback below

    try:
        out = subprocess.check_output(
            ["gcloud", "auth", "print-access-token"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except Exception as exc:  # pragma: no cover - environment-specific
        raise RuntimeError(
            "Could not obtain GCP credentials (metadata server unreachable and "
            f"`gcloud auth print-access-token` failed: {exc})."
        ) from exc


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"DB_GCS_URI must be 'gs://…', got {uri!r}")
    bucket, _, obj = uri[len("gs://"):].partition("/")
    if not bucket or not obj:
        raise ValueError(f"DB_GCS_URI missing bucket/object: {uri!r}")
    return bucket, obj


def fetch(force: bool = False) -> None:
    """Download the DB object to ``DB_PATH`` when ``DB_GCS_URI`` is configured.

    Skipped (a) when ``DB_GCS_URI`` is unset (local dev), or (b) when the DB is
    already present and ``force`` is False (warm container restart).
    """
    if not DB_GCS_URI:
        print(f"[fetch_db] DB_GCS_URI unset; using local DB at {DB_PATH}")
        return
    existing = Path(DB_PATH)
    if not force and existing.exists() and existing.stat().st_size > 0:
        print(f"[fetch_db] DB already present ({existing.stat().st_size // (1 << 20)} MiB); "
              "skipping download")
        return

    bucket, obj = _parse_gs_uri(DB_GCS_URI)
    token = _access_token()
    url = f"https://storage.googleapis.com/{bucket}/{obj}"
    tmp = f"{DB_PATH}.part"
    print(f"[fetch_db] downloading {DB_GCS_URI} -> {DB_PATH}")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=180) as resp, open(tmp, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)  # 1 MiB
            if not chunk:
                break
            fh.write(chunk)
    os.replace(tmp, DB_PATH)  # atomic on the same filesystem
    mib = Path(DB_PATH).stat().st_size / (1 << 20)
    print(f"[fetch_db] done ({mib:.0f} MiB)")


if __name__ == "__main__":
    fetch(force="--force" in sys.argv)
