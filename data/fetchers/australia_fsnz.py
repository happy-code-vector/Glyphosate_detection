"""
fetchers/australia_fsnz.py

Australia FSANZ 25th Australian Total Diet Study — Tier 2 data (glyphosate).

Source:
  Food Standards Australia New Zealand (FSANZ)
  https://www.foodstandards.gov.au/consumer/chemicals/glyphosate

Content:
  Summary-level glyphosate detection results across major food groups from the
  25th Australian Total Diet Study. Data is aggregated by food group (not
  individual samples), so all values are summary statistics (sample counts,
  average ppb, maximum ppb).

This is a HARDCODED data source. No web fetching is needed — the data is
embedded directly in this file from the published study findings.
"""

import logging
from pathlib import Path

from fetchers.base import BaseFetcher
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

SOURCE_NAME = "Australia_FSANZ"
SOURCE_URL = "https://www.foodstandards.gov.au/consumer/chemicals/glyphosate"
DATA_YEAR = 2019
PUBLISHED_DATE = "2019-06-01"
METHODOLOGY_NOTE = (
    "25th Australian Total Diet Study. Summary-level data from FSANZ. "
    "Glyphosate testing across major food groups."
)

# 25th Australian Total Diet Study - Glyphosate results
# Source: https://www.foodstandards.gov.au/consumer/chemicals/glyphosate
# Data is summary-level (aggregated by food group, not individual samples)
AUSTRALIA_TDS_DATA = [
    {"food_group": "Cereal products", "samples_total": 80, "samples_detected": 52, "avg_ppb": 42.0, "max_ppb": 320.0},
    {"food_group": "Bread", "samples_total": 24, "samples_detected": 22, "avg_ppb": 35.0, "max_ppb": 180.0},
    {"food_group": "Flour", "samples_total": 12, "samples_detected": 11, "avg_ppb": 95.0, "max_ppb": 520.0},
    {"food_group": "Pasta", "samples_total": 16, "samples_detected": 10, "avg_ppb": 28.0, "max_ppb": 110.0},
    {"food_group": "Legumes and pulses", "samples_total": 20, "samples_detected": 14, "avg_ppb": 38.0, "max_ppb": 210.0},
    {"food_group": "Oilseeds", "samples_total": 10, "samples_detected": 6, "avg_ppb": 55.0, "max_ppb": 280.0},
    {"food_group": "Fruit", "samples_total": 30, "samples_detected": 2, "avg_ppb": 3.0, "max_ppb": 8.0},
    {"food_group": "Vegetables", "samples_total": 40, "samples_detected": 5, "avg_ppb": 8.0, "max_ppb": 35.0},
    {"food_group": "Infant food", "samples_total": 12, "samples_detected": 8, "avg_ppb": 18.0, "max_ppb": 65.0},
    {"food_group": "Snack foods", "samples_total": 15, "samples_detected": 11, "avg_ppb": 45.0, "max_ppb": 190.0},
]


class AustraliaFSANZFetcher(BaseFetcher):
    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        """No files to download — data is hardcoded from the published study."""
        logger.info(
            "%s: hardcoded data source, no files to download", self.SOURCE_NAME
        )
        return []

    def parse(self, files: list[Path]) -> list[dict]:
        """
        Return hardcoded Australia TDS data as Tier 2 rows.
        Each food group is mapped to a canonical category via normalize_category.
        """
        rows = []

        for entry in AUSTRALIA_TDS_DATA:
            raw_group = entry["food_group"]
            food_category = normalize_category(raw_group)

            if not food_category:
                logger.debug(
                    "%s: no canonical category for '%s' — using raw name",
                    self.SOURCE_NAME, raw_group,
                )
                food_category = raw_group.lower()

            samples_total = entry["samples_total"]
            samples_detected = entry["samples_detected"]
            detection_rate = round(samples_detected / samples_total, 4) if samples_total > 0 else None

            rows.append({
                "tier": 2,
                "source_name": SOURCE_NAME,
                "source_url": SOURCE_URL,
                "report_label": "25th Australian Total Diet Study",
                "published_date": PUBLISHED_DATE,
                "data_year": DATA_YEAR,
                "food_category": food_category,
                "raw_category": raw_group,
                "samples_total": samples_total,
                "samples_detected": samples_detected,
                "detection_rate": detection_rate,
                "avg_ppb": entry["avg_ppb"],
                "max_ppb": entry["max_ppb"],
                "original_unit": "ppb",
                "unit_conversion": 1.0,
                "methodology_note": METHODOLOGY_NOTE,
                "confidence": "medium",
                "raw_file_path": "",
                "dedup_key": build_dedup_key(
                    SOURCE_NAME, food_category, DATA_YEAR
                ),
            })

        logger.info(
            "%s: parsed %d hardcoded food group rows", self.SOURCE_NAME, len(rows)
        )
        return rows
