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
            tier2_rows = self._derive_category_aggregate(rows, report)
            all_rows.extend(tier2_rows)
        return all_rows

    def _parse_pdf(self, pdf_path: Path, report: dict) -> list[dict]:
        """
        Extract product name + ppb from EWG results table.
        EWG PDFs have multi-column tables with product name and up to 3 sample columns.
        The product name column and ppb columns shift position across reports.
        We use the header row to find the right columns dynamically.
        """
        rows = []
        found_table = False

        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                table = page.extract_table()
                if not table:
                    continue

                # Find column indices from the first 2 header rows
                product_col = None
                ppb_cols = []
                for row in table[:2]:
                    for i, cell in enumerate(row):
                        if not cell:
                            continue
                        lower = cell.lower().strip()
                        if "product name" in lower and product_col is None:
                            product_col = i
                        if lower.startswith("sample"):
                            ppb_cols.append(i)
                        if "glyphosate" in lower and "ppb" in lower:
                            # Header row for ppb section — samples follow on next row
                            pass

                if product_col is None or not ppb_cols:
                    continue

                for row_idx, row in enumerate(table):
                    # Skip header rows
                    cells_text = " ".join(str(c or "").lower() for c in row)
                    if any(h in cells_text for h in ["product name", "sample 1", "glyphosate (ppb)"]):
                        continue
                    if "type of product" in cells_text:
                        continue

                    # Get product name
                    if product_col >= len(row):
                        continue
                    product_name = str(row[product_col] or "").strip()
                    if not product_name or product_name.lower() in ("none", "nan"):
                        continue

                    # Get ppb values from all sample columns — use the highest
                    ppb_values = []
                    all_nd = True
                    for col in ppb_cols:
                        if col >= len(row):
                            continue
                        raw = str(row[col] or "").strip().lower()
                        if raw in NOT_DETECTED_PATTERNS or raw.startswith("<"):
                            continue
                        numeric = re.sub(r"[^\d.]", "", raw)
                        if numeric:
                            ppb_values.append(float(numeric))
                            all_nd = False

                    if ppb_values:
                        ppb_value = max(ppb_values)
                        below_detection = 0
                    elif all_nd:
                        ppb_value = None
                        below_detection = 1
                    else:
                        continue

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
                            "Up to 3 samples per product; highest value recorded. "
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

    def _derive_category_aggregate(self, tier1_rows: list[dict], report: dict) -> list[dict]:
        """
        Compute Tier 2 category statistics directly from the Tier 1 product results.
        Returns a list of aggregate rows (one per food_category).
        """
        if not tier1_rows:
            return []

        from collections import defaultdict
        by_category = defaultdict(list)
        for row in tier1_rows:
            by_category[row["food_category"]].append(row)

        aggregates = []
        for category, cat_rows in by_category.items():
            total = len(cat_rows)
            detected = [r for r in cat_rows if not r["below_detection"] and r["measured_ppb"]]
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
                    f"{report['label']}. Up to 3 samples per product. Method: LC-MS/MS."
                ),
                "confidence": "high",
                "raw_file_path": str(tier1_rows[0]["raw_file_path"]) if tier1_rows else "",
                "dedup_key": build_dedup_key(
                    "EWG", "aggregate", category, report["data_year"]
                ),
            })

        return aggregates

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
