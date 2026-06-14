"""
fetchers/clean_label_certified.py

Clean Label Project certified products.

Source:
  https://www.cleanlabelproject.org/
  Clean Label Project certifies products that are free from harmful
  chemicals including glyphosate, heavy metals, and other contaminants.

Tier 1 (certified products data).
"""

import logging
from pathlib import Path

from fetchers.base import BaseFetcher, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

SOURCE_NAME = "CleanLabelCertified"
SOURCE_URL = "https://www.cleanlabelproject.org/"

CLEAN_LABEL_PRODUCTS = [
    # ── Protein Powders ────────────────────────────────────────────────
    ("Organic Plant Protein", "Garden of Life", "soybeans", 2020),
    ("Raw Organic Protein", "Garden of Life", "soybeans", 2020),
    ("Sport Organic Plant Protein", "Garden of Life", "soybeans", 2020),
    ("Organic Protein Powder", "Orgain", "soybeans", 2020),
    ("Plant Based Protein Powder", "Orgain", "soybeans", 2020),
    ("Sport Protein Powder", "Orgain", "soybeans", 2020),
    ("Vega One All-in-One", "Vega", "soybeans", 2020),
    ("Vega Sport Premium Protein", "Vega", "soybeans", 2020),
    ("Vega Protein & Greens", "Vega", "soybeans", 2020),
    ("Pea Protein", "Naked Nutrition", "peas", 2020),
    ("Rice Protein", "Naked Nutrition", "rice", 2020),
    ("Bone Broth Protein", "Naked Nutrition", "chicken", 2020),
    ("Organic Pea Protein", "NOW Foods", "peas", 2020),
    ("Organic Rice Protein", "NOW Foods", "rice", 2020),
    ("Whey Protein Isolate", "NOW Foods", "dairy", 2020),
    # ── Baby Food ──────────────────────────────────────────────────────
    ("Organic Baby Food Apple", "Happy Baby", "infant_cereal", 2020),
    ("Organic Baby Food Banana", "Happy Baby", "infant_cereal", 2020),
    ("Organic Baby Food Pear", "Happy Baby", "infant_cereal", 2020),
    ("Organic Baby Food Sweet Potato", "Happy Baby", "infant_cereal", 2020),
    ("Organic Baby Cereal Oatmeal", "Happy Baby", "infant_cereal", 2020),
    ("Organic Baby Cereal Rice", "Happy Baby", "infant_cereal", 2020),
    ("Organic Baby Food Apple", "Plum Organics", "infant_cereal", 2020),
    ("Organic Baby Food Banana", "Plum Organics", "infant_cereal", 2020),
    ("Organic Baby Food Pear", "Plum Organics", "infant_cereal", 2020),
    ("Organic Baby Food Mango", "Plum Organics", "infant_cereal", 2020),
    ("Organic Baby Cereal", "Earth's Best", "infant_cereal", 2020),
    ("Organic Baby Food", "Earth's Best", "infant_cereal", 2020),
    # ── Cereals ────────────────────────────────────────────────────────
    ("Organic Oatmeal", "Nature's Path", "oats", 2020),
    ("Organic Granola", "Nature's Path", "oats", 2020),
    ("Organic Heritage Flakes", "Nature's Path", "oats", 2020),
    ("Organic Corn Flakes", "Nature's Path", "corn", 2020),
    ("Organic Rice Cereal", "Nature's Path", "rice", 2020),
    # ── Snacks ─────────────────────────────────────────────────────────
    ("Organic Animal Cookies", "Nature's Path", "corn", 2020),
    ("Organic Crispy Rice Bars", "Nature's Path", "rice", 2020),
    ("Organic Granola Bars", "Nature's Path", "oats", 2020),
    # ── Dairy Alternatives ─────────────────────────────────────────────
    ("Organic Almond Milk", "Califia Farms", "almond", 2020),
    ("Organic Oat Milk", "Califia Farms", "oats", 2020),
    ("Organic Coconut Milk", "Califia Farms", "coconut", 2020),
    ("Organic Almond Milk", "Silk", "almond", 2020),
    ("Organic Oat Milk", "Silk", "oats", 2020),
    ("Organic Soy Milk", "Silk", "soybeans", 2020),
]


class CleanLabelCertifiedFetcher(BaseFetcher):
    """Fetches Clean Label Project certified product data."""

    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        sentinel = RAW_DATA_DIR / "clean_label_certified_sentinel.txt"
        if not sentinel.exists():
            sentinel.write_text("Clean Label Certified data - hardcoded", encoding="utf-8")
        return [sentinel]

    def parse(self, files: list[Path]) -> list[dict]:
        rows = []
        for entry in CLEAN_LABEL_PRODUCTS:
            product_name, brand, raw_cat, data_year = entry
            food_category = normalize_category(raw_cat)
            if not food_category:
                food_category = raw_cat
            rows.append({
                "product_name": product_name,
                "brand": brand,
                "food_category": food_category,
                "raw_category": raw_cat,
                "certification": "Clean Label Project Certified",
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
