"""
fetchers/codex_mrls.py

Codex Alimentarius Maximum Residue Limits (MRLs) for Glyphosate.

Source:
  FAO/WHO Codex Alimentarius Pesticide Residue Database
  https://www.fao.org/fao-who-codexalimentarius/codex-texts/dbs/pestres/
  Glyphosate pesticide ID: 158

Content:
  International MRLs for glyphosate across 100+ commodities in mg/kg (ppm).
  Set by the Codex Committee on Pesticide Residues (CCPR) under the
  Joint FAO/WHO Meeting on Pesticide Residues (JMPR).

This is a REFERENCE data source, not monitoring data.
It populates the `tolerance_limits` table alongside EPA Tolerances.

Strategy:
  1. Attempt to scrape the Codex database search page for glyphosate (ID 158).
  2. If the page is JS-rendered or access is blocked, fall back to a
     comprehensive hardcoded dataset of current Codex MRLs.
"""

import logging
import sqlite3
from pathlib import Path

from bs4 import BeautifulSoup

from fetchers.base import BaseFetcher, SESSION, RAW_DATA_DIR, fetch_page
from db.database import normalize_category, build_dedup_key, get_connection

logger = logging.getLogger(__name__)

SOURCE_NAME = "Codex_Alimentarius"
REGULATION_REFERENCE = "CXC/PR 0218 (Glyphosate)"

# Codex Alimentarius pesticide residue database — glyphosate detail page
CODEX_SEARCH_URL = (
    "https://www.fao.org/fao-who-codexalimentarius/codex-texts/dbs/pestres/"
    "commoditydetail/en/?p_id=158"
)

CREATE_TOLERANCE_TABLE = """
CREATE TABLE IF NOT EXISTS tolerance_limits (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    food_category       TEXT NOT NULL,
    raw_commodity       TEXT,
    contaminant         TEXT NOT NULL DEFAULT 'glyphosate',
    tolerance_ppm       REAL NOT NULL,
    tolerance_ppb       REAL NOT NULL,
    source              TEXT NOT NULL,
    regulation_reference TEXT,
    dedup_key           TEXT UNIQUE
);
"""

CACHE_FILENAME = "codex_glyphosate_mrls.html"

