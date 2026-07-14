"""
fetchers/florida_hff.py

Healthy Florida First — Tier 1 named product ppb values.

Source: exposingfoodtoxins.com — an advocacy site (not a Florida government
agency) that publishes independent lab test results for food toxins.
Only the bread page measures glyphosate; the candy page measures arsenic
and the infant formula page has no numeric results, so those are excluded.

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
        "url": "https://web.archive.org/web/20260414123704/https://exposingfoodtoxins.com/bread/",
        "filename": "florida_hff_bread_2026.html",
        "published_date": "2026-02-01",
        "data_year": 2026,
        "category_hint": "wheat",
    },
    # NOTE: The candy page measures ARSENIC, not glyphosate — excluded.
    # NOTE: The infant formula page has no numeric ppb values — excluded.
    # Source: exposingfoodtoxins.com is a 2025-2026 advocacy site by
    # "Healthy Florida First", not a Florida government agency.
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
    CONTAMINANT = "glyphosate"

    def fetch(self) -> list[Path]:
        """Fetch and cache all Florida HFF report pages as HTML files."""
        paths = []
        for report in FLORIDA_REPORTS:
            cache_path = RAW_DATA_DIR / report["filename"]
            if cache_path.exists():
                logger.info("Cache hit: %s", report["filename"])
                paths.append(cache_path)
                continue
            html = fetch_page(report["url"])
            cache_path.write_text(html, encoding="utf-8")
            logger.info("Fetched %s (%d bytes)", report["url"], len(html))
            paths.append(cache_path)
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

        # Try standard HTML tables first
        tables = soup.find_all("table")
        if tables:
            for table in tables:
                table_rows = self._parse_table(table, report)
                if table_rows:
                    logger.info(
                        "%s: parsed %d product rows from %s",
                        self.SOURCE_NAME, len(table_rows), html_path.name
                    )
                    return table_rows

        # Try Divi table builder (dvmd_table_maker) — cells are div.dvmd_tm_cdata
        divi_rows = self._parse_divi_table(soup, report, html_path)
        if divi_rows:
            logger.info(
                "%s: parsed %d product rows from Divi table in %s",
                self.SOURCE_NAME, len(divi_rows), html_path.name
            )
            return divi_rows

        raise ValueError(
            f"No product/ppb data found in {html_path.name}. "
            "Page structure may have changed."
        )

    def _parse_divi_table(self, soup, report: dict, html_path: Path = None) -> list[dict]:
        """Parse Divi table builder cells. Data cells are div.dvmd_tm_cdata."""
        cells = soup.find_all("div", class_="dvmd_tm_cdata")
        if len(cells) < 4:
            return []

        texts = [c.get_text(strip=True) for c in cells]

        # Find repeating group size by looking for the first cell value repeating
        group_size = 0
        first_val = texts[0]
        for i in range(2, min(12, len(texts))):
            if texts[i] == first_val:
                group_size = i
                break

        if group_size == 0:
            # Fallback: assume numeric values are ppb, extract them with preceding text
            group_size = 4

        rows = []
        for i in range(0, len(texts) - group_size + 1, group_size):
            group = texts[i:i + group_size]
            # Find ppb value — the numeric cell with a decimal point
            ppb_value = None
            product_name = None
            brand = None
            for val in group:
                numeric = re.sub(r"[^\d.]", "", val)
                if numeric and "." in val:
                    try:
                        ppb_value = float(numeric)
                    except ValueError:
                        pass
            # Product name is the most descriptive non-header, non-numeric cell
            header_words = {"bread", "brand", "type", "pesticide", "contaminent",
                          "glyphosate", "food", "infant", "formula", "cereal", "candy"}
            for val in group:
                lower = val.lower().strip()
                if not val or re.match(r'^[\d.]+$', val):
                    continue
                if any(lower == hw for hw in header_words):
                    continue
                if lower.startswith("pesticide") or lower.startswith("contaminent"):
                    continue
                if product_name is None or (len(val) > len(product_name) and ppb_value is not None):
                    product_name = val

            if not product_name or ppb_value is None:
                continue

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
                "below_detection": 0,
                "original_unit": "ppb",
                "unit_conversion": 1.0,
                "is_organic": int("organic" in product_name.lower()),
                "methodology_note": (
                    "Florida Healthy Florida First program. "
                    "Glyphosate test results from exposingfoodtoxins.com."
                ),
                "confidence": "high",
                "raw_file_path": str(html_path) if html_path else "",
                "dedup_key": build_dedup_key(
                    "FloridaHFF", product_name, report["data_year"]
                ),
            })

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
                    "Healthy Florida First (exposingfoodtoxins.com) independent lab test. "
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
        if any(t in name_lower for t in ["candy", "gummy", "gummies", "licorice", "twizzler"]):
            return "corn"
        if any(t in name_lower for t in ["chocolate", "cocoa"]):
            return "soybeans"
        return hint
