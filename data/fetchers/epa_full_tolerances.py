"""
fetchers/epa_full_tolerances.py

EPA eCFR 40 CFR Part 180 -- Full Pesticide Tolerance Database.

Source:
  Electronic Code of Federal Regulations (eCFR)
  https://www.ecfr.gov/current/title-40/chapter-I/subchapter-E/part-180/subpart-C

Content:
  All pesticide tolerances organized by section (180.101, 180.102, ...,
  180.364 for glyphosate, etc.). Each section page contains a table of
  commodity + tolerance (ppm) pairs for a specific pesticide.

This fetcher targets the most important pesticide sections (excluding
glyphosate/180.364 which is handled by epa_tolerances.py) and inserts
into the shared `tolerance_limits` table.

This is a REFERENCE data source, not monitoring data.
"""

import logging
import re
import sqlite3
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from fetchers.base import BaseFetcher, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key, get_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_NAME = "EPA_Full_Part180"
SOURCE_VALUE = "EPA_40CFR180"  # shared with glyphosate-specific fetcher

ECFR_BASE_URL = (
    "https://www.ecfr.gov/current/title-40/chapter-I/"
    "subchapter-E/part-180/subpart-C"
)

# Browser-like headers required because eCFR blocks bot User-Agents
# with a CAPTCHA page.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

CREATE_TOLERANCE_TABLE = """
CREATE TABLE IF NOT EXISTS tolerance_limits (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    food_category       TEXT NOT NULL,
    raw_commodity       TEXT,
    tolerance_ppm       REAL NOT NULL,
    tolerance_ppb       REAL NOT NULL,
    source              TEXT NOT NULL,
    regulation_reference TEXT,
    dedup_key           TEXT UNIQUE
);
"""

# Key pesticide sections to scrape.
# 180.364 (glyphosate) is intentionally EXCLUDED -- it is handled by
# the dedicated epa_tolerances.py fetcher.
REPORTS = [
    {
        "section": "180.258",
        "pesticide": "Chlorpyrifos",
        "regulation": "40 CFR 180.258",
    },
    {
        "section": "180.185",
        "pesticide": "Dicamba",
        "regulation": "40 CFR 180.185",
    },
    {
        "section": "180.368",
        "pesticide": "Glufosinate",
        "regulation": "40 CFR 180.368",
    },
    {
        "section": "180.169",
        "pesticide": "Clopyralid",
        "regulation": "40 CFR 180.169",
    },
    {
        "section": "180.213",
        "pesticide": "Dimethenamid",
        "regulation": "40 CFR 180.213",
    },
    {
        "section": "180.341",
        "pesticide": "Acetochlor",
        "regulation": "40 CFR 180.341",
    },
    {
        "section": "180.350",
        "pesticide": "Bifenthrin",
        "regulation": "40 CFR 180.350",
    },
    {
        "section": "180.443",
        "pesticide": "Fomesafen",
        "regulation": "40 CFR 180.443",
    },
    {
        "section": "180.153",
        "pesticide": "Clethodim",
        "regulation": "40 CFR 180.153",
    },
]

# Sections blocked by eCFR rate-limiting (CAPTCHA). Keep for manual retry.
# 180.344 (Atrazine), 180.105 (2,4-D), 180.115 (Bentazon),
# 180.282 (Fluazifop), 180.338 (Alachlor), 180.091 (Aminopyralid)


def _ecfr_url(section: str) -> str:
    """Build the eCFR URL for a given Part 180 section."""
    return (
        f"https://www.ecfr.gov/current/title-40/chapter-I/"
        f"subchapter-E/part-180/subpart-C/section-{section}"
    )


