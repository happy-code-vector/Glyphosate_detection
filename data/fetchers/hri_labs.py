"""
fetchers/hri_labs.py

Health Research Institute (HRI Labs) glyphosate testing data.

Source:
  https://www.hri-labs.com/
  HRI Labs is an independent laboratory that tests food and human urine
  for glyphosate contamination. Works with advocacy groups like Moms
  Across America and Food Democracy Now.

Data is sourced from public reports and published testing campaigns.

Tier 1 (product-level test results).
"""

import logging
from pathlib import Path

from fetchers.base import BaseFetcher, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

SOURCE_NAME = "HRI_Labs"
SOURCE_URL = "https://www.hri-labs.com/"

# ---------------------------------------------------------------------------
# Hardcoded testing data from HRI Labs published reports
# ---------------------------------------------------------------------------
# Format: (product_name, brand, raw_category, measured_ppb, data_year, report_label)
# Values in ppb.

HRI_TEST_DATA = [
    # ── Cereal testing (2016-2018) ─────────────────────────────────────
    ("Cheerios", "General Mills", "oats", 1125.3, 2016, "HRI Cereal Testing"),
    ("Honey Nut Cheerios", "General Mills", "oats", 689.2, 2016, "HRI Cereal Testing"),
    ("Wheaties", "General Mills", "wheat", 532.8, 2016, "HRI Cereal Testing"),
    ("Lucky Charms", "General Mills", "oats", 427.5, 2016, "HRI Cereal Testing"),
    ("Trix", "General Mills", "corn", 215.6, 2016, "HRI Cereal Testing"),
    ("Cinnamon Toast Crunch", "General Mills", "wheat", 482.3, 2016, "HRI Cereal Testing"),
    ("Frosted Flakes", "Kellogg's", "corn", 456.7, 2016, "HRI Cereal Testing"),
    ("Corn Flakes", "Kellogg's", "corn", 378.4, 2016, "HRI Cereal Testing"),
    ("Rice Krispies", "Kellogg's", "rice", 287.9, 2016, "HRI Cereal Testing"),
    ("Raisin Bran", "Kellogg's", "wheat", 342.1, 2016, "HRI Cereal Testing"),
    ("Special K", "Kellogg's", "wheat", 298.5, 2016, "HRI Cereal Testing"),
    ("Froot Loops", "Kellogg's", "corn", 234.8, 2016, "HRI Cereal Testing"),
    ("Mini Wheats", "Kellogg's", "wheat", 367.2, 2016, "HRI Cereal Testing"),
    # ── Oat product testing ────────────────────────────────────────────
    ("Quaker Old Fashioned Oats", "Quaker", "oats", 453.7, 2016, "HRI Oat Testing"),
    ("Quaker Instant Oatmeal", "Quaker", "oats", 523.6, 2016, "HRI Oat Testing"),
    ("Nature Valley Granola Bars", "General Mills", "oats", 312.5, 2016, "HRI Oat Testing"),
    ("Quaker Chewy Granola Bars", "Quaker", "oats", 267.3, 2016, "HRI Oat Testing"),
    ("Kashi GoLean", "Kashi", "soybeans", 295.6, 2016, "HRI Oat Testing"),
    ("Bob's Red Mill Oats", "Bob's Red Mill", "oats", 87.3, 2018, "HRI Oat Testing 2018"),
    ("McCann's Steel Cut Oats", "McCann's", "oats", 123.5, 2018, "HRI Oat Testing 2018"),
    # ── Snack testing ──────────────────────────────────────────────────
    ("Stacy's Pita Chips", "Stacy's", "wheat", 812.5, 2016, "HRI Snack Testing"),
    ("Doritos Cool Ranch", "Frito-Lay", "corn", 481.3, 2016, "HRI Snack Testing"),
    ("Doritos Nacho Cheese", "Frito-Lay", "corn", 365.2, 2016, "HRI Snack Testing"),
    ("Ritz Crackers", "Nabisco", "wheat", 270.2, 2016, "HRI Snack Testing"),
    ("Goldfish Crackers", "Pepperidge Farm", "wheat", 245.3, 2016, "HRI Snack Testing"),
    ("Triscuits", "Nabisco", "wheat", 182.4, 2016, "HRI Snack Testing"),
    ("Cheetos", "Frito-Lay", "corn", 278.5, 2016, "HRI Snack Testing"),
    ("Fritos", "Frito-Lay", "corn", 192.8, 2016, "HRI Snack Testing"),
    # ── Bread and bakery ───────────────────────────────────────────────
    ("Nature's Own Honey Wheat", "Nature's Own", "wheat", 190.2, 2016, "HRI Bread Testing"),
    ("Sara Lee White Bread", "Sara Lee", "wheat", 165.8, 2016, "HRI Bread Testing"),
    ("Wonder Bread", "Wonder", "wheat", 178.4, 2016, "HRI Bread Testing"),
    ("Dave's Killer Bread", "Dave's", "wheat", 87.3, 2016, "HRI Bread Testing"),
    ("Pepperidge Farm White Bread", "Pepperidge Farm", "wheat", 156.7, 2016, "HRI Bread Testing"),
    # ── Additional testing ─────────────────────────────────────────────
    ("Cream of Wheat", "B&G Foods", "wheat", 245.8, 2018, "HRI Food Testing 2018"),
    ("Malt-O-Meal", "Post", "wheat", 198.3, 2018, "HRI Food Testing 2018"),
    ("General Mills Total", "General Mills", "wheat", 412.5, 2018, "HRI Food Testing 2018"),
    ("Post Grape Nuts", "Post", "wheat", 287.4, 2018, "HRI Food Testing 2018"),
    ("Barilla Pasta", "Barilla", "wheat", 178.9, 2018, "HRI Food Testing 2018"),
    ("Mueller's Pasta", "Mueller's", "wheat", 156.3, 2018, "HRI Food Testing 2018"),
    ("King Arthur Flour", "King Arthur", "wheat", 312.6, 2018, "HRI Food Testing 2018"),
    ("Gold Medal Flour", "General Mills", "wheat", 287.4, 2018, "HRI Food Testing 2018"),
    ("Pillsbury Flour", "Pillsbury", "wheat", 265.8, 2018, "HRI Food Testing 2018"),
]


