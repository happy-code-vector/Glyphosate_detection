"""
fetchers/usda_fas_mrls.py

USDA Foreign Agricultural Service (FAS) MRL Database for international
maximum residue limits on glyphosate.

Source:
  USDA FAS MRL Search Tool
  https://apps.fas.usda.gov/psdonline/app/index.html#/app/mrlSearch

Content:
  International MRL comparisons for glyphosate across major trading
  partners: EU (EFSA), Canada (Health Canada / PMRA), Japan (MHLW),
  Australia (FSANZ), and Brazil (ANVISA). Shows how US tolerances
  compare to other major regulatory bodies.

This source inserts into the `international_mrls` table -- a dedicated
table for cross-country regulatory comparisons, separate from the
tolerance_limits table used by EPA and Codex.

Strategy:
  1. Attempt to fetch the FAS MRL search page.
  2. The FAS website is a JavaScript-heavy single-page application that
     cannot be scraped with simple HTTP requests. Fall back to hardcoded
     data with key international MRL comparisons for glyphosate.
"""

import logging
import sqlite3
from pathlib import Path

from fetchers.base import BaseFetcher, SESSION, RAW_DATA_DIR, fetch_page
from db.database import normalize_category, build_dedup_key, get_connection

logger = logging.getLogger(__name__)

SOURCE_NAME = "USDA_FAS_MRLs"
SOURCE_URL = "https://apps.fas.usda.gov/psdonline/app/index.html#/app/mrlSearch"

CREATE_INTERNATIONAL_MRLS_TABLE = """
CREATE TABLE IF NOT EXISTS international_mrls (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    food_category       TEXT NOT NULL,
    raw_commodity       TEXT,
    pesticide           TEXT NOT NULL DEFAULT 'glyphosate',
    country_region      TEXT NOT NULL,
    mrl_ppm             REAL NOT NULL,
    mrl_ppb             REAL NOT NULL,
    regulatory_body     TEXT,
    source_url          TEXT,
    dedup_key           TEXT UNIQUE
);
"""

# ---------------------------------------------------------------------------
# International glyphosate MRLs by country/region (ppm)
#
# Sources:
#   EU: EFSA (European Food Safety Authority) Regulation (EC) No 396/2005
#   Canada: Health Canada / PMRA MRL Database
#   Japan: MHLW (Ministry of Health, Labour and Welfare) MRL Database
#   Australia: FSANZ (Food Standards Australia New Zealand) MRL Standard
#   Brazil: ANVISA (Agencia Nacional de Vigilancia Sanitaria) RDC 296/2019
#
# Key comparison points:
#   Oats:     US 30 ppm, EU 20 ppm, Canada 15 ppm, Japan 10 ppm
#   Wheat:    US 30 ppm, EU 10 ppm, Canada 5 ppm
#   Soybeans: US 20 ppm, EU 20 ppm, Canada 20 ppm, Japan 20 ppm
# ---------------------------------------------------------------------------

# MRL data is in international_mrls_data.py


class USDAFASMRLFetcher(BaseFetcher):
    """
    USDA Foreign Agricultural Service MRL Database fetcher.

    Provides international glyphosate MRL comparisons across major
    trading partners. Inserts into the dedicated `international_mrls` table.
    """

    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        """
        Attempt to fetch the FAS MRL search page.

        The FAS website is a JavaScript-heavy SPA that cannot be meaningfully
        scraped. This method tries the page and always falls back to hardcoded
        data since the site requires a browser to render.
        """
        cache_path = RAW_DATA_DIR / "usda_fas_mrls_page.html"

        if cache_path.exists():
            logger.info("Cache hit: usda_fas_mrls_page.html")
            return [cache_path]

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
            resp = SESSION.get(SOURCE_URL, headers=headers, timeout=30)
            resp.raise_for_status()
            html = resp.text

            # The FAS site is a SPA — even a successful response is just a
            # JS shell with no actual MRL data in the HTML.
            # Save it for completeness but we will always use hardcoded data.
            cache_path.write_text(html, encoding="utf-8")
            logger.info(
                "Saved FAS page to %s (%d bytes) — "
                "will use hardcoded MRL data regardless",
                cache_path.name, len(html),
            )

        except Exception as e:
            logger.warning(
                "Failed to fetch FAS page (%s). "
                "Using hardcoded international MRL data.",
                e,
            )
            cache_path.write_text(
                "<!-- USDA FAS MRLs: hardcoded fallback used; "
                "web fetch failed -->\n",
                encoding="utf-8",
            )

        return [cache_path]

    def parse(self, files: list[Path]) -> list[dict]:
        """
        Parse international MRL data. Since the FAS website is a JavaScript
        SPA, this always returns the hardcoded dataset.
        """
        rows = self._build_hardcoded_rows()

        if not rows:
            raise ValueError(
                "No international MRL data could be built from hardcoded dataset."
            )

        logger.info(
            "%s: parsed %d international MRL entries",
            self.SOURCE_NAME, len(rows),
        )
        return rows

    def _build_hardcoded_rows(self) -> list[dict]:
        """
        Build row dicts from the comprehensive international MRL dataset.
        Uses international_mrls_data.py for top 50 pesticides across 6 countries.
        """
        from fetchers.international_mrls_data import get_mrl_rows
        return get_mrl_rows()

    def run(self) -> dict:
        """
        Override base run() to insert into the international_mrls table.

        This fetcher does NOT use the standard insert_rows() pipeline since
        it targets a different table (international_mrls vs
        glyphosate_measurements). The flow is:
          1. Attempt web fetch (always falls back to hardcoded data)
          2. Parse hardcoded MRL data into row dicts
          3. Create the international_mrls table if it does not exist
          4. INSERT OR IGNORE with dedup_key for idempotent runs
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
            "%s parsed %d international MRL entries, inserting...",
            self.SOURCE_NAME, len(rows),
        )

        # Create the international_mrls table if it doesn't exist
        inserted = skipped = failed = 0
        with get_connection() as conn:
            conn.execute(CREATE_INTERNATIONAL_MRLS_TABLE)

            for row in rows:
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO international_mrls
                            (food_category, raw_commodity, pesticide,
                             country_region, mrl_ppm, mrl_ppb,
                             regulatory_body, source_url, dedup_key)
                        VALUES
                            (:food_category, :raw_commodity, :pesticide,
                             :country_region, :mrl_ppm, :mrl_ppb,
                             :regulatory_body, :source_url, :dedup_key)
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
                        "Insert failed for %s (%s): %s",
                        row.get("raw_commodity"), row.get("country_region"), e,
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
