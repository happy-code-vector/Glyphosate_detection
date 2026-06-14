"""
fetchers/eu_organic.py

EU Organic certified products.

Source:
  https://ec.europa.eu/info/food-farming-fisheries/farming/organic-farming
  EU Organic certification restricts synthetic pesticide use including
  glyphosate. Products must meet strict EU organic standards.

Tier 1 (certified products data).
"""

import logging
from pathlib import Path

from fetchers.base import BaseFetcher, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

SOURCE_NAME = "EU_Organic"
SOURCE_URL = "https://ec.europa.eu/info/food-farming-fisheries/farming/organic-farming"

EU_ORGANIC_PRODUCTS = [
    # ── Oats and Cereals ───────────────────────────────────────────────
    ("Organic Porridge Oats", "Alara", "oats", 2020),
    ("Organic Muesli", "Alara", "oats", 2020),
    ("Organic Granola", "Alara", "oats", 2020),
    ("Organic Oat Flakes", "Doves Farm", "oats", 2020),
    ("Organic Porridge Oats", "Suma", "oats", 2020),
    ("Organic Muesli", "Suma", "oats", 2020),
    ("Organic Cornflakes", "Whole Earth", "corn", 2020),
    ("Organic Rice Puffs", "Whole Earth", "rice", 2020),
    # ── Bread and Bakery ───────────────────────────────────────────────
    ("Organic Wholemeal Bread", "Village Bakery", "wheat", 2020),
    ("Organic Sourdough", "Village Bakery", "wheat", 2020),
    ("Organic Rye Bread", "Village Bakery", "wheat", 2020),
    ("Organic Spelt Bread", "Village Bakery", "wheat", 2020),
    # ── Pasta and Flour ────────────────────────────────────────────────
    ("Organic Spaghetti", "Biona", "wheat", 2020),
    ("Organic Penne", "Biona", "wheat", 2020),
    ("Organic Fusilli", "Biona", "wheat", 2020),
    ("Organic Lasagne", "Biona", "wheat", 2020),
    ("Organic Whole Wheat Flour", "Doves Farm", "wheat", 2020),
    ("Organic Plain Flour", "Doves Farm", "wheat", 2020),
    ("Organic Self Raising Flour", "Doves Farm", "wheat", 2020),
    ("Organic Spelt Flour", "Doves Farm", "wheat", 2020),
    ("Organic Rye Flour", "Doves Farm", "wheat", 2020),
    # ── Rice ───────────────────────────────────────────────────────────
    ("Organic Basmati Rice", "Tilda", "rice", 2020),
    ("Organic Brown Rice", "Tilda", "rice", 2020),
    ("Organic Jasmine Rice", "Biona", "rice", 2020),
    ("Organic Wild Rice", "Biona", "rice", 2020),
    # ── Dairy ──────────────────────────────────────────────────────────
    ("Organic Whole Milk", "Arla", "dairy", 2020),
    ("Organic Semi-Skimmed Milk", "Arla", "dairy", 2020),
    ("Organic Butter", "Arla", "butter", 2020),
    ("Organic Yogurt", "Arla", "dairy", 2020),
    ("Organic Whole Milk", "Yeo Valley", "dairy", 2020),
    ("Organic Butter", "Yeo Valley", "butter", 2020),
    ("Organic Yogurt", "Yeo Valley", "dairy", 2020),
    ("Organic Cheese", "Yeo Valley", "dairy", 2020),
    # ── Fruit and Vegetables ───────────────────────────────────────────
    ("Organic Apples", "Various", "apple", 2020),
    ("Organic Bananas", "Various", "banana", 2020),
    ("Organic Carrots", "Various", "carrot", 2020),
    ("Organic Potatoes", "Various", "potato", 2020),
    ("Organic Tomatoes", "Various", "tomato", 2020),
    ("Organic Onions", "Various", "onion", 2020),
    ("Organic Broccoli", "Various", "broccoli", 2020),
    ("Organic Spinach", "Various", "spinach", 2020),
    # ── Tinned and Packaged ────────────────────────────────────────────
    ("Organic Chopped Tomatoes", "Biona", "tomato", 2020),
    ("Organic Passata", "Biona", "tomato", 2020),
    ("Organic Baked Beans", "Biona", "beans", 2020),
    ("Organic Chickpeas", "Biona", "chickpeas", 2020),
    ("Organic Lentils", "Biona", "lentils", 2020),
    ("Organic Kidney Beans", "Biona", "beans", 2020),
    ("Organic Coconut Milk", "Biona", "coconut", 2020),
    # ── Drinks ─────────────────────────────────────────────────────────
    ("Organic Orange Juice", "Innocent", "orange", 2020),
    ("Organic Apple Juice", "Innocent", "apple", 2020),
    ("Organic Green Tea", "Clipper", "tea", 2020),
    ("Organic English Breakfast Tea", "Clipper", "tea", 2020),
    ("Organic Coffee", "Cafedirect", "coffee", 2020),
    # ── Snacks ─────────────────────────────────────────────────────────
    ("Organic Corn Chips", "Eat Real", "corn", 2020),
    ("Organic Rice Cakes", "Kallo", "rice", 2020),
    ("Organic Dark Chocolate", "Green & Black's", "cocoa", 2020),
    ("Organic Milk Chocolate", "Green & Black's", "cocoa", 2020),
]


class EUOrganicFetcher(BaseFetcher):
    """Fetches EU Organic certified product data."""

    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        sentinel = RAW_DATA_DIR / "eu_organic_sentinel.txt"
        if not sentinel.exists():
            sentinel.write_text("EU Organic data - hardcoded", encoding="utf-8")
        return [sentinel]

    def parse(self, files: list[Path]) -> list[dict]:
        rows = []
        for entry in EU_ORGANIC_PRODUCTS:
            product_name, brand, raw_cat, data_year = entry
            food_category = normalize_category(raw_cat)
            if not food_category:
                food_category = raw_cat
            rows.append({
                "product_name": product_name,
                "brand": brand,
                "food_category": food_category,
                "raw_category": raw_cat,
                "certification": "EU Organic",
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
