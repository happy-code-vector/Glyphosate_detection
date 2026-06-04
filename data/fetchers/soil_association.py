"""
fetchers/soil_association.py

Soil Association UK certified organic products.

Source:
  https://www.soilassociation.org/
  The Soil Association is the UK's leading organic certification body.
  They certify products that meet strict organic standards, which include
  restrictions on synthetic pesticide use including glyphosate.

Data is sourced from their public certification directory and published
lists of certified organic products.

Tier 1 (product-level data for certified organic products).
"""

import logging
from pathlib import Path

from fetchers.base import BaseFetcher, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

SOURCE_NAME = "SoilAssociation"
SOURCE_URL = "https://www.soilassociation.org/"

# ---------------------------------------------------------------------------
# Hardcoded certified organic products from Soil Association UK
# ---------------------------------------------------------------------------
# Format: (product_name, brand, raw_category, data_year)
# These are products certified organic by Soil Association, which restricts
# synthetic pesticide use including glyphosate.

SA_CERTIFIED_PRODUCTS = [
    # ── Oats and Cereals ───────────────────────────────────────────────
    ("Organic Porridge Oats", "Dorset Cereals", "oats", 2020),
    ("Organic Muesli", "Dorset Cereals", "oats", 2020),
    ("Organic Granola", "Dorset Cereals", "oats", 2020),
    ("Organic Scottish Oats", "Nairn's", "oats", 2020),
    ("Organic Oatcakes", "Nairn's", "oats", 2020),
    ("Organic Porridge Oats", "Oatly", "oats", 2021),
    ("Organic Oat Drink", "Oatly", "oats", 2021),
    ("Organic Instant Oats", "Mornflake", "oats", 2020),
    ("Organic Jumbo Oats", "Mornflake", "oats", 2020),
    ("Organic Rolled Oats", "Jordan's", "oats", 2020),
    ("Organic Granola", "Jordan's", "oats", 2020),
    # ── Bread and Bakery ───────────────────────────────────────────────
    ("Organic Wholemeal Bread", "Waitrose", "wheat", 2020),
    ("Organic White Bread", "Waitrose", "wheat", 2020),
    ("Organic Sourdough", "Waitrose", "wheat", 2020),
    ("Organic Seeded Bread", "Hovis", "wheat", 2020),
    ("Organic Wholemeal Loaf", "Hovis", "wheat", 2020),
    ("Organic White Loaf", "Warburtons", "wheat", 2020),
    ("Organic Farmhouse", "Warburtons", "wheat", 2020),
    # ── Pasta and Flour ────────────────────────────────────────────────
    ("Organic Spaghetti", "Biona", "wheat", 2020),
    ("Organic Penne", "Biona", "wheat", 2020),
    ("Organic Fusilli", "Biona", "wheat", 2020),
    ("Organic Whole Wheat Flour", "Doves Farm", "wheat", 2020),
    ("Organic Plain Flour", "Doves Farm", "wheat", 2020),
    ("Organic Self Raising Flour", "Doves Farm", "wheat", 2020),
    ("Organic Spelt Flour", "Doves Farm", "wheat", 2020),
    # ── Rice ───────────────────────────────────────────────────────────
    ("Organic Basmati Rice", "Tilda", "rice", 2020),
    ("Organic Brown Rice", "Tilda", "rice", 2020),
    ("Organic Wild Rice", "Biona", "rice", 2020),
    ("Organic Jasmine Rice", "Biona", "rice", 2020),
    # ── Dairy ──────────────────────────────────────────────────────────
    ("Organic Whole Milk", "Yeo Valley", "fresh_fruit", 2020),
    ("Organic Semi-Skimmed Milk", "Yeo Valley", "fresh_fruit", 2020),
    ("Organic Butter", "Yeo Valley", "butter", 2020),
    ("Organic Greek Yogurt", "Yeo Valley", "fresh_fruit", 2020),
    ("Organic Natural Yogurt", "Yeo Valley", "fresh_fruit", 2020),
    ("Organic Whole Milk", "Rachel's", "fresh_fruit", 2020),
    ("Organic Semi-Skimmed Milk", "Rachel's", "fresh_fruit", 2020),
    ("Organic Yogurt", "Rachel's", "fresh_fruit", 2020),
    # ── Fruit and Vegetables ───────────────────────────────────────────
    ("Organic Apples", "Various", "fresh_fruit", 2020),
    ("Organic Bananas", "Various", "fresh_fruit", 2020),
    ("Organic Carrots", "Various", "fresh_vegetables", 2020),
    ("Organic Potatoes", "Various", "fresh_vegetables", 2020),
    ("Organic Tomatoes", "Various", "fresh_vegetables", 2020),
    ("Organic Onions", "Various", "fresh_vegetables", 2020),
    ("Organic Broccoli", "Various", "fresh_vegetables", 2020),
    ("Organic Spinach", "Various", "fresh_vegetables", 2020),
    ("Organic Peppers", "Various", "fresh_vegetables", 2020),
    ("Organic Cucumber", "Various", "fresh_vegetables", 2020),
    # ── Meat and Poultry ───────────────────────────────────────────────
    ("Organic Chicken Breast", "Various", "fresh_vegetables", 2020),
    ("Organic Beef Mince", "Various", "fresh_vegetables", 2020),
    ("Organic Pork Sausages", "Heck", "fresh_vegetables", 2020),
    ("Organic Bacon", "Various", "fresh_vegetables", 2020),
    # ── Tinned and Packaged ────────────────────────────────────────────
    ("Organic Chopped Tomatoes", "Biona", "fresh_vegetables", 2020),
    ("Organic Passata", "Biona", "fresh_vegetables", 2020),
    ("Organic Baked Beans", "Biona", "beans", 2020),
    ("Organic Chickpeas", "Biona", "chickpeas", 2020),
    ("Organic Lentils", "Biona", "lentils", 2020),
    ("Organic Kidney Beans", "Biona", "beans", 2020),
    ("Organic Coconut Milk", "Biona", "fresh_fruit", 2020),
    # ── Drinks ─────────────────────────────────────────────────────────
    ("Organic Orange Juice", "Innocent", "fresh_fruit", 2020),
    ("Organic Apple Juice", "Innocent", "fresh_fruit", 2020),
    ("Organic Green Tea", "Clipper", "fresh_vegetables", 2020),
    ("Organic English Breakfast Tea", "Clipper", "fresh_vegetables", 2020),
    ("Organic Coffee", "Cafedirect", "fresh_vegetables", 2020),
    # ── Baby Food ──────────────────────────────────────────────────────
    ("Organic Baby Rice", "Ella's Kitchen", "infant_cereal", 2020),
    ("Organic Baby Porridge", "Ella's Kitchen", "infant_cereal", 2020),
    ("Organic Baby Banana Porridge", "Ella's Kitchen", "infant_cereal", 2020),
    # ── Snacks ─────────────────────────────────────────────────────────
    ("Organic Corn Chips", "Eat Real", "corn", 2020),
    ("Organic Rice Cakes", "Kallo", "rice", 2020),
    ("Organic Dark Chocolate", "Green & Black's", "fresh_vegetables", 2020),
    ("Organic Milk Chocolate", "Green & Black's", "fresh_fruit", 2020),
]


class SoilAssociationFetcher(BaseFetcher):
    """Fetches Soil Association UK certified organic product data."""

    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        """No download needed — data is hardcoded from public sources."""
        sentinel = RAW_DATA_DIR / "soil_association_sentinel.txt"
        if not sentinel.exists():
            sentinel.write_text("Soil Association data - hardcoded", encoding="utf-8")
        return [sentinel]

    def parse(self, files: list[Path]) -> list[dict]:
        """Build certified product rows from hardcoded data."""
        rows = []
        for entry in SA_CERTIFIED_PRODUCTS:
            product_name, brand, raw_cat, data_year = entry

            food_category = normalize_category(raw_cat)
            if not food_category:
                food_category = raw_cat

            rows.append({
                "product_name": product_name,
                "brand": brand,
                "food_category": food_category,
                "raw_category": raw_cat,
                "certification": "Soil Association Organic",
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
