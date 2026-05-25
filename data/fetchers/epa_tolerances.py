"""
fetchers/epa_tolerances.py

EPA Glyphosate Tolerance Limits from eCFR 40 CFR 180.364.

Source:
  Electronic Code of Federal Regulations (eCFR)
  https://www.ecfr.gov/current/title-40/chapter-I/subchapter-E/part-180/subpart-C/section-180.364

Content:
  HTML table listing commodity + tolerance (ppm) pairs for glyphosate.
  150+ commodities with legal maximum residue limits established by EPA.

This is a REFERENCE data source, not monitoring data.
It populates a separate `tolerance_limits` table.
"""

import logging
import re
import sqlite3
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from fetchers.base import BaseFetcher, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key, get_connection

logger = logging.getLogger(__name__)

EPA_ECFR_URL = (
    "https://www.ecfr.gov/current/title-40/chapter-I/subchapter-E"
    "/part-180/subpart-C/section-180.364"
)

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

SOURCE_NAME = "EPA_40CFR180.364"
REGULATION_REFERENCE = "40 CFR 180.364"
CACHE_FILENAME = "epa_40cfr180_364.html"


class EPATolerancesFetcher(BaseFetcher):
    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        """Download the eCFR page and cache it as HTML.

        The eCFR site blocks automated/bot User-Agents with a CAPTCHA
        page ("Request Access"). We use a browser-like User-Agent to
        retrieve the actual page content with the tolerance tables.
        """
        dest = RAW_DATA_DIR / CACHE_FILENAME

        if dest.exists():
            logger.info("Cache hit: %s", CACHE_FILENAME)
            return [dest]

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.5",
        }

        resp = requests.get(EPA_ECFR_URL, headers=headers, timeout=30)
        resp.raise_for_status()
        html = resp.text

        # Verify we didn't get a CAPTCHA page
        if "Request Access" in html or "captcha" in html.lower():
            raise ValueError(
                f"eCFR returned a CAPTCHA/access-block page for {EPA_ECFR_URL}. "
                "The site may have updated its bot detection. "
                "Try fetching manually or from a different IP."
            )

        dest.write_text(html, encoding="utf-8")
        logger.info("Saved eCFR page to %s (%d bytes)", CACHE_FILENAME, len(html))
        return [dest]

    def parse(self, files: list[Path]) -> list[dict]:
        """
        Scrape the eCFR HTML for commodity + ppm pairs from the tolerance table.

        The page contains a markdown-style or HTML table under section 180.364
        with rows like:
            "Asparagus  0.5"
            "Corn, sweet, kernel plus cob with husk removed  3.5"

        We parse each row into a commodity name and ppm value, then map the
        commodity to a canonical food_category via normalize_category.
        """
        html = files[0].read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")

        rows = []

        # Strategy 1: Pipe-delimited or plain-text table from the page content
        rows = self._parse_text_patterns(soup)

        # Strategy 2: Fall back to HTML <table> elements
        if not rows:
            rows = self._parse_html_tables(soup)

        if not rows:
            raise ValueError(
                f"No tolerance data extracted from {CACHE_FILENAME}. "
                "Page structure may have changed — inspect the file manually."
            )

        logger.info(
            "%s: parsed %d tolerance entries", self.SOURCE_NAME, len(rows)
        )
        return rows

    def _parse_html_tables(self, soup: BeautifulSoup) -> list[dict]:
        """Parse structured HTML <table> elements on the eCFR page."""
        results = []

        tables = soup.find_all("table")
        for table in tables:
            # Find header row to identify commodity and ppm columns
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

                entry = self._parse_entry(commodity, ppm_text)
                if entry:
                    results.append(entry)

        return results

    def _parse_pipe_delimited_table(self, text: str) -> list[dict]:
        """
        Parse the markdown-style pipe-delimited table that eCFR serves.

        The table looks like:
            | Commodity | Parts per million |
            | --- | --- |
            | Acerola | 0.2 |
            | Alfalfa, seed | 0.5 |
        """
        results = []
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("|") or not line.endswith("|"):
                continue
            # Skip separator rows like | --- | --- |
            if re.match(r"^\|\s*[-:]+\s*\|", line):
                continue

            parts = [p.strip() for p in line.split("|")]
            # parts[0] and parts[-1] are empty strings from leading/trailing |
            # The actual cells are parts[1:-1]
            cells = parts[1:-1]
            if len(cells) < 2:
                continue

            commodity = cells[0]
            ppm_text = cells[1]

            # Skip the header row
            if commodity.lower() == "commodity":
                continue

            entry = self._parse_entry(commodity, ppm_text)
            if entry:
                results.append(entry)

        return results

    def _parse_text_patterns(self, soup: BeautifulSoup) -> list[dict]:
        """
        Fall back to regex-based parsing of page text.
        First tries pipe-delimited table rows, then plain "commodity N.NN" lines.
        """
        text = soup.get_text(separator="\n")

        # Strategy A: pipe-delimited table rows (most common on eCFR pages)
        results = self._parse_pipe_delimited_table(text)
        if results:
            return results

        # Strategy B: plain "commodity N.NN" lines
        pattern = re.compile(
            r"^([A-Z][A-Za-z ,\-/&()]+?)\s+(\d+\.?\d*)\s*$",
            re.MULTILINE,
        )

        for match in pattern.finditer(text):
            commodity = match.group(1).strip()
            ppm_text = match.group(2).strip()

            # Skip lines that are clearly not tolerance entries
            if self._is_header_or_metadata(commodity):
                continue

            entry = self._parse_entry(commodity, ppm_text)
            if entry:
                results.append(entry)

        return results

    def _parse_entry(self, commodity: str, ppm_text: str) -> dict | None:
        """
        Parse a single commodity + ppm entry into a row dict.
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

        # Skip empty commodity names
        if not commodity:
            return None

        # Skip header-like text
        if self._is_header_or_metadata(commodity):
            return None

        ppm_ppb = ppm * 1000  # convert ppm to ppb

        with get_connection() as conn:
            food_category = normalize_category(commodity, conn)

        # Build deterministic dedup key
        dedup = build_dedup_key("EPA_Tolerances", food_category or commodity)

        return {
            "food_category": food_category or commodity.lower(),
            "raw_commodity": commodity,
            "tolerance_ppm": ppm,
            "tolerance_ppb": ppm_ppb,
            "source": SOURCE_NAME,
            "regulation_reference": REGULATION_REFERENCE,
            "dedup_key": dedup,
        }

    def _is_header_or_metadata(self, text: str) -> bool:
        """Return True if the text looks like a table header or metadata, not a commodity."""
        lower = text.lower().strip()
        skip_phrases = {
            "commodity", "parts per million", "ppm", "section",
            "paragraph", "tolerance", "residues", "glyphosate",
            "note:", "table", "40 cfr", "eCFR",
        }
        return lower in skip_phrases or len(lower) < 2

    def run(self) -> dict:
        """
        Override base run() to use custom insert logic for tolerance_limits table.
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

        logger.info("%s parsed %d tolerance entries, inserting...", self.SOURCE_NAME, len(rows))

        # Create the tolerance_limits table if it doesn't exist
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
            source_file=str(files[0]),
        )

        logger.info(
            "%s complete: inserted=%d skipped=%d failed=%d",
            self.SOURCE_NAME, inserted, skipped, failed,
        )
        return {"inserted": inserted, "skipped": skipped, "failed": failed}
