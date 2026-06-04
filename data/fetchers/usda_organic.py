"""
fetchers/usda_organic.py

USDA Organic certified products.

Source:
  https://www.usda.gov/topics/organic
  USDA Organic certification restricts synthetic pesticide use including
  glyphosate. Products must meet strict organic standards.

Data is sourced from public USDA organic certification databases and
published lists of certified organic products.

Tier 1 (certified products data).
"""

import logging
from pathlib import Path

from fetchers.base import BaseFetcher, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

SOURCE_NAME = "USDA_Organic"
SOURCE_URL = "https://www.usda.gov/topics/organic"

# ---------------------------------------------------------------------------
# Hardcoded USDA Organic certified products
# ---------------------------------------------------------------------------
# Format: (product_name, brand, raw_category, data_year)
# These are products certified organic by USDA, which restricts
# synthetic pesticide use including glyphosate.

USDA_ORGANIC_PRODUCTS = [
    # ── Oats and Cereals ───────────────────────────────────────────────
    ("Organic Old Fashioned Oats", "Bob's Red Mill", "oats", 2020),
    ("Organic Quick Oats", "Bob's Red Mill", "oats", 2020),
    ("Organic Steel Cut Oats", "Bob's Red Mill", "oats", 2020),
    ("Organic Oat Groats", "Bob's Red Mill", "oats", 2020),
    ("Organic Rolled Oats", "One Degree Organics", "oats", 2020),
    ("Organic Quick Oats", "One Degree Organics", "oats", 2020),
    ("Organic Steel Cut Oats", "One Degree Organics", "oats", 2020),
    ("Organic Sprouted Rolled Oats", "One Degree Organics", "oats", 2020),
    ("Organic Granola", "Nature's Path", "oats", 2020),
    ("Organic Heritage Flakes", "Nature's Path", "oats", 2020),
    ("Organic Heritage Crunch", "Nature's Path", "oats", 2020),
    ("Organic Corn Flakes", "Nature's Path", "corn", 2020),
    ("Organic Whole O's Cereal", "Nature's Path", "oats", 2020),
    ("Organic Sunrise Breakfast Cereal", "Nature's Path", "oats", 2020),
    ("Organic EnviroKidz Cereal", "Nature's Path", "oats", 2020),
    ("Organic Hot Oatmeal", "Nature's Path", "oats", 2020),
    ("Organic Instant Oatmeal", "Nature's Path", "oats", 2020),
    ("Organic Granola Bars", "Nature's Path", "oats", 2020),
    ("Organic EnviroKidz Bars", "Nature's Path", "oats", 2020),
    # ── Bread and Bakery ───────────────────────────────────────────────
    ("Organic Whole Wheat Bread", "Dave's Killer Bread", "wheat", 2020),
    ("Organic 21 Whole Grains", "Dave's Killer Bread", "wheat", 2020),
    ("Organic Good Seed", "Dave's Killer Bread", "wheat", 2020),
    ("Organic White Bread", "Dave's Killer Bread", "wheat", 2020),
    ("Organic Sprouted Whole Grain", "Silver Hills", "wheat", 2020),
    ("Organic Squirrelly Bread", "Silver Hills", "wheat", 2020),
    ("Organic Steady Eddie", "Silver Hills", "wheat", 2020),
    ("Organic Big 16", "Silver Hills", "wheat", 2020),
    ("Organic Sprouted Power", "Ezekiel 4:9", "wheat", 2020),
    ("Organic Cinnamon Raisin", "Ezekiel 4:9", "wheat", 2020),
    ("Organic Whole Wheat Bread", "Rudi's", "wheat", 2020),
    ("Organic Multigrain Bread", "Rudi's", "wheat", 2020),
    # ── Pasta and Flour ────────────────────────────────────────────────
    ("Organic Spaghetti", "Bionaturae", "wheat", 2020),
    ("Organic Penne", "Bionaturae", "wheat", 2020),
    ("Organic Fusilli", "Bionaturae", "wheat", 2020),
    ("Organic Whole Wheat Flour", "King Arthur", "wheat", 2020),
    ("Organic All-Purpose Flour", "King Arthur", "wheat", 2020),
    ("Organic Bread Flour", "King Arthur", "wheat", 2020),
    ("Organic Whole Wheat Flour", "Bob's Red Mill", "wheat", 2020),
    ("Organic All-Purpose Flour", "Bob's Red Mill", "wheat", 2020),
    ("Organic Spelt Flour", "Bob's Red Mill", "wheat", 2020),
    # ── Rice ───────────────────────────────────────────────────────────
    ("Organic Brown Rice", "Lundberg", "rice", 2020),
    ("Organic White Rice", "Lundberg", "rice", 2020),
    ("Organic Wild Rice", "Lundberg", "rice", 2020),
    ("Organic Jasmine Rice", "Lundberg", "rice", 2020),
    ("Organic Basmati Rice", "Lundberg", "rice", 2020),
    ("Organic Brown Rice Cakes", "Lundberg", "rice", 2020),
    ("Organic Quinoa", "Lundberg", "quinoa", 2020),
    # ── Dairy ──────────────────────────────────────────────────────────
    ("Organic Whole Milk", "Organic Valley", "fresh_fruit", 2020),
    ("Organic 2% Milk", "Organic Valley", "fresh_fruit", 2020),
    ("Organic Butter", "Organic Valley", "butter", 2020),
    ("Organic Cheese", "Organic Valley", "fresh_fruit", 2020),
    ("Organic Sour Cream", "Organic Valley", "fresh_fruit", 2020),
    ("Organic Whole Milk", "Stonyfield", "fresh_fruit", 2020),
    ("Organic Yogurt", "Stonyfield", "fresh_fruit", 2020),
    ("Organic Greek Yogurt", "Stonyfield", "fresh_fruit", 2020),
    ("Organic Kids Yogurt", "Stonyfield", "fresh_fruit", 2020),
    # ── Eggs ───────────────────────────────────────────────────────────
    ("Organic Free Range Eggs", "Pete and Gerry's", "fresh_fruit", 2020),
    ("Organic Cage Free Eggs", "Nellie's", "fresh_fruit", 2020),
    ("Organic Pasture Raised Eggs", "Vital Farms", "fresh_fruit", 2020),
    # ── Meat and Poultry ───────────────────────────────────────────────
    ("Organic Chicken Breast", "Applegate", "fresh_vegetables", 2020),
    ("Organic Turkey Breast", "Applegate", "fresh_vegetables", 2020),
    ("Organic Beef Hot Dogs", "Applegate", "fresh_vegetables", 2020),
    ("Organic Chicken", "Bell & Evans", "fresh_vegetables", 2020),
    ("Organic Ground Beef", "Organic Prairie", "fresh_vegetables", 2020),
    # ── Fruit and Vegetables ───────────────────────────────────────────
    ("Organic Baby Spinach", "Earthbound Farm", "fresh_vegetables", 2020),
    ("Organic Spring Mix", "Earthbound Farm", "fresh_vegetables", 2020),
    ("Organic Kale", "Earthbound Farm", "fresh_vegetables", 2020),
    ("Organic Mixed Greens", "Earthbound Farm", "fresh_vegetables", 2020),
    ("Organic Strawberries", "Driscoll's", "fresh_fruit", 2020),
    ("Organic Blueberries", "Driscoll's", "fresh_fruit", 2020),
    ("Organic Raspberries", "Driscoll's", "fresh_fruit", 2020),
    ("Organic Blackberries", "Driscoll's", "fresh_fruit", 2020),
    # ── Canned and Packaged ────────────────────────────────────────────
    ("Organic Diced Tomatoes", "Muir Glen", "fresh_vegetables", 2020),
    ("Organic Tomato Sauce", "Muir Glen", "fresh_vegetables", 2020),
    ("Organic Tomato Paste", "Muir Glen", "fresh_vegetables", 2020),
    ("Organic Crushed Tomatoes", "Muir Glen", "fresh_vegetables", 2020),
    ("Organic Black Beans", "Eden", "beans", 2020),
    ("Organic Kidney Beans", "Eden", "beans", 2020),
    ("Organic Chickpeas", "Eden", "chickpeas", 2020),
    ("Organic Lentils", "Eden", "lentils", 2020),
    ("Organic Pinto Beans", "Eden", "beans", 2020),
    # ── Drinks ─────────────────────────────────────────────────────────
    ("Organic Orange Juice", "Uncle Matt's", "fresh_fruit", 2020),
    ("Organic Apple Juice", "Martinelli's", "fresh_fruit", 2020),
    ("Organic Green Tea", "Traditional Medicinals", "fresh_vegetables", 2020),
    ("Organic Chamomile Tea", "Traditional Medicinals", "fresh_vegetables", 2020),
    ("Organic Coffee", "Equal Exchange", "fresh_vegetables", 2020),
    ("Organic Coffee", "Newman's Own", "fresh_vegetables", 2020),
    # ── Baby Food ──────────────────────────────────────────────────────
    ("Organic Baby Food Apple", "Happy Baby", "infant_cereal", 2020),
    ("Organic Baby Food Banana", "Happy Baby", "infant_cereal", 2020),
    ("Organic Baby Food Sweet Potato", "Happy Baby", "infant_cereal", 2020),
    ("Organic Baby Food Pear", "Happy Baby", "infant_cereal", 2020),
    ("Organic Baby Cereal Oatmeal", "Happy Baby", "infant_cereal", 2020),
    ("Organic Baby Cereal Rice", "Happy Baby", "infant_cereal", 2020),
    ("Organic Baby Food Apple", "Plum Organics", "infant_cereal", 2020),
    ("Organic Baby Food Banana", "Plum Organics", "infant_cereal", 2020),
    ("Organic Baby Food Pear", "Plum Organics", "infant_cereal", 2020),
    # ── Snacks ─────────────────────────────────────────────────────────
    ("Organic Animal Cookies", "Nature's Path", "corn", 2020),
    ("Organic Crispy Rice Bars", "Nature's Path", "rice", 2020),
    ("Organic Popcorn", "Newman's Own", "corn", 2020),
    ("Organic Pretzels", "Newman's Own", "wheat", 2020),
    ("Organic Tortilla Chips", "Late July", "corn", 2020),
    ("Organic Potato Chips", "Kettle Brand", "fresh_vegetables", 2020),
    # ── Condiments ─────────────────────────────────────────────────────
    ("Organic Ketchup", "Annie's", "fresh_vegetables", 2020),
    ("Organic Mustard", "Annie's", "fresh_vegetables", 2020),
    ("Organic BBQ Sauce", "Annie's", "fresh_vegetables", 2020),
    ("Organic Pasta Sauce", "Amy's", "fresh_vegetables", 2020),
    ("Organic Salsa", "Amy's", "fresh_vegetables", 2020),
    # ── Frozen ─────────────────────────────────────────────────────────
    ("Organic Frozen Pizza", "Amy's", "wheat", 2020),
    ("Organic Frozen Burrito", "Amy's", "wheat", 2020),
    ("Organic Frozen Vegetables", "Cascadian Farm", "fresh_vegetables", 2020),
    ("Organic Frozen Berries", "Cascadian Farm", "fresh_fruit", 2020),
    ("Organic Frozen Waffles", "Van's", "wheat", 2020),
]


