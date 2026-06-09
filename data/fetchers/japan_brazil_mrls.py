"""
fetchers/japan_brazil_mrls.py

Japan and Brazil glyphosate Maximum Residue Limits (MRLs).

Sources:
  Japan: Ministry of Health, Labour and Welfare (MHLW) MRL Database
         https://www.m5.ws001.squarestart.ne.jp/foundation/search.html
  Brazil: ANVISA Agencia Nacional de Vigilancia Sanitaria
          RDC 296/2019 (PARA program)

This is a HARDCODED reference data fetcher. Japan's MRL database uses
JavaScript rendering and cannot be scraped. Brazil's MRLs are published
as PDF reports. The key commodity MRL values are encoded directly.

This source populates the `tolerance_limits` table (like EPA Tolerances).
"""

import logging
import sqlite3
from pathlib import Path

from fetchers.base import BaseFetcher
from db.database import normalize_category, build_dedup_key, get_connection

logger = logging.getLogger(__name__)

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

# ─────────────────────────────────────────────────────────────────────
# Japan MHLW MRLs for glyphosate (ppm)
# Source: Japan MRL Database
# ─────────────────────────────────────────────────────────────────────
JAPAN_SOURCE = "Japan_MRLs"
JAPAN_REFERENCE = "Japan MRL Database"

JAPAN_MRLS = [
    # Grains
    ("Wheat",          5),
    ("Barley",         10),
    ("Rye",            5),
    ("Oats",          10),
    ("Corn",           1),
    ("Rice",           0.1),
    ("Sorghum",        5),
    # Oilseeds
    ("Soybeans",      20),
    ("Canola",        10),
    ("Sunflower seed", 7),
    ("Sugar beet",     5),
    ("Cottonseed",    10),
    # Fruit
    ("Apple",          0.5),
    ("Grape",          0.5),
    ("Orange",         0.5),
    ("Peach",          0.5),
    # Vegetables
    ("Tomato",         0.5),
    ("Cabbage",        0.5),
    ("Lettuce",        5),
    ("Carrot",         0.5),
    ("Potato",         0.5),
    ("Onion",          0.5),
    ("Cucumber",       0.5),
    # Other
    ("Green tea",      1),
    ("Soybean oil",   10),
    ("Corn oil",       1),
    ("Milk",           0.05),
    ("Eggs",           0.05),
    ("Meat",           0.05),
]

# ─────────────────────────────────────────────────────────────────────
# Brazil ANVISA MRLs for glyphosate (ppm)
# Source: ANVISA RDC 296/2019
# ─────────────────────────────────────────────────────────────────────
BRAZIL_SOURCE = "Brazil_ANVISA"
BRAZIL_REFERENCE = "ANVISA RDC 296/2019"

BRAZIL_MRLS = [
    # Grains
    ("Wheat flour",   10),
    ("Barley",        10),
    ("Oats",          10),
    ("Corn",           1),
    ("Rice",           0.1),
    # Oilseeds
    ("Soybeans",      10),
    ("Canola",        10),
    # Other crops
    ("Sugar cane",     2),
    ("Cotton",        15),
    # Fruit
    ("Apple",          0.5),
    ("Grape",          0.5),
    ("Citrus",         0.5),
    # Vegetables
    ("Tomato",         1),
    ("Lettuce",        5),
    ("Carrot",         0.5),
]


class JapanBrazilMRLFetcher(BaseFetcher):
    """
    Hardcoded reference fetcher for Japan and Brazil glyphosate MRLs.

    No web fetching is performed. The run() method builds rows from
    the hardcoded MRL tables and inserts them into tolerance_limits.
    """
    SOURCE_NAME = "Japan_Brazil_MRLs"

    def fetch(self) -> list[Path]:
        """No files to fetch — data is hardcoded."""
        return []

    def parse(self, files: list[Path]) -> list[dict]:
        """Not used — run() handles everything directly."""
        return []

    def _build_rows(self) -> list[dict]:
        """Build tolerance limit rows from hardcoded MRL data."""
        rows = []

        rows.extend(self._build_source_rows(
            JAPAN_MRLS, JAPAN_SOURCE, JAPAN_REFERENCE,
        ))
        rows.extend(self._build_source_rows(
            BRAZIL_MRLS, BRAZIL_SOURCE, BRAZIL_REFERENCE,
        ))

        return rows

    def _build_source_rows(
        self, mrl_list: list[tuple[str, float]], source: str, reference: str,
    ) -> list[dict]:
        """Convert a list of (commodity, ppm) tuples into tolerance limit rows."""
        rows = []

        with get_connection() as conn:
            for raw_commodity, ppm in mrl_list:
                food_category = normalize_category(raw_commodity, conn)
                if not food_category:
                    logger.warning(
                        "%s: no canonical category for '%s' — using raw name",
                        source, raw_commodity,
                    )
                    food_category = raw_commodity.lower()

                ppb = ppm * 1000  # ppm -> ppb
                dedup = build_dedup_key(source, food_category, raw_commodity)

                rows.append({
                    "food_category": food_category,
                    "raw_commodity": raw_commodity,
                    "tolerance_ppm": ppm,
                    "tolerance_ppb": ppb,
                    "source": source,
                    "regulation_reference": reference,
                    "contaminant": "glyphosate",
                    "dedup_key": dedup,
                })

        return rows

    def run(self) -> dict:
        """
        Override base run() to insert into tolerance_limits table.
        No fetch/parse cycle — data is hardcoded.
        """
        logger.info("=== Starting %s pipeline ===", self.SOURCE_NAME)

        rows = self._build_rows()
        logger.info(
            "%s built %d tolerance entries (Japan=%d, Brazil=%d), inserting...",
            self.SOURCE_NAME, len(rows), len(JAPAN_MRLS), len(BRAZIL_MRLS),
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
                             tolerance_ppb, source, regulation_reference,
                             contaminant, dedup_key)
                        VALUES
                            (:food_category, :raw_commodity, :tolerance_ppm,
                             :tolerance_ppb, :source, :regulation_reference,
                             :contaminant, :dedup_key)
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
                        row.get("raw_commodity"), row.get("source"), e,
                    )
                    failed += 1

        from db.database import log_ingest
        log_ingest(
            self.SOURCE_NAME,
            "success" if failed == 0 else "partial",
            inserted, skipped, failed,
            source_file="hardcoded",
        )

        logger.info(
            "%s complete: inserted=%d skipped=%d failed=%d",
            self.SOURCE_NAME, inserted, skipped, failed,
        )
        return {"inserted": inserted, "skipped": skipped, "failed": failed}
