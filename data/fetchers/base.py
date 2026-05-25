"""
fetchers/base.py
Base class for all source fetchers.
Handles: HTTP with retry, file download with integrity check,
         caching to raw_data/, and logging.
"""

import hashlib
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RAW_DATA_DIR = Path(__file__).parent.parent / "raw_data"
RAW_DATA_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=2,          # waits 2, 4, 8, 16, 32 seconds between retries
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": (
            "ResidueIQ-DataPipeline/1.0 "
            "(research data collection; contact@residueiq.app)"
        )
    })
    return session


SESSION = _build_session()


def download_file(url: str, dest_filename: str, expected_sha256: str = None) -> Path:
    """
    Download a file to raw_data/. Skips download if file already exists
    and hash matches (idempotent). Returns local path.
    Raises on failure — never returns silently broken data.
    """
    dest = RAW_DATA_DIR / dest_filename
    if dest.exists():
        if expected_sha256:
            actual = _sha256(dest)
            if actual == expected_sha256:
                logger.info("Cache hit (hash match): %s", dest_filename)
                return dest
            else:
                logger.warning(
                    "Cached file hash mismatch — re-downloading: %s", dest_filename
                )
        else:
            logger.info("Cache hit (no hash check): %s", dest_filename)
            return dest

    logger.info("Downloading %s -> %s", url, dest_filename)
    resp = SESSION.get(url, stream=True, timeout=120)
    resp.raise_for_status()

    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)

    if expected_sha256:
        actual = _sha256(dest)
        if actual != expected_sha256:
            dest.unlink()
            raise ValueError(
                f"Hash mismatch for {dest_filename}. "
                f"Expected {expected_sha256}, got {actual}. "
                "File deleted — possible data corruption or source update."
            )
    logger.info("Downloaded %s (%d bytes)", dest_filename, dest.stat().st_size)
    return dest


def fetch_page(url: str, timeout: int = 30) -> str:
    """Fetch a web page. Raises on HTTP error."""
    resp = SESSION.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class BaseFetcher(ABC):
    """
    Every source fetcher extends this.
    Implement fetch() and parse() — runner calls both.
    """
    SOURCE_NAME: str = ""

    @abstractmethod
    def fetch(self) -> list[Path]:
        """
        Download source files to raw_data/.
        Returns list of local paths that were fetched.
        Must be idempotent — safe to re-run without re-downloading.
        """

    @abstractmethod
    def parse(self, files: list[Path]) -> list[dict]:
        """
        Parse fetched files into normalized row dicts.
        Each dict must include all required schema fields.
        Must not contain any hardcoded measurement values.
        Raises ValueError if file format has changed unexpectedly.
        """

    def run(self) -> dict:
        """Fetch + parse + insert. Returns insert counts."""
        from db.database import insert_rows
        logger.info("=== Starting %s pipeline ===", self.SOURCE_NAME)
        try:
            files = self.fetch()
        except Exception as e:
            from db.database import log_ingest
            log_ingest(self.SOURCE_NAME, "failed", error_message=str(e))
            logger.error("%s fetch failed: %s", self.SOURCE_NAME, e)
            raise

        try:
            rows = self.parse(files)
        except Exception as e:
            from db.database import log_ingest
            log_ingest(self.SOURCE_NAME, "failed", error_message=str(e))
            logger.error("%s parse failed: %s", self.SOURCE_NAME, e)
            raise

        logger.info("%s parsed %d rows, inserting...", self.SOURCE_NAME, len(rows))
        counts = insert_rows(rows, self.SOURCE_NAME, str(files))
        logger.info(
            "%s complete: inserted=%d skipped=%d failed=%d",
            self.SOURCE_NAME, counts["inserted"], counts["skipped"], counts["failed"]
        )
        return counts
