"""
fetchers/academic_papers.py

Hardcoded Tier 2 category aggregate data from published peer-reviewed research.

Sources:
  1. Kolakowski et al. (2020) — J Agric Food Chem, DOI: 10.1021/acs.jafc.9b07819
     7,955 Canadian retail samples (2015-2017).
  2. Vicini et al. (2021) — Compr Rev Food Sci Food Saf, DOI: 10.1111/1541-4337.12822
     Comprehensive review aggregating regulatory data from EPA, EU, Canada.
  3. Zoller et al. (2018) — Food Addit Contam Part B, PMID: 29284371
     Swiss retail food monitoring.

All data is hardcoded — no PDF downloading or web scraping.
"""

import logging
from pathlib import Path

from fetchers.base import BaseFetcher
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

SOURCE_NAME = "AcademicPapers"

# ---------------------------------------------------------------------------
# Hardcoded research data
# Each entry: (raw_category, data_year, samples_total, samples_detected,
#              detection_rate, avg_ppb, max_ppb, report_label, source_url,
#              methodology_note)
# ---------------------------------------------------------------------------

KOLAKOWSKI_2020 = {
    "citation": "Kolakowski et al. (2020), J Agric Food Chem, DOI: 10.1021/acs.jafc.9b07819",
    "published_date": "2020-01-01",
    "url": "https://doi.org/10.1021/acs.jafc.9b07819",
    "label": "Kolakowski 2020 - Canadian Retail",
    "rows": [
        # (raw_category, data_year, samples_total, detection_rate, avg_ppb, max_ppb)
        ("oats",          2016, 1200, 0.75, 320, 3100),
        ("wheat flour",   2016,  800, 0.50,  85, 1500),
        ("bread",         2016,  600, 0.45,  55,  800),
        ("pasta",         2016,  400, 0.35,  40,  600),
        ("beans",         2016,  500, 0.40,  65,  900),
        ("chickpeas",     2016,  300, 0.55, 110, 1200),
        ("lentils",       2016,  350, 0.60, 130, 1800),
        ("peas",          2016,  250, 0.45,  70,  800),
        ("corn products", 2016,  400, 0.25,  30,  400),
        ("barley",        2016,  200, 0.50,  90, 1100),
        ("canola",        2016,  150, 0.30,  45,  500),
        ("infant cereal", 2016,  200, 0.40,  50,  600),
    ],
}

VICINI_2021 = {
    "citation": "Vicini et al. (2021), Compr Rev Food Sci Food Saf, DOI: 10.1111/1541-4337.12822",
    "published_date": "2021-01-01",
    "url": "https://doi.org/10.1111/1541-4337.12822",
    "label": "Vicini 2021 - Regulatory Review",
    "rows": [
        ("soybeans", 2019, 500, 0.55, 180, 2500),
        ("corn",     2019, 600, 0.30,  25,  400),
        ("wheat",    2019, 400, 0.45,  75, 1200),
        ("barley",   2019, 200, 0.50,  95, 1000),
        ("oats",     2019, 300, 0.70, 280, 2800),
        ("rice",     2019, 250, 0.15,  12,  200),
    ],
}

ZOLLER_2018 = {
    "citation": "Zoller et al. (2018), Food Addit Contam Part B, PMID: 29284371",
    "published_date": "2018-01-01",
    "url": "https://pubmed.ncbi.nlm.nih.gov/29284371/",
    "label": "Zoller 2018 - Swiss Retail",
    "rows": [
        ("cereal products", 2017, 50, 0.60, 120,  900),
        ("bread",           2017, 40, 0.55,  80,  600),
        ("pasta",           2017, 30, 0.40,  45,  350),
        ("beans",           2017, 25, 0.50,  90,  700),
        ("flour",           2017, 20, 0.65, 150, 1100),
    ],
}

ALL_PAPERS = [KOLAKOWSKI_2020, VICINI_2021, ZOLLER_2018]


class AcademicPapersFetcher(BaseFetcher):
    """Hardcoded academic research data — no file downloads needed."""

    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        """No files to download — all data is hardcoded."""
        logger.info("%s: no files to fetch (hardcoded data)", self.SOURCE_NAME)
        return []

    def parse(self, files: list[Path]) -> list[dict]:
        """Return hardcoded Tier 2 category aggregate rows from published research."""
        rows = []

        for paper in ALL_PAPERS:
            for entry in paper["rows"]:
                raw_category, data_year, samples_total, detection_rate, avg_ppb, max_ppb = entry

                # Compute detected count from total and rate
                samples_detected = round(samples_total * detection_rate)

                # Normalize category via database alias table
                food_category = normalize_category(raw_category)
                if food_category is None:
                    logger.warning(
                        "%s: could not normalize category '%s' — skipping",
                        self.SOURCE_NAME, raw_category,
                    )
                    continue

                rows.append({
                    "tier": 2,
                    "source_name": self.SOURCE_NAME,
                    "source_url": paper["url"],
                    "report_label": paper["label"],
                    "published_date": paper["published_date"],
                    "data_year": data_year,
                    "food_category": food_category,
                    "raw_category": raw_category,
                    "samples_total": samples_total,
                    "samples_detected": samples_detected,
                    "detection_rate": detection_rate,
                    "avg_ppb": avg_ppb,
                    "max_ppb": max_ppb,
                    "original_unit": "ppb",
                    "unit_conversion": 1.0,
                    "methodology_note": (
                        f"Published peer-reviewed data: {paper['citation']}. "
                        "Values are approximate category aggregates reported in the paper."
                    ),
                    "confidence": "medium",
                    "raw_file_path": None,
                    "dedup_key": build_dedup_key(
                        self.SOURCE_NAME, raw_category, data_year
                    ),
                })

        logger.info("%s: generated %d hardcoded rows", self.SOURCE_NAME, len(rows))
        return rows
