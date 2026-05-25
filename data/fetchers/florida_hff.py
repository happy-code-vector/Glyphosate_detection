"""
fetchers/florida_hff.py

Florida Healthy Florida First — Tier 1 named product ppb values.

Florida publishes glyphosate test results as HTML tables in press releases
on floridahealth.gov and exposingfoodtoxins.com. This fetcher scrapes
those tables and extracts all product results.

No values are hardcoded. All ppb values come from the live pages.
If a page structure changes, the parser raises ValueError rather than
silently returning wrong data.
"""

import logging
import re
from pathlib import Path
from datetime import date

from bs4 import BeautifulSoup

from fetchers.base import BaseFetcher, fetch_page
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

RAW_DATA_DIR = Path(__file__).parent.parent / "raw_data"

# Known Florida HFF report pages.
# Add new entries as Florida publishes more reports.
# category_hint: canonical food_category key that applies to this report.
FLORIDA_REPORTS = [
    {
        "label": "Florida HFF Bread Glyphosate 2026",
        "url": "https://www.exposingfoodtoxins.com/glyphosate-bread",
        "fallback_url": "https://www.floridahealth.gov",
        "filename": "florida_hff_bread_2026.html",
        "published_date": "2026-02-01",
        "data_year": 2026,
        "category_hint": "wheat",
    },
    {
        "label": "Florida HFF Infant Formula 2026",
        "url": "https://www.exposingfoodtoxins.com/glyphosate-infant-formula",
        "fallback_url": "https://www.floridahealth.gov",
        "filename": "florida_hff_infant_2026.html",
        "published_date": "2026-01-01",
        "data_year": 2026,
        "category_hint": "infant_cereal",
    },
]

# Column header patterns that indicate the ppb/result column
PPB_COLUMN_PATTERNS = [
    r"ppb", r"glyphosate.*level", r"result", r"concentration",
    r"µg/kg", r"mg/kg", r"amount", r"detected"
]

# Column header patterns that indicate the product name column
PRODUCT_COLUMN_PATTERNS = [
    r"product", r"brand", r"item", r"food", r"sample", r"name"
]


