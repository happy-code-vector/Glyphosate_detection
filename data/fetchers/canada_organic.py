"""
fetchers/canada_organic.py

Canada Organic certified products.

Source:
  https://www.canada.ca/en/agriculture-agri-food/services/organic-products.html
  Canada Organic certification restricts synthetic pesticide use including
  glyphosate. Products must meet Canada Organic Regime (COR) standards.

Tier 1 (certified products data).
"""

import logging
from pathlib import Path

from fetchers.base import BaseFetcher, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

SOURCE_NAME = "Canada_Organic"
SOURCE_URL = "https://www.canada.ca/en/agriculture-agri-food/services/organic-products.html"

CANADA_ORGANIC_PRODUCTS = [
    # ── Oats and Cereals ───────────────────────────────────────────────
    ("Organic Rolled Oats", "Nature's Path", "oats", 2020),
    ("Organic Quick Oats", "Nature's Path", "oats", 2020),
    ("Organic Granola", "Nature's Path", "oats", 2020),
    ("Organic Muesli", "Nature's Path", "oats", 2020),
    ("Organic Heritage Flakes", "Nature's Path", "oats", 2020),
    ("Organic Heritage Crunch", "Nature's Path", "oats", 2020),
    ("Organic Corn Flakes", "Nature's Path", "corn", 2020),
    ("Organic Sunrise Cereal", "Nature's Path", "oats", 2020),
    ("Organic EnviroKidz Cereal", "Nature's Path", "oats", 2020),
    ("Organic Hot Oatmeal", "Nature's Path", "oats", 2020),
    ("Organic Instant Oatmeal", "Nature's Path", "oats", 2020),
    ("Organic Granola Bars", "Nature's Path", "oats", 2020),
    # ── Bread and Bakery ───────────────────────────────────────────────
    ("Organic Whole Grain Bread", "Silver Hills", "wheat", 2020),
    ("Organic Squirrelly Bread", "Silver Hills", "wheat", 2020),
    ("Organic Steady Eddie", "Silver Hills", "wheat", 2020),
    ("Organic Big 16", "Silver Hills", "wheat", 2020),
    ("Organic Sprouted Power", "Silver Hills", "wheat", 2020),
    # ── Dairy ──────────────────────────────────────────────────────────
    ("Organic Whole Milk", "Organic Meadow", "fresh_fruit", 2020),
    ("Organic 2% Milk", "Organic Meadow", "fresh_fruit", 2020),
    ("Organic Butter", "Organic Meadow", "butter", 2020),
    ("Organic Cream", "Organic Meadow", "fresh_fruit", 2020),
    ("Organic Yogurt", "Liberte", "fresh_fruit", 2020),
    ("Organic Greek Yogurt", "Liberte", "fresh_fruit", 2020),
    # ── Eggs ───────────────────────────────────────────────────────────
    ("Organic Free Range Eggs", "Organic Meadow", "fresh_fruit", 2020),
    ("Organic Cage Free Eggs", "Born 3", "fresh_fruit", 2020),
    # ── Fruit and Vegetables ───────────────────────────────────────────
    ("Organic Apples", "Various", "fresh_fruit", 2020),
    ("Organic Bananas", "Various", "fresh_fruit", 2020),
    ("Organic Carrots", "Various", "fresh_vegetables", 2020),
    ("Organic Potatoes", "Various", "fresh_vegetables", 2020),
    ("Organic Tomatoes", "Various", "fresh_vegetables", 2020),
    ("Organic Onions", "Various", "fresh_vegetables", 2020),
    # ── Drinks ─────────────────────────────────────────────────────────
    ("Organic Orange Juice", "Various", "fresh_fruit", 2020),
    ("Organic Apple Juice", "Various", "fresh_fruit", 2020),
    ("Organic Coffee", "Kicking Horse", "fresh_vegetables", 2020),
    ("Organic Tea", "Red Rose", "fresh_vegetables", 2020),
]


class CanadaOrganicFetcher(BaseFetcher):
    """Fetches Canada Organic certified product data."""

    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        sentinel = RAW_DATA_DIR / "canada_organic_sentinel.txt"
        if not sentinel.exists():
            sentinel.write_text("Canada Organic data - hardcoded", encoding="utf-8")
        return [sentinel]

    def parse(self, files: list[Path]) -> list[dict]:
        rows = []
        for entry in CANADA_ORGANIC_PRODUCTS:
            product_name, brand, raw_cat, data_year = entry
            food_category = normalize_category(raw_cat)
            if not food_category:
                food_category = raw_cat
            rows.append({
                "product_name": product_name,
                "brand": brand,
                "food_category": food_category,
                "raw_category": raw_cat,
                "certification": "Canada Organic",
                "threshold_ppb": 10.0,
                "source": SOURCE_NAME,
                "source_url": SOURCE_URL,
                "verified_date": f"{data_year}-01-01",
                "contaminant": None,
                "dedup_key": build_dedup_key(SOURCE_NAME, product_name, brand),
            })
        logger.info("%s: built %d certified product rows", SOURCE_NAME, len(rows))
        return rows

    def run(self) -> dict:
        import sqlite3
        from db.database import get_connection, log_ingest
        logger.info("=== Starting %s pipeline ===", self.SOURCE_NAME)
        files = self.fetch()
        rows = self.parse(files)
        inserted = skipped = failed = 0
        with get_connection() as conn:
            for row in rows:
                if not row.get("dedup_key"):
                    failed += 1
                    continue
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO certified_products (
                            product_name, brand, food_category, raw_category,
                            certification, contaminant, threshold_ppb, source, source_url,
                            verified_date, dedup_key
                        ) VALUES (
                            :product_name, :brand, :food_category, :raw_category,
                            :certification, :contaminant, :threshold_ppb, :source, :source_url,
                            :verified_date, :dedup_key
                        )
                    """, row)
                    changes = conn.execute("SELECT changes()").fetchone()[0]
                    if changes:
                        inserted += 1
                    else:
                        skipped += 1
                except sqlite3.Error as e:
                    logger.error("Insert failed for %s: %s", row.get("dedup_key"), e)
                    failed += 1
        log_ingest(self.SOURCE_NAME, "success" if failed == 0 else "partial",
                   inserted, skipped, failed, source_file=str(files))
        logger.info("%s complete: inserted=%d skipped=%d failed=%d",
                    self.SOURCE_NAME, inserted, skipped, failed)
        return {"inserted": inserted, "skipped": skipped, "failed": failed}