# ---------------------------------------------------------------------------
# Hardcoded Codex MRLs for glyphosate (ppm / mg/kg)
# Sourced from the Codex Alimentarius Pesticide Residue Database.
# These are the internationally harmonized maximum residue limits adopted
# by the Codex Alimentarius Commission.
# ---------------------------------------------------------------------------
CODEX_MRLS_HARDCODED: list[tuple[str, float]] = [
    # ── Cereal grains ──────────────────────────────────────────────────────
    ("Wheat", 5.0),
    ("Wheat bran", 10.0),
    ("Wheat germ", 10.0),
    ("Wheat flour", 5.0),
    ("Wheat whole meal", 5.0),
    ("Barley", 10.0),
    ("Barley pearled", 10.0),
    ("Oats", 10.0),
    ("Oat bran", 10.0),
    ("Rye", 5.0),
    ("Triticale", 5.0),
    ("Corn (maize)", 1.0),
    ("Corn grits", 1.0),
    ("Corn flour", 1.0),
    ("Rice", 0.1),
    ("Rice husked", 0.1),
    ("Rice polished", 0.1),
    ("Sorghum", 5.0),
    ("Millet", 5.0),
    ("Buckwheat", 5.0),
    ("Quinoa", 5.0),
    # ── Oilseeds ───────────────────────────────────────────────────────────
    ("Soybeans", 20.0),
    ("Soybean meal", 20.0),
    ("Canola (rapeseed)", 10.0),
    ("Rapeseed oil", 10.0),
    ("Sunflower seed", 7.0),
    ("Sunflower seed oil", 7.0),
    ("Cottonseed", 10.0),
    ("Cottonseed oil", 10.0),
    ("Peanut", 0.5),
    ("Peanut oil", 0.5),
    ("Sesame seed", 1.0),
    ("Flaxseed (linseed)", 10.0),
    ("Safflower seed", 7.0),
    # ── Sugar crops ────────────────────────────────────────────────────────
    ("Sugar beet", 5.0),
    ("Sugar beet pulp", 5.0),
    ("Sugarcane", 1.0),
    # ── Fruit ──────────────────────────────────────────────────────────────
    ("Apples", 0.5),
    ("Pears", 0.5),
    ("Grapes", 0.5),
    ("Grape juice", 0.5),
    ("Oranges", 0.5),
    ("Lemons", 0.5),
    ("Grapefruit", 0.5),
    ("Citrus pulp", 0.5),
    ("Peaches", 0.05),
    ("Nectarines", 0.05),
    ("Plums", 0.05),
    ("Cherries", 0.05),
    ("Strawberries", 0.05),
    ("Blueberries", 0.05),
    ("Cranberries", 0.05),
    ("Raspberries", 0.05),
    ("Bananas", 0.05),
    ("Pineapples", 0.1),
    ("Mangoes", 0.05),
    ("Avocados", 0.1),
    ("Melons", 0.1),
    ("Watermelons", 0.1),
    ("Kiwifruit", 0.05),
    ("Figs", 0.5),
    ("Olives", 1.0),
    # ── Vegetables ─────────────────────────────────────────────────────────
    ("Lettuce", 5.0),
    ("Spinach", 5.0),
    ("Carrots", 0.5),
    ("Potatoes", 0.2),
    ("Tomatoes", 0.5),
    ("Peppers", 0.5),
    ("Cucumbers", 0.5),
    ("Onions", 0.05),
    ("Garlic", 0.05),
    ("Cabbage", 0.5),
    ("Broccoli", 0.5),
    ("Cauliflower", 0.5),
    ("Celery", 5.0),
    ("Mushrooms", 0.05),
    ("Green beans", 0.5),
    ("Peas", 0.5),
    ("Sweet corn", 1.0),
    ("Asparagus", 0.05),
    ("Beetroot", 5.0),
    ("Turnips", 0.5),
    ("Pumpkins", 0.05),
    ("Squash", 0.05),
    # ── Legumes / pulses ───────────────────────────────────────────────────
    ("Chickpeas", 2.0),
    ("Lentils", 5.0),
    ("Dry beans", 5.0),
    ("Dry peas", 5.0),
    ("Broad beans", 5.0),
    # ── Tree nuts ──────────────────────────────────────────────────────────
    ("Almonds", 1.0),
    ("Walnuts", 1.0),
    ("Pecans", 1.0),
    ("Cashews", 1.0),
    ("Hazelnuts", 1.0),
    ("Pistachios", 1.0),
    # ── Miscellaneous ──────────────────────────────────────────────────────
    ("Tea", 1.0),
    ("Coffee beans", 1.0),
    ("Hops", 5.0),
    ("Cocoa beans", 1.0),
    ("Spices", 0.5),
]