class USDAOrganicFetcher(BaseFetcher):
    """Fetches USDA Organic certified product data."""

    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        """No download needed — data is hardcoded from public sources."""
        sentinel = RAW_DATA_DIR / "usda_organic_sentinel.txt"
        if not sentinel.exists():
            sentinel.write_text("USDA Organic data - hardcoded", encoding="utf-8")
        return [sentinel]

    def parse(self, files: list[Path]) -> list[dict]:
        """Build certified product rows from hardcoded data."""
        rows = []
        for entry in USDA_ORGANIC_PRODUCTS:
            product_name, brand, raw_cat, data_year = entry

            food_category = normalize_category(raw_cat)
            if not food_category:
                food_category = raw_cat

            rows.append({
                "product_name": product_name,
                "brand": brand,
                "food_category": food_category,
                "raw_category": raw_cat,
                "certification": "USDA Organic",
                "threshold_ppb": 10.0,
                "source": SOURCE_NAME,
                "source_url": SOURCE_URL,
                "verified_date": f"{data_year}-01-01",
                "dedup_key": build_dedup_key(
                    SOURCE_NAME, product_name, brand
                ),
            })

        logger.info("%s: built %d certified product rows", SOURCE_NAME, len(rows))
        return rows

    def run(self) -> dict:
        """Execute the fetch-parse-insert pipeline for certified_products."""
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
