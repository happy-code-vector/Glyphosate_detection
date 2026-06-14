"""
fetchers/ca_dpr.py

California Department of Pesticide Regulation — Marketplace Surveillance Program.
Tier 2 (category aggregate) glyphosate residue data.

Source: CA DPR Pesticide Residue Monitoring Program
URL: https://www.cdpr.ca.gov/data-and-reports/residue-monitoring/
Reports directory: https://www.cdpr.ca.gov/reports-directory/  (filter: Residue)

DPR publishes annual residue monitoring results with commodity, pesticide,
and residue level data. This fetcher downloads per-year data files (CSV or
Excel), filters for glyphosate detections, and aggregates by canonical
food category.

MANUAL DATA SOURCE (as of 2025-05):
  DPR restructured its website around 2024.  The old /docs/pml/ URLs are all
  404.  The new site does NOT expose machine-downloadable CSV/XLSX files for
  residue monitoring data.  The reports directory is a client-side JavaScript
  application that lists entries like "Annual Residue Data 2020/2021/2022" but
  provides no direct download links.  No pesticide residue food monitoring
  dataset exists on data.ca.gov.

  TO USE THIS FETCHER: manually download annual residue data files from
  DPR's reports directory (https://www.cdpr.ca.gov/reports-directory/ —
  filter by Category: Residue) or via a public records request through
  DPR's NextRequest portal.  Place the files in data/raw_data/ named as
  specified in CA_DPR_REPORTS (e.g. ca_dpr_2020_residue.csv,
  ca_dpr_2021_residue.csv, etc.).

  The fetcher will detect and parse any manually placed files.  If no data
  files are found, it logs a clear warning and returns zero rows.

No values are hardcoded. All residue levels come from downloaded data files.
"""

import logging
from collections import defaultdict
from pathlib import Path

import pandas as pd

from fetchers.base import BaseFetcher, RAW_DATA_DIR, fetch_page, download_file
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# CA DPR reports registry — one entry per monitoring year.
# Add new entries as DPR publishes new annual data.
#
# MANUAL DATA REQUIRED (as of 2025-05):
#   DPR's restructured website does not expose direct CSV/XLSX download
#   links for residue data.  To populate this source, manually download
#   data from the reports directory or via a DPR public records request
#   and place files in data/raw_data/ with the filenames listed below.
#
#   Reports directory (filter: Category = Residue):
#     https://www.cdpr.ca.gov/reports-directory/
#   Public records portal:
#     https://cdpr.nextrequest.com/
# ─────────────────────────────────────────────────────────────────────
CA_DPR_REPORTS = [
    {
        "label": "CA DPR Pesticide Residue Monitoring 2020",
        "year": 2020,
        "filename": "ca_dpr_2020_residue.xlsx",
        "source_url": "https://www.cdpr.ca.gov/data-and-reports/residue-monitoring/",
        "report_page_url": "https://www.cdpr.ca.gov/report/annual-residue-data-2020/",
        "published_date": "2021-06-01",
        "data_year": 2020,
    },
    {
        "label": "CA DPR Pesticide Residue Monitoring 2021",
        "year": 2021,
        "filename": "ca_dpr_2021_residue.xlsx",
        "source_url": "https://www.cdpr.ca.gov/data-and-reports/residue-monitoring/",
        "report_page_url": "https://www.cdpr.ca.gov/report/annual-residue-data-2021/",
        "published_date": "2022-06-01",
        "data_year": 2021,
    },
    {
        "label": "CA DPR Pesticide Residue Monitoring 2022",
        "year": 2022,
        "filename": "ca_dpr_2022_residue.xlsx",
        "source_url": "https://www.cdpr.ca.gov/data-and-reports/residue-monitoring/",
        "report_page_url": "https://www.cdpr.ca.gov/report/annual-residue-data-2022/",
        "published_date": "2023-06-01",
        "data_year": 2022,
    },
    {
        "label": "CA DPR Pesticide Residue Monitoring 2023",
        "year": 2023,
        "filename": "ca_dpr_2023_residue.csv",
        "source_url": "https://www.cdpr.ca.gov/data-and-reports/residue-monitoring/",
        "published_date": "2024-06-01",
        "data_year": 2023,
    },
]

