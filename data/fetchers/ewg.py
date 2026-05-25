"""
fetchers/ewg.py

EWG Glyphosate Test Results — Tier 1 (named product ppb) and Tier 2 (category rates).

Sources:
  PDF tables from commissioned lab tests (Anresco Laboratories).
  Detection rates derived from the parsed product results — not hardcoded.
  All ppb values come directly from the PDF tables.
"""

import logging
import re
from pathlib import Path

import pdfplumber

from fetchers.base import BaseFetcher, download_file
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

# Every EWG report published. Add new entries here when EWG releases new rounds.
# sha256 is left empty — fill in after first run to lock the file.
EWG_REPORTS = [
    {
        "label": "EWG Oat Test 2018 Round 1",
        "url": "https://www.ewg.org/sites/default/files/u352/EWG_Glyphosate_BenchmarkTable-2_C02.pdf",
        "filename": "ewg_2018_round1.pdf",
        "published_date": "2018-07-01",
        "data_year": 2018,
        "food_category_hint": "oats",    # all rows from this PDF are oat products
        "sha256": "",
    },
    {
        "label": "EWG Oat Test 2018 Round 2",
        "url": "https://www.ewg.org/sites/default/files/u352/EWG_Glyphosate-2_Table_Full_C02.pdf",
        "filename": "ewg_2018_round2.pdf",
        "published_date": "2018-10-01",
        "data_year": 2018,
        "food_category_hint": "oats",
        "sha256": "",
    },
    {
        "label": "EWG Oat Test 2023",
        "url": "https://static.ewg.org/upload/pdf/EWG_Glyphosate-Testing_05.23_Table_C01.pdf",
        "filename": "ewg_2023.pdf",
        "published_date": "2023-04-01",
        "data_year": 2023,
        "food_category_hint": "oats",
        "sha256": "",
    },
]

# Patterns that mean "not detected" in EWG PDFs.
NOT_DETECTED_PATTERNS = {"nd", "n.d.", "<lod", "<loq", "bdl", "not detected", ""}