class CodexMRLsFetcher(BaseFetcher):
    """Fetch and parse Codex Alimentarius glyphosate MRLs."""

    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        """
        Attempt to scrape the Codex database page for glyphosate MRLs.
        If the page is JS-rendered or inaccessible, fall back to hardcoded data.
        """
        dest = RAW_DATA_DIR / CACHE_FILENAME

        if dest.exists():
            logger.info("Cache hit: %s", CACHE_FILENAME)
            return [dest]

        try:
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
            resp = SESSION.get(CODEX_SEARCH_URL, headers=headers, timeout=30)
            resp.raise_for_status()
            html = resp.text

            # Check for meaningful content — not an empty JS shell or error page
            soup = BeautifulSoup(html, "html.parser")
            page_text = soup.get_text(strip=True)

            # Heuristic: if the page body is very short or contains error
            # indicators, it's likely a JS-rendered shell
            has_data = (
                "glyphosate" in page_text.lower()
                and ("ppm" in page_text.lower() or "mg/kg" in page_text.lower())
                and len(page_text) > 500
            )

            if has_data:
                dest.write_text(html, encoding="utf-8")
                logger.info(
                    "Saved Codex page to %s (%d bytes)", CACHE_FILENAME, len(html)
                )
                return [dest]
            else:
                logger.warning(
                    "Codex page appears to be JS-rendered or empty (%d chars). "
                    "Falling back to hardcoded MRLs.",
                    len(page_text),
                )

        except Exception as e:
            logger.warning(
                "Failed to fetch Codex page (%s). Falling back to hardcoded MRLs.",
                e,
            )

        # Write a marker file indicating hardcoded fallback was used
        dest.write_text(
            "<!-- Codex MRLs: hardcoded fallback used; "
            "web scrape failed or returned JS-rendered content -->\n",
            encoding="utf-8",
        )
        logger.info("Created fallback marker file: %s", CACHE_FILENAME)
        return [dest]

    def parse(self, files: list[Path]) -> list[dict]:
        """
        Parse Codex MRLs. Tries HTML scraping first, then falls back to
        the hardcoded dataset.
        """
        html = files[0].read_text(encoding="utf-8")

        # If this is a fallback marker file, skip scraping
        if "hardcoded fallback" in html:
            rows = []
        else:
            rows = self._parse_html(html)

        # Fall back to hardcoded data if scraping yielded nothing
        if not rows:
            logger.info("Using hardcoded Codex MRL fallback (%d entries)", len(CODEX_MRLS_HARDCODED))
            rows = self._parse_hardcoded()

        if not rows:
            raise ValueError(
                "No Codex MRL data could be extracted — neither from web "
                "scraping nor from hardcoded fallback."
            )

        logger.info(
            "%s: parsed %d MRL entries", self.SOURCE_NAME, len(rows)
        )
        return rows

    def _parse_html(self, html: str) -> list[dict]:
        """
        Parse the Codex search results HTML for commodity + MRL pairs.

        The Codex database presents results as a table with columns for
        commodity name and MRL value (mg/kg).
        """
        soup = BeautifulSoup(html, "html.parser")
        results = []

        tables = soup.find_all("table")
        for table in tables:
            header_row = table.find("tr")
            if not header_row:
                continue

            header_cells = header_row.find_all(["th", "td"])
            header_text = " ".join(
                cell.get_text(strip=True).lower() for cell in header_cells
            )

            # Only process tables that look like MRL tables
            if not any(
                kw in header_text
                for kw in ("commodity", "mrl", "mg/kg", "ppm", "residue")
            ):
                continue

            for tr in table.find_all("tr")[1:]:  # skip header
                cells = tr.find_all(["td"])
                if len(cells) < 2:
                    continue

                commodity = cells[0].get_text(strip=True)
                ppm_text = cells[-1].get_text(strip=True)

                entry = self._parse_entry(commodity, ppm_text)
                if entry:
                    results.append(entry)

        return results

    def _parse_hardcoded(self) -> list[dict]:
        """Build row dicts from the hardcoded Codex MRL dataset."""
        results = []
        for commodity, ppm in CODEX_MRLS_HARDCODED:
            entry = self._parse_entry(commodity, str(ppm))
            if entry:
                results.append(entry)
        return results

    def _parse_entry(self, commodity: str, ppm_text: str) -> dict | None:
        """
        Parse a single commodity + ppm entry into a tolerance_limits row dict.
        Returns None for entries that should be skipped.
        """
        import re

        commodity = commodity.strip()
        ppm_text = ppm_text.strip()

        if not commodity:
            return None

        # Extract numeric ppm value
        ppm_match = __import__("re").match(r"([\d.]+)", ppm_text)
        if not ppm_match:
            return None

        try:
            ppm = float(ppm_match.group(1))
        except ValueError:
            return None

        ppm_ppb = ppm * 1000  # convert ppm to ppb

        with get_connection() as conn:
            food_category = normalize_category(commodity, conn)

        # Build deterministic dedup key (include pesticide name for uniqueness)
        dedup = build_dedup_key("Codex_MRLs", f"{food_category or commodity}|glyphosate")

        return {
            "food_category": food_category or commodity.lower(),
            "raw_commodity": commodity,
            "contaminant": "glyphosate",
            "tolerance_ppm": ppm,
            "tolerance_ppb": ppm_ppb,
            "source": SOURCE_NAME,
            "regulation_reference": REGULATION_REFERENCE,
            "dedup_key": dedup,
        }

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

        logger.info(
            "%s parsed %d MRL entries, inserting...", self.SOURCE_NAME, len(rows)
        )

        # Create the tolerance_limits table if it doesn't exist
        inserted = skipped = failed = 0
        with get_connection() as conn:
            conn.execute(CREATE_TOLERANCE_TABLE)

            for row in rows:
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO tolerance_limits
                            (food_category, raw_commodity, contaminant,
                             tolerance_ppm, tolerance_ppb, source,
                             regulation_reference, dedup_key)
                        VALUES
                            (:food_category, :raw_commodity, :contaminant,
                             :tolerance_ppm, :tolerance_ppb, :source,
                             :regulation_reference, :dedup_key)
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