# Reference URLs for manual data retrieval.
CA_DPR_URL_PATTERNS = {
    "residue_landing": "https://www.cdpr.ca.gov/data-and-reports/residue-monitoring/",
    "reports_directory": "https://www.cdpr.ca.gov/reports-directory/",
    "public_records_portal": "https://cdpr.nextrequest.com/",
}

# Supported data file extensions for manual placement.
_DPR_FILE_EXTENSIONS = [".csv", ".xlsx", ".xls"]

# CA DPR commodity name → raw category hint for normalize_category.
# These cover the uppercase, comma-separated style DPR uses.
CA_DPR_COMMODITY_MAP = {
    "LETTUCE, HEAD": "lettuce",
    "LETTUCE, LEAF": "lettuce",
    "LETTUCE, ROMAINE": "lettuce",
    "LETTUCE": "lettuce",
    "SPINACH": "spinach",
    "CELERY": "celery",
    "TOMATOES": "tomato",
    "TOMATO": "tomato",
    "PEPPERS, BELL": "pepper",
    "PEPPERS": "pepper",
    "CUCUMBERS": "cucumber",
    "BROCCOLI": "broccoli",
    "CARROTS": "carrot",
    "POTATOES": "potato",
    "ONIONS": "onion",
    "CABBAGE": "cabbage",
    "MUSHROOMS": "mushroom",
    "STRAWBERRIES": "strawberry",
    "GRAPES, TABLE": "grape",
    "GRAPES": "grape",
    "ORANGES": "orange",
    "APPLES": "apple",
    "PEACHES": "peach",
    "PEARS": "pear",
    "BANANAS": "banana",
    "OATS": "oats",
    "OAT FLOUR": "oats",
    "WHEAT FLOUR": "wheat",
    "WHEAT": "wheat",
    "CORN, SWEET": "corn",
    "CORN": "corn",
    "SOYBEANS": "soybeans",
    "BARLEY": "barley",
    "RICE": "rice",
    "BEANS, DRY": "beans",
    "BEANS, GREEN": "beans",
    "BEANS": "beans",
    "LENTILS": "lentils",
    "CHICKPEAS": "chickpeas",
    "BLUEBERRIES": "blueberries",
    "CHERRIES": "cherries",
    "RASPBERRIES": "raspberries",
    "CANTALOUPE": "cantaloupe",
    "WATERMELON": "watermelon",
    "MELONS": "melon",
    "KALE": "kale",
    "CHARD": "chard",
    "ARUGULA": "arugula",
    "CILANTRO": "cilantro",
    "BASIL": "basil",
    "PARSLEY": "parsley",
    "MINT": "mint",
    "HERBS": "herbs",
    "MANGOES": "mango",
    "PINEAPPLE": "pineapple",
    "AVOCADOS": "avocado",
    "LIMES": "lime",
    "LEMONS": "lemon",
    "GRAPEFRUIT": "grapefruit",
    "TANGERINES": "orange",
    "PLUMS": "plum",
    "NECTARINES": "nectarine",
    "APRICOTS": "apricot",
    "FIGS": "fig",
    "KIWI": "kiwi",
    "PAPAYA": "papaya",
    "ASPARAGUS": "asparagus",
    "ARTICHOKES": "artichoke",
    "BEETS": "beet",
    "CAULIFLOWER": "cauliflower",
    "EGGPLANT": "eggplant",
    "GREEN BEANS": "beans",
    "SNAP PEAS": "peas",
    "SQUASH": "squash",
    "ZUCCHINI": "zucchini",
    "TURNIPS": "turnip",
    "RADISHES": "radish",
}