class FloridaHFFetcher(BaseFetcher):
    SOURCE_NAME = "FloridaHFF"

    def fetch(self) -> list[Path]:
        """Fetch and cache all Florida HFF report pages as HTML files."""
        paths = []
        for report in FLORIDA_REPORTS:
            cache_path = RAW_DATA_DIR / report["filename"]
            if cache_path.exists():
                logger.info("Cache hit: %s", report["filename"])
                paths.append(cache_path)
                continue
            try:
                html = fetch_page(report["url"])
                cache_path.write_text(html, encoding="utf-8")
                logger.info("Fetched %s (%d bytes)", report["url"], len(html))
                paths.append(cache_path)
            except Exception as e:
                # Try fallback URL if primary fails
                if report.get("fallback_url"):
                    logger.warning(
                        "Primary URL failed (%s), trying fallback: %s", e, report["fallback_url"]
                    )
                    try:
                        html = fetch_page(report["fallback_url"])
                        cache_path.write_text(html, encoding="utf-8")
                        paths.append(cache_path)
                    except Exception as e2:
                        logger.error("Both URLs failed for %s: %s", report["label"], e2)
                        raise RuntimeError(
                            f"Could not fetch {report['label']}: {e2}"
                        ) from e2
                else:
                    raise
        return paths

    def parse(self, files: list[Path]) -> list[dict]:
        all_rows = []
        for path, report in zip(files, FLORIDA_REPORTS):
            rows = self._parse_html(path, report)
            all_rows.extend(rows)
        return all_rows

    def _parse_html(self, html_path: Path, report: dict) -> list[dict]:
        html = html_path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")

        tables = soup.find_all("table")
        if not tables:
            raise ValueError(
                f"No <table> elements found in {html_path.name}. "
                "Page structure may have changed."
            )

        rows = []
        for table in tables:
            table_rows = self._parse_table(table, report)
            if table_rows:
                rows.extend(table_rows)
                break  # Use first table that yields results

        if not rows:
            raise ValueError(
                f"No valid product/ppb rows extracted from {html_path.name}. "
                "Inspect the page — table structure or column names may have changed."
            )

        logger.info(
            "%s: parsed %d product rows from %s",
            self.SOURCE_NAME, len(rows), html_path.name
        )
        return rows

    def _parse_table(self, table, report: dict) -> list[dict]:
        """
        Parse a BeautifulSoup table element.
        Dynamically identifies product name and ppb columns from headers.
        """
        headers = []
        header_row = table.find("tr")
        if header_row:
            headers = [
                th.get_text(strip=True).lower()
                for th in header_row.find_all(["th", "td"])
            ]

        if not headers:
            return []

        # Identify column indices
        product_col = self._find_column(headers, PRODUCT_COLUMN_PATTERNS)
        ppb_col = self._find_column(headers, PPB_COLUMN_PATTERNS)

        if product_col is None or ppb_col is None:
            logger.debug(
                "Could not identify product/ppb columns in table. Headers: %s", headers
            )
            return []

        rows = []
        for tr in table.find_all("tr")[1:]:  # skip header
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) <= max(product_col, ppb_col):
                continue

            product_name = cells[product_col].strip()
            ppb_raw = cells[ppb_col].strip()

            if not product_name or not ppb_raw:
                continue

            # Parse ppb value
            ppb_clean = ppb_raw.lower().replace(",", "").strip()
            if any(nd in ppb_clean for nd in ["nd", "not detect", "<lod", "<loq", "bdl"]):
                ppb_value = None
                below_detection = 1
            else:
                # Handle formats: "190.23 ppb", "190.23", "<5", ">0.01 mg/kg"
                numeric = re.sub(r"[^\d.]", "", ppb_clean.split()[0])
                if not numeric:
                    continue
                ppb_value = float(numeric)
                # Convert mg/kg to ppb if needed (1 mg/kg = 1000 ppb)
                original_unit = "ppb"
                unit_conversion = 1.0
                if "mg/kg" in ppb_raw.lower():
                    ppb_value = ppb_value * 1000
                    original_unit = "mg/kg"
                    unit_conversion = 1000.0
                elif "µg/kg" in ppb_raw.lower() or "ug/kg" in ppb_raw.lower():
                    original_unit = "µg/kg"
                    unit_conversion = 1.0  # µg/kg == ppb
                below_detection = 0

            # Infer category from product name, falling back to report hint
            raw_cat = self._infer_raw_category(product_name, report["category_hint"])
            food_category = normalize_category(raw_cat) or report["category_hint"]

            rows.append({
                "tier": 1,
                "source_name": "FloridaHFF",
                "source_url": report["url"],
                "report_label": report["label"],
                "published_date": report["published_date"],
                "data_year": report["data_year"],
                "food_category": food_category,
                "raw_category": raw_cat,
                "product_name": product_name,
                "measured_ppb": ppb_value,
                "below_detection": below_detection,
                "original_unit": original_unit if "original_unit" in dir() else "ppb",
                "unit_conversion": unit_conversion if "unit_conversion" in dir() else 1.0,
                "is_organic": int("organic" in product_name.lower()),
                "methodology_note": (
                    "Florida Dept of Health Healthy Florida First program lab test. "
                    "Note: detailed methodology not fully disclosed in public report."
                ),
                "confidence": "high",
                "raw_file_path": str(html_path),
                "dedup_key": build_dedup_key(
                    "FloridaHFF", product_name, report["data_year"]
                ),
            })

        return rows

    def _find_column(self, headers: list[str], patterns: list[str]) -> int | None:
        for i, header in enumerate(headers):
            for pattern in patterns:
                if re.search(pattern, header, re.IGNORECASE):
                    return i
        return None

    def _infer_raw_category(self, product_name: str, hint: str) -> str:
        name_lower = product_name.lower()
        if any(t in name_lower for t in ["bread", "toast", "loaf", "wheat"]):
            return "bread"
        if any(t in name_lower for t in ["oat", "cereal", "granola"]):
            return "oats"
        if any(t in name_lower for t in ["pasta", "noodle", "spaghetti"]):
            return "pasta"
        if any(t in name_lower for t in ["infant", "baby", "formula", "toddler"]):
            return "infant food"
        return hint