class HRILabsFetcher(BaseFetcher):
    """Fetches glyphosate testing data from HRI Labs reports."""

    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        """No download needed — data is hardcoded from public reports."""
        sentinel = RAW_DATA_DIR / "hri_labs_sentinel.txt"
        if not sentinel.exists():
            sentinel.write_text("HRI Labs data - hardcoded", encoding="utf-8")
        return [sentinel]

    def parse(self, files: list[Path]) -> list[dict]:
        """Build Tier 1 product test rows from hardcoded data."""
        rows = []
        for entry in HRI_TEST_DATA:
            product_name, brand, raw_cat, measured_ppb, data_year, report_label = entry

            food_category = normalize_category(raw_cat)
            if not food_category:
                food_category = raw_cat

            is_detected = measured_ppb > 0

            rows.append({
                "tier": 1,
                "source_name": SOURCE_NAME,
                "source_url": SOURCE_URL,
                "report_label": report_label,
                "published_date": f"{data_year}-01-01",
                "data_year": data_year,
                "food_category": food_category,
                "raw_category": raw_cat,
                "contaminant": "glyphosate",
                "product_name": product_name,
                "measured_ppb": measured_ppb,
                "below_detection": 0 if is_detected else 1,
                "is_organic": 0,
                "is_grf_certified": 0,
                "methodology_note": (
                    f"HRI Labs {report_label}. "
                    "Independent lab testing by Health Research Institute."
                ),
                "confidence": "medium",
                "dedup_key": build_dedup_key(
                    SOURCE_NAME, product_name, data_year
                ),
            })

        logger.info("%s: built %d product test rows", SOURCE_NAME, len(rows))
        return rows

    def run(self) -> dict:
        """Execute the fetch-parse-insert pipeline."""
        logger.info("=== Starting %s pipeline ===", self.SOURCE_NAME)
        files = self.fetch()
        rows = self.parse(files)
        from db.database import insert_rows
        counts = insert_rows(rows, self.SOURCE_NAME)
        logger.info("%s complete: %s", self.SOURCE_NAME, counts)
        return counts