# Column header patterns for dynamic detection.
_PESTICIDE_COL_PATTERNS = [
    "pesticide", "pest_name", "chem_name", "chemical", "compound",
    "substance", "analyte", "active_ingredient", "pestcode",
]
_COMMODITY_COL_PATTERNS = [
    "commodity", "commname", "prodname", "product", "food",
    "sample_type", "matrix", "crop",
]
_RESULT_COL_PATTERNS = [
    "result", "concentration", "level", "residue", "value",
    "amount", "measured", "ppm", "mg_kg", "mg/kg", "ppb",
    "detect", "find", "quant",
]
_UNIT_COL_PATTERNS = [
    "unit", "units", "reportunit", "result_unit", "report_unit",
]


class CADPRFetcher(BaseFetcher):
    """California DPR Marketplace Surveillance residue monitoring fetcher.

    As of 2025-05, DPR does not expose machine-downloadable residue data files.
    This fetcher checks for manually placed data files in raw_data/ and parses
    them if found.  It does NOT attempt to scrape DPR's website because:
      - The landing page has no data download links.
      - The reports directory is client-side rendered (JavaScript) with no
        direct CSV/XLSX download links for residue data entries.
      - All legacy /docs/pml/ URLs return 404.

    To populate this source, manually place data files in raw_data/ named as
    specified in CA_DPR_REPORTS (e.g. ca_dpr_2020_residue.csv).
    """

    SOURCE_NAME = "CA_DPR"

    def fetch(self) -> list[Path]:
        """
        Download CA DPR residue data files. Tries auto-download from
        DPR report pages for 2020-2022 first, then falls back to checking
        for manually placed files in raw_data/.
        """
        paths = []
        for report in CA_DPR_REPORTS:
            # Check primary filename and alternative extensions.
            found_path = self._find_cached(report)
            if found_path:
                paths.append(found_path)
                continue

            # Try auto-download from report page.
            if report.get("report_page_url"):
                dl_path = self._auto_download(report)
                if dl_path:
                    paths.append(dl_path)
                    continue

            logger.warning(
                "CA DPR: no data file for %d — "
                "manually place '%s' in %s. "
                "Source: %s — filter: Residue, or request via %s",
                report["year"],
                report["filename"],
                RAW_DATA_DIR,
                CA_DPR_URL_PATTERNS["reports_directory"],
                CA_DPR_URL_PATTERNS["public_records_portal"],
            )

        if not paths:
            logger.warning(
                "CA DPR: no residue data files found in %s. "
                "This source requires manual data file placement. "
                "See fetcher documentation for instructions.",
                RAW_DATA_DIR,
            )

        return paths

    def _find_cached(self, report: dict) -> Path | None:
        """Check for cached data file (any supported extension)."""
        cache_path = RAW_DATA_DIR / report["filename"]
        if cache_path.exists():
            logger.info("Cache hit: %s", report["filename"])
            return cache_path

        base = report["filename"].rsplit(".", 1)[0]
        for ext in _DPR_FILE_EXTENSIONS:
            alt_path = RAW_DATA_DIR / f"{base}{ext}"
            if alt_path.exists():
                logger.info("Cache hit: %s", alt_path.name)
                return alt_path
        return None

    def _auto_download(self, report: dict) -> Path | None:
        """Try to auto-download XLSX from DPR report page."""
        from bs4 import BeautifulSoup

        try:
            html = fetch_page(report["report_page_url"])
        except Exception as e:
            logger.debug("CA DPR: report page fetch failed for %d: %s", report["year"], e)
            return None

        try:
            soup = BeautifulSoup(html, "html.parser")
            xlsx_links = [
                a["href"] for a in soup.find_all("a", href=True)
                if a["href"].lower().endswith(".xlsx")
            ]
            if not xlsx_links:
                logger.debug("CA DPR: no XLSX links on report page for %d", report["year"])
                return None

            url = xlsx_links[0]
            if not url.startswith("http"):
                url = f"https://www.cdpr.ca.gov{url}"

            # Download to the expected filename
            return download_file(url, report["filename"])
        except Exception as e:
            logger.debug("CA DPR: auto-download failed for %d: %s", report["year"], e)
            return None

    def parse(self, files: list[Path]) -> list[dict]:
        """
        Parse downloaded CA DPR data files into Tier 2 aggregate rows.
        Handles CSV, XLSX, and XLS formats.
        Filters for glyphosate, aggregates by commodity category.
        """
        all_rows = []
        if not files:
            logger.info(
                "CA DPR: no data files to parse — skipping. "
                "Place residue data files in %s to enable this source.",
                RAW_DATA_DIR,
            )
            return all_rows

        # Build a map from filename to report metadata.
        # Support both .csv and .xlsx/.xls variants.
        file_map = {}
        for f in files:
            file_map[f.name] = f

        for report in CA_DPR_REPORTS:
            path = file_map.get(report["filename"])
            if path is None:
                # Check for .xlsx/.xls variants.
                for ext in _DPR_FILE_EXTENSIONS:
                    if ext == ".csv":
                        continue
                    alt_name = report["filename"].replace(".csv", ext)
                    alt_path = file_map.get(alt_name)
                    if alt_path is not None:
                        path = alt_path
                        break

            if path is None:
                logger.debug("CA DPR: no file for %s — skipping", report["label"])
                continue

            if path.suffix in (".xlsx", ".xls"):
                rows = self._parse_excel_file(path, report)
            elif path.suffix == ".csv":
                rows = self._parse_csv_file(path, report)
            else:
                logger.warning(
                    "CA DPR: unrecognized file format %s — skipping", path.suffix
                )
                continue

            all_rows.extend(rows)

        return all_rows

    def _parse_csv_file(self, csv_path: Path, report: dict) -> list[dict]:
        """Parse a CSV data file from CA DPR."""
        try:
            df = pd.read_csv(csv_path, low_memory=False)
        except UnicodeDecodeError:
            df = pd.read_csv(csv_path, low_memory=False, encoding="latin-1")
        return self._parse_dataframe(df, csv_path, report)

    def _parse_excel_file(self, xlsx_path: Path, report: dict) -> list[dict]:
        """Parse an Excel data file from CA DPR."""
        df = pd.read_excel(xlsx_path, sheet_name=0)
        return self._parse_dataframe(df, xlsx_path, report)

    def _parse_dataframe(
        self, df: pd.DataFrame, file_path: Path, report: dict
    ) -> list[dict]:
        """
        Core parser: identify columns dynamically, process ALL pesticides,
        aggregate by (commodity, pesticide) into canonical food categories.
        """
        # Normalize column names.
        df.columns = [
            c.lower().strip().replace(" ", "_").replace("(", "").replace(")", "")
            for c in df.columns
        ]
        logger.info("CA DPR %s columns: %s", report["year"], list(df.columns))

        # Dynamically find key columns.
        pest_col = self._find_col(df, _PESTICIDE_COL_PATTERNS)
        comm_col = self._find_col(df, _COMMODITY_COL_PATTERNS)
        result_col = self._find_col(df, _RESULT_COL_PATTERNS)
        unit_col = self._find_col(df, _UNIT_COL_PATTERNS)

        if pest_col is None:
            logger.warning("CA DPR: no pesticide column found in %s — skipping", file_path.name)
            return []
        if comm_col is None:
            logger.warning("CA DPR: no commodity column found in %s — skipping", file_path.name)
            return []
        if result_col is None:
            logger.warning("CA DPR: no result column found in %s — skipping", file_path.name)
            return []

        # Clean pesticide names
        df[pest_col] = df[pest_col].astype(str).str.strip()
        df = df[df[pest_col].str.lower() != 'nan']
        df = df[df[pest_col].str.len() > 0]

        logger.info("CA DPR %d: %d total sample rows", report["year"], len(df))

        # Determine unit conversion from unit column or default to ppm -> ppb.
        conversion = 1000.0
        original_unit = "ppm"
        if unit_col and len(df) > 0:
            unit_val = str(df[unit_col].iloc[0]).lower().strip()
            if "ppb" in unit_val or "µg/kg" in unit_val or "ug/kg" in unit_val:
                conversion = 1.0
                original_unit = unit_val
            elif "ppm" in unit_val or "mg/kg" in unit_val:
                conversion = 1000.0
                original_unit = unit_val

        # Aggregate by (commodity, pesticide) → canonical food category.
        by_cat_pest = defaultdict(
            lambda: {"total": 0, "detected": [], "raw_cats": []}
        )

        for (commodity, pesticide), group in df.groupby([comm_col, pest_col]):
            raw_cat = self._map_commodity(str(commodity).strip())
            if not raw_cat:
                continue

            food_category = normalize_category(raw_cat)
            if not food_category:
                continue

            pest_name = str(pesticide).strip().lower()
            if not pest_name or pest_name == 'nan':
                continue

            key = (food_category, pest_name)
            total = len(group)
            values = pd.to_numeric(group[result_col], errors="coerce")
            detected = values[values > 0].tolist()

            by_cat_pest[key]["total"] += total
            by_cat_pest[key]["detected"].extend(detected)
            by_cat_pest[key]["raw_cats"].append(str(commodity).strip())

        rows = []
        for (food_category, pest_name), stats in by_cat_pest.items():
            total = stats["total"]
            n_detected = len(stats["detected"])
            detection_rate = round(n_detected / total, 4) if total > 0 else None
            avg_ppb = (
                round(sum(stats["detected"]) / n_detected * conversion, 2)
                if n_detected > 0
                else None
            )
            max_ppb = (
                round(max(stats["detected"]) * conversion, 2)
                if stats["detected"]
                else None
            )
            raw_cat = ", ".join(sorted(set(stats["raw_cats"])))

            rows.append({
                "tier": 2,
                "source_name": "CA_DPR",
                "source_url": report["source_url"],
                "report_label": report["label"],
                "published_date": report["published_date"],
                "data_year": report["data_year"],
                "food_category": food_category,
                "raw_category": raw_cat,
                "contaminant": pest_name,
                "samples_total": total,
                "samples_detected": n_detected,
                "detection_rate": detection_rate,
                "avg_ppb": avg_ppb,
                "max_ppb": max_ppb,
                "original_unit": original_unit,
                "unit_conversion": conversion,
                "methodology_note": (
                    f"{report['label']}. CA DPR Marketplace Surveillance Program. "
                    f"Individual sample results for {pest_name}, "
                    "aggregated by canonical food category."
                ),
                "confidence": "high",
                "raw_file_path": str(file_path),
                "dedup_key": build_dedup_key("CA_DPR", food_category, pest_name, report["data_year"]),
            })

        logger.info(
            "CA DPR %d: parsed %d (category, pesticide) rows from %s",
            report["year"], len(rows), file_path.name,
        )
        return rows

    def _map_commodity(self, commodity_name: str) -> str:
        """
        Map a CA DPR commodity name to a raw category string suitable for
        normalize_category(). Uses exact lookup in CA_DPR_COMMODITY_MAP,
        then falls back to substring matching, then to the original name.
        """
        upper = commodity_name.upper().strip()

        # Exact match in the commodity map.
        if upper in CA_DPR_COMMODITY_MAP:
            return CA_DPR_COMMODITY_MAP[upper]

        # Substring match: check if any map key is contained in the commodity.
        for dpr_name, raw_cat in CA_DPR_COMMODITY_MAP.items():
            if dpr_name in upper or upper in dpr_name:
                return raw_cat

        # Fall back to the original name (normalize_category will try aliases).
        return commodity_name.lower().strip()

    def _find_col(self, df: pd.DataFrame, candidates: list[str]) -> str | None:
        """Find the first column in df that matches any candidate pattern."""
        for candidate in candidates:
            if candidate in df.columns:
                return candidate
        # Try substring match on actual column names.
        for col in df.columns:
            for candidate in candidates:
                if candidate in col:
                    return col
        return None