class EWGFetcher(BaseFetcher):
    SOURCE_NAME = "EWG"

    def fetch(self) -> list[Path]:
        paths = []
        for report in EWG_REPORTS:
            path = download_file(
                url=report["url"],
                dest_filename=report["filename"],
                expected_sha256=report["sha256"] or None,
            )
            paths.append(path)
        return paths

    def parse(self, files: list[Path]) -> list[dict]:
        all_rows = []
        for path, report in zip(files, EWG_REPORTS):
            rows = self._parse_pdf(path, report)
            all_rows.extend(rows)
            # Derive Tier 2 category aggregate from the Tier 1 rows we just parsed
            tier2 = self._derive_category_aggregate(rows, report)
            if tier2:
                all_rows.append(tier2)
        return all_rows

    def _parse_pdf(self, pdf_path: Path, report: dict) -> list[dict]:
        """
        Extract product name + ppb from EWG results table.
        EWG PDFs have a consistent two-column table: Product Name | ppb value.
        Raises ValueError if the table structure has changed.
        """
        rows = []
        found_table = False

        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                table = page.extract_table()
                if not table:
                    continue

                for row_idx, row in enumerate(table):
                    # Skip empty rows
                    if not row or not any(row):
                        continue

                    # Skip header rows (contain "product" or "sample" in first cell)
                    first = str(row[0] or "").lower().strip()
                    if any(h in first for h in ["product", "sample", "brand", "food", "ppb"]):
                        continue
                    if not first:
                        continue

                    product_name = str(row[0]).strip()
                    ppb_raw = str(row[-1]).strip() if len(row) > 1 else ""
                    ppb_clean = ppb_raw.lower().strip()

                    if ppb_clean in NOT_DETECTED_PATTERNS or ppb_clean.startswith("<"):
                        # Result is below detection limit — record as non-detect
                        ppb_value = None
                        below_detection = 1
                    else:
                        # Remove non-numeric characters except decimal point
                        numeric = re.sub(r"[^\d.]", "", ppb_raw)
                        if not numeric:
                            logger.debug(
                                "Skipping unparseable ppb '%s' in %s row %d",
                                ppb_raw, report["filename"], row_idx
                            )
                            continue
                        ppb_value = float(numeric)
                        below_detection = 0

                    # Determine category: use hint (all EWG PDFs are oat-focused),
                    # but also try to infer from product name for edge cases
                    food_category = self._infer_category(
                        product_name, report["food_category_hint"]
                    )

                    found_table = True
                    rows.append({
                        "tier": 1,
                        "source_name": "EWG",
                        "source_url": report["url"],
                        "report_label": report["label"],
                        "published_date": report["published_date"],
                        "data_year": report["data_year"],
                        "food_category": food_category,
                        "raw_category": report.get("food_category_hint", "oats"),
                        "product_name": product_name,
                        "measured_ppb": ppb_value,
                        "below_detection": below_detection,
                        "original_unit": "ppb",
                        "unit_conversion": 1.0,
                        "is_organic": int("organic" in product_name.lower()),
                        "methodology_note": (
                            "EWG commissioned independent lab test. "
                            "Lab: Anresco Laboratories, San Francisco. "
                            "Method: LC-MS/MS."
                        ),
                        "confidence": "high",
                        "raw_file_path": str(pdf_path),
                        "dedup_key": build_dedup_key(
                            "EWG", product_name, report["data_year"]
                        ),
                    })

        if not found_table:
            raise ValueError(
                f"No table data extracted from {pdf_path.name}. "
                "PDF structure may have changed — inspect the file manually."
            )

        logger.info("%s: parsed %d product rows from %s", self.SOURCE_NAME, len(rows), pdf_path.name)
        return rows

    def _derive_category_aggregate(self, tier1_rows: list[dict], report: dict) -> dict | None:
        """
        Compute Tier 2 category statistics directly from the Tier 1 product results.
        This is the correct way — no hardcoded rates.
        """
        if not tier1_rows:
            return None

        # Group by food_category (handle case where PDF has mixed categories)
        from collections import defaultdict
        by_category = defaultdict(list)
        for row in tier1_rows:
            by_category[row["food_category"]].append(row)

        aggregates = []
        for category, rows in by_category.items():
            total = len(rows)
            detected = [r for r in rows if not r["below_detection"] and r["measured_ppb"]]
            n_detected = len(detected)
            detection_rate = round(n_detected / total, 4) if total > 0 else None
            ppb_values = [r["measured_ppb"] for r in detected]
            avg_ppb = round(sum(ppb_values) / len(ppb_values), 2) if ppb_values else None
            max_ppb = max(ppb_values) if ppb_values else None

            aggregates.append({
                "tier": 2,
                "source_name": "EWG",
                "source_url": report["url"],
                "report_label": report["label"],
                "published_date": report["published_date"],
                "data_year": report["data_year"],
                "food_category": category,
                "raw_category": category,
                "samples_total": total,
                "samples_detected": n_detected,
                "detection_rate": detection_rate,
                "avg_ppb": avg_ppb,
                "max_ppb": max_ppb,
                "original_unit": "ppb",
                "unit_conversion": 1.0,
                "methodology_note": (
                    f"Aggregate derived from {total} individual product tests in "
                    f"{report['label']}. Lab: Anresco Laboratories. Method: LC-MS/MS."
                ),
                "confidence": "high",
                "raw_file_path": str(aggregates[0]["raw_file_path"]) if aggregates else "",
                "dedup_key": build_dedup_key(
                    "EWG", "aggregate", category, report["data_year"]
                ),
            })

        return aggregates[0] if len(aggregates) == 1 else aggregates if aggregates else None

    def _infer_category(self, product_name: str, hint: str) -> str:
        """
        Try to infer food category from product name.
        Falls back to the report-level hint if no match.
        """
        name_lower = product_name.lower()
        # Check for non-oat ingredients that could override the hint
        if any(t in name_lower for t in ["hummus", "chickpea", "garbanzo"]):
            return "chickpeas"
        if any(t in name_lower for t in ["lentil"]):
            return "lentils"
        if any(t in name_lower for t in ["wheat bread", "whole wheat"]):
            return "wheat"
        # Default to the report hint
        return hint