def _cache_filename(section: str) -> str:
    """Standardised filename for cached HTML."""
    return f"epa_40cfr_{section.replace('.', '_')}.html"


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class EPAFullTolerancesFetcher(BaseFetcher):
    SOURCE_NAME = SOURCE_NAME

    # ------------------------------------------------------------------
    # fetch()
    # ------------------------------------------------------------------
    def fetch(self) -> list[Path]:
        """
        Download each configured section page from eCFR and cache as HTML.

        Uses direct requests.get() with browser-like headers because the
        eCFR site blocks the default session User-Agent with a CAPTCHA.
        Cached files are reused on subsequent runs (idempotent).
        """
        paths: list[Path] = []

        for report in REPORTS:
            section = report["section"]
            dest = RAW_DATA_DIR / _cache_filename(section)

            if dest.exists():
                logger.info("Cache hit: %s", dest.name)
                paths.append(dest)
                continue

            url = _ecfr_url(section)
            logger.info("Fetching %s (%s) -> %s", section, report["pesticide"], url)

            try:
                resp = requests.get(url, headers=HEADERS, timeout=30)
                resp.raise_for_status()
            except requests.RequestException as exc:
                logger.error("Failed to fetch %s: %s", url, exc)
                continue

            html = resp.text

            # Verify we didn't get a CAPTCHA page
            if "Request Access" in html or "captcha" in html.lower():
                logger.error(
                    "eCFR returned a CAPTCHA/access-block page for %s. "
                    "Skipping.", section
                )
                continue

            dest.write_text(html, encoding="utf-8")
            logger.info(
                "Saved %s (%d bytes)", dest.name, len(html)
            )
            paths.append(dest)

            # Polite delay to avoid rate-limiting
            time.sleep(1.0)

        return paths

    # ------------------------------------------------------------------
    # parse()
    # ------------------------------------------------------------------
    def parse(self, files: list[Path]) -> list[dict]:
        """
        Parse cached HTML pages for commodity + ppm tolerance pairs.

        For each section the page contains a tolerance table with rows like:
            | Commodity                     | Parts per million |
            | Alfalfa, forage               | 5.0               |
            | Corn, grain                   | 0.1               |

        We extract each row, normalise the commodity to a canonical category,
        convert ppm to ppb, and build a row dict for the tolerance_limits table.
        """
        file_map = {f.name: f for f in files}
        all_rows: list[dict] = []

        for report in REPORTS:
            section = report["section"]
            cache_name = _cache_filename(section)
            path = file_map.get(cache_name)

            if path is None:
                logger.warning(
                    "No cached file for section %s -- skipping", section
                )
                continue

            html = path.read_text(encoding="utf-8")
            soup = BeautifulSoup(html, "html.parser")

            rows = self._parse_section(soup, report)
            logger.info(
                "%s %s: parsed %d tolerance entries",
                section, report["pesticide"], len(rows),
            )
            all_rows.extend(rows)

        return all_rows

    # ------------------------------------------------------------------
    # Section-level parsing
    # ------------------------------------------------------------------
    def _parse_section(self, soup: BeautifulSoup, report: dict) -> list[dict]:
        """
        Extract tolerance entries from a single section page.
        Tries pipe-delimited table first, then HTML <table> elements.
        """
        rows: list[dict] = []

        # Strategy 1: pipe-delimited / markdown table from page text
        text = soup.get_text(separator="\n")
        rows = self._parse_pipe_table(text, report)

        # Strategy 2: HTML <table> elements
        if not rows:
            rows = self._parse_html_tables(soup, report)

        if not rows:
            logger.warning(
                "No tolerance data extracted from section %s (%s). "
                "Page structure may have changed.",
                report["section"], report["pesticide"],
            )

        return rows

    # ------------------------------------------------------------------
    # Pipe-delimited table parser
    # ------------------------------------------------------------------
    def _parse_pipe_table(self, text: str, report: dict) -> list[dict]:
        """
        Parse markdown-style pipe-delimited table that eCFR typically serves.

        Example:
            | Commodity | Parts per million |
            | --- | --- |
            | Acerola | 0.2 |
            | Alfalfa, seed | 0.5 |
        """
        results: list[dict] = []

        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("|") or not line.endswith("|"):
                continue
            # Skip separator rows like | --- | --- |
            if re.match(r"^\|\s*[-:]+\s*\|", line):
                continue

            parts = [p.strip() for p in line.split("|")]
            # parts[0] and parts[-1] are empty from leading/trailing |
            cells = parts[1:-1]
            if len(cells) < 2:
                continue

            commodity = cells[0]
            ppm_text = cells[1]

            # Skip header row
            if commodity.lower() in ("commodity", ""):
                continue

            entry = self._make_entry(commodity, ppm_text, report)
            if entry:
                results.append(entry)

        return results

    # ------------------------------------------------------------------
    # HTML <table> parser
    # ------------------------------------------------------------------
    def _parse_html_tables(self, soup: BeautifulSoup, report: dict) -> list[dict]:
        """Parse structured HTML <table> elements on the eCFR page."""
        results: list[dict] = []

        for table in soup.find_all("table"):
            header_row = table.find("tr")
            if not header_row:
                continue

            header_cells = header_row.find_all(["th", "td"])
            header_text = " ".join(
                cell.get_text(strip=True).lower() for cell in header_cells
            )

            # Only process tables that look like tolerance tables
            if "commodity" not in header_text and "ppm" not in header_text:
                continue

            for tr in table.find_all("tr")[1:]:  # skip header
                cells = tr.find_all(["td"])
                if len(cells) < 2:
                    continue

                commodity = cells[0].get_text(strip=True)
                ppm_text = cells[1].get_text(strip=True)

                entry = self._make_entry(commodity, ppm_text, report)
                if entry:
                    results.append(entry)

        return results

    # ------------------------------------------------------------------
    # Single-entry builder
    # ------------------------------------------------------------------
    def _make_entry(self, commodity: str, ppm_text: str, report: dict) -> dict | None:
        """
        Parse a single commodity + ppm entry into a tolerance_limits row.
        Returns None for entries that should be skipped.
        """
        commodity = commodity.strip()
        ppm_text = ppm_text.strip()

        # Skip entries with no tolerance established (N notation)
        if "(N)" in ppm_text or "(N)" in commodity:
            return None

        # Strip parenthetical notes like "(computed from parent)"
        commodity = re.sub(r"\(computed.*?\)", "", commodity).strip()
        commodity = re.sub(r"\s+", " ", commodity)

        # Extract numeric ppm value
        ppm_match = re.match(r"([\d.]+)", ppm_text)
        if not ppm_match:
            return None

        try:
            ppm = float(ppm_match.group(1))
        except ValueError:
            return None

        # Skip empty or header-like commodity names
        if not commodity or self._is_header_or_metadata(commodity):
            return None

        ppb = ppm * 1000  # ppm -> ppb

        with get_connection() as conn:
            food_category = normalize_category(commodity, conn)

        section = report["section"]
        dedup = build_dedup_key(
            "EPA_Full_Part180", food_category or commodity, section
        )

        return {
            "food_category": food_category or commodity.lower(),
            "raw_commodity": commodity,
            "tolerance_ppm": ppm,
            "tolerance_ppb": ppb,
            "source": SOURCE_VALUE,
            "regulation_reference": report["regulation"],
            "dedup_key": dedup,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _is_header_or_metadata(text: str) -> bool:
        """Return True if text looks like a table header or metadata."""
        lower = text.lower().strip()
        skip_phrases = {
            "commodity", "parts per million", "ppm", "section",
            "paragraph", "tolerance", "residues", "note:", "table",
            "40 cfr", "ecfr", "subpart", "regulation",
        }
        return lower in skip_phrases or len(lower) < 2

    # ------------------------------------------------------------------
    # run() -- override to target tolerance_limits table
    # ------------------------------------------------------------------
    def run(self) -> dict:
        """
        Override base run() to use custom insert logic for tolerance_limits.
        This fetcher does NOT use the standard insert_rows() pipeline since
        it targets a different table (tolerance_limits vs glyphosate_measurements).
        """
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

        logger.info(
            "%s parsed %d tolerance entries, inserting...",
            self.SOURCE_NAME, len(rows),
        )

        inserted = skipped = failed = 0
        with get_connection() as conn:
            conn.execute(CREATE_TOLERANCE_TABLE)

            for row in rows:
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO tolerance_limits
                            (food_category, raw_commodity, tolerance_ppm,
                             tolerance_ppb, source, regulation_reference, dedup_key)
                        VALUES
                            (:food_category, :raw_commodity, :tolerance_ppm,
                             :tolerance_ppb, :source, :regulation_reference, :dedup_key)
                        """,
                        row,
                    )
                    changes = conn.execute("SELECT changes()").fetchone()[0]
                    if changes:
                        inserted += 1
                    else:
                        skipped += 1
                except sqlite3.Error as e:
                    logger.error(
                        "Insert failed for %s: %s", row.get("raw_commodity"), e
                    )
                    failed += 1

        from db.database import log_ingest
        log_ingest(
            self.SOURCE_NAME,
            "success" if failed == 0 else "partial",
            inserted, skipped, failed,
            source_file=str(files[0]) if files else "",
        )

        logger.info(
            "%s complete: inserted=%d skipped=%d failed=%d",
            self.SOURCE_NAME, inserted, skipped, failed,
        )
        return {"inserted": inserted, "skipped": skipped, "failed": failed}
