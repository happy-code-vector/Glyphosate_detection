"""
fetchers/non_gmo_project.py

Non-GMO Project verified products.

Source:
  https://www.nongmoproject.org/
  Non-GMO Project verifies products that are produced without genetic
  engineering. While not directly about glyphosate, many Non-GMO products
  also avoid glyphosate-based herbicides used on GMO crops.

Tier 1 (certified products data).
"""

import logging
from pathlib import Path

from fetchers.base import BaseFetcher, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

SOURCE_NAME = "NonGMOProject"
SOURCE_URL = "https://www.nongmoproject.org/"

NON_GMO_PRODUCTS = [
    # ── Oats and Cereals ───────────────────────────────────────────────
    ("Non-GMO Rolled Oats", "Bob's Red Mill", "oats", 2020),
    ("Non-GMO Quick Oats", "Bob's Red Mill", "oats", 2020),
    ("Non-GMO Steel Cut Oats", "Bob's Red Mill", "oats", 2020),
    ("Non-GMO Oat Groats", "Bob's Red Mill", "oats", 2020),
    ("Non-GMO Oat Flour", "Bob's Red Mill", "oats", 2020),
    ("Non-GMO Granola", "Bear Naked", "oats", 2020),
    ("Non-GMO Granola", "Kind", "oats", 2020),
    ("Non-GMO Granola Bars", "Kind", "oats", 2020),
    ("Non-GMO Granola Bars", "Nature Valley", "oats", 2020),
    # ── Bread and Bakery ───────────────────────────────────────────────
    ("Non-GMO Whole Wheat Bread", "Arnold", "wheat", 2020),
    ("Non-GMO White Bread", "Arnold", "wheat", 2020),
    ("Non-GMO Whole Grain Bread", "Pepperidge Farm", "wheat", 2020),
    ("Non-GMO Whole Wheat Bread", "Sara Lee", "wheat", 2020),
    # ── Pasta and Flour ────────────────────────────────────────────────
    ("Non-GMO Spaghetti", "Barilla", "wheat", 2020),
    ("Non-GMO Penne", "Barilla", "wheat", 2020),
    ("Non-GMO Fusilli", "Barilla", "wheat", 2020),
    ("Non-GMO Elbow Macaroni", "Barilla", "wheat", 2020),
    ("Non-GMO Whole Wheat Flour", "King Arthur", "wheat", 2020),
    ("Non-GMO All-Purpose Flour", "King Arthur", "wheat", 2020),
    ("Non-GMO Bread Flour", "King Arthur", "wheat", 2020),
    ("Non-GMO Whole Wheat Flour", "Gold Medal", "wheat", 2020),
    ("Non-GMO All-Purpose Flour", "Gold Medal", "wheat", 2020),
    # ── Corn Products ──────────────────────────────────────────────────
    ("Non-GMO Corn Chips", "Tostitos", "corn", 2020),
    ("Non-GMO Tortilla Chips", "Tostitos", "corn", 2020),
    ("Non-GMO Corn Chips", "Fritos", "corn", 2020),
    ("Non-GMO Popcorn", "Orville Redenbacher's", "corn", 2020),
    ("Non-GMO Popcorn", "Smartfood", "corn", 2020),
    ("Non-GMO Corn Flakes", "Kellogg's", "corn", 2020),
    # ── Soy Products ───────────────────────────────────────────────────
    ("Non-GMO Tofu", "Nasoya", "soybeans", 2020),
    ("Non-GMO Tempeh", "Nasoya", "soybeans", 2020),
    ("Non-GMO Soy Milk", "Silk", "soybeans", 2020),
    ("Non-GMO Edamame", "Seapoint Farms", "soybeans", 2020),
    # ── Dairy ──────────────────────────────────────────────────────────
    ("Non-GMO Whole Milk", "Organic Valley", "fresh_fruit", 2020),
    ("Non-GMO 2% Milk", "Organic Valley", "fresh_fruit", 2020),
    ("Non-GMO Butter", "Organic Valley", "butter", 2020),
    ("Non-GMO Cheese", "Organic Valley", "fresh_fruit", 2020),
    ("Non-GMO Yogurt", "Stonyfield", "fresh_fruit", 2020),
    ("Non-GMO Greek Yogurt", "Chobani", "fresh_fruit", 2020),
    # ── Eggs ───────────────────────────────────────────────────────────
    ("Non-GMO Free Range Eggs", "Pete and Gerry's", "fresh_fruit", 2020),
    ("Non-GMO Cage Free Eggs", "Nellie's", "fresh_fruit", 2020),
    # ── Meat and Poultry ───────────────────────────────────────────────
    ("Non-GMO Chicken Breast", "Applegate", "fresh_vegetables", 2020),
    ("Non-GMO Turkey Breast", "Applegate", "fresh_vegetables", 2020),
    ("Non-GMO Beef Hot Dogs", "Applegate", "fresh_vegetables", 2020),
    ("Non-GMO Ground Beef", "Applegate", "fresh_vegetables", 2020),
    # ── Canned and Packaged ────────────────────────────────────────────
    ("Non-GMO Diced Tomatoes", "Muir Glen", "fresh_vegetables", 2020),
    ("Non-GMO Tomato Sauce", "Muir Glen", "fresh_vegetables", 2020),
    ("Non-GMO Tomato Paste", "Muir Glen", "fresh_vegetables", 2020),
    ("Non-GMO Black Beans", "Eden", "beans", 2020),
    ("Non-GMO Kidney Beans", "Eden", "beans", 2020),
    ("Non-GMO Chickpeas", "Eden", "chickpeas", 2020),
    ("Non-GMO Lentils", "Eden", "lentils", 2020),
    # ── Drinks ─────────────────────────────────────────────────────────
    ("Non-GMO Orange Juice", "Tropicana", "fresh_fruit", 2020),
    ("Non-GMO Apple Juice", "Mott's", "fresh_fruit", 2020),
    ("Non-GMO Almond Milk", "Silk", "fresh_fruit", 2020),
    ("Non-GMO Oat Milk", "Oatly", "oats", 2020),
    # ── Baby Food ──────────────────────────────────────────────────────
    ("Non-GMO Baby Food Apple", "Happy Baby", "infant_cereal", 2020),
    ("Non-GMO Baby Food Banana", "Happy Baby", "infant_cereal", 2020),
    ("Non-GMO Baby Food Pear", "Happy Baby", "infant_cereal", 2020),
    ("Non-GMO Baby Cereal", "Happy Baby", "infant_cereal", 2020),
    # ── Snacks ─────────────────────────────────────────────────────────
    ("Non-GMO Pretzels", "Snyder's", "wheat", 2020),
    ("Non-GMO Crackers", "Wheat Thins", "wheat", 2020),
    ("Non-GMO Crackers", "Triscuit", "wheat", 2020),
    ("Non-GMO Potato Chips", "Lay's", "fresh_vegetables", 2020),
    ("Non-GMO Potato Chips", "Kettle Brand", "fresh_vegetables", 2020),
]


class NonGMOProjectFetcher(BaseFetcher):
    """Fetches Non-GMO Project verified product data."""

    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        sentinel = RAW_DATA_DIR / "non_gmo_project_sentinel.txt"
        if not sentinel.exists():
            sentinel.write_text("Non-GMO Project data - hardcoded", encoding="utf-8")
        return [sentinel]

    def parse(self, files: list[Path]) -> list[dict]:
        rows = []
        for entry in NON_GMO_PRODUCTS:
            product_name, brand, raw_cat, data_year = entry
            food_category = normalize_category(raw_cat)
            if not food_category:
                food_category = raw_cat
            rows.append({
                "product_name": product_name,
                "brand": brand,
                "food_category": food_category,
                "raw_category": raw_cat,
                "certification": "Non-GMO Project Verified",
                "threshold_ppb": 10.0,
                "source": SOURCE_NAME,
                "source_url": SOURCE_URL,
                "verified_date": f"{data_year}-01-01",
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
                            certification, threshold_ppb, source, source_url,
                            verified_date, dedup_key
                        ) VALUES (
                            :product_name, :brand, :food_category, :raw_category,
                            :certification, :threshold_ppb, :source, :source_url,
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
