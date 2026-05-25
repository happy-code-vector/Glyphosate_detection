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

NOTE: The old /docs/pml/ URLs were retired when DPR restructured its site
(c. 2024).  Data files are now accessed through the reports directory or
by scraping the residue monitoring landing page.

No values are hardcoded. All residue levels come from downloaded data files.
"""

import logging
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

from fetchers.base import BaseFetcher, download_file, fetch_page, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# CA DPR reports registry — one entry per monitoring year.
# Add new entries as DPR publishes new annual data.
#
# NOTE (2025-05): The old /docs/pml/ URLs are all 404.  DPR restructured
# its website around 2024.  The current entry points are:
#   - Landing page:  https://www.cdpr.ca.gov/data-and-reports/residue-monitoring/
#   - Reports dir:   https://www.cdpr.ca.gov/reports-directory/  (filter: Residue)
#
# Annual residue data entries found in the reports directory include:
#   "Annual Residue Data 2020" (Jan 2020), "Annual Residue Data 2021" (Jan 2025),
#   "Annual Residue Data 2022" (Jan 2022), plus annual program reports.
# Direct CSV download URLs have not been confirmed; the fetcher relies on
# scraping the reports directory or landing page for download links.
# ─────────────────────────────────────────────────────────────────────
CA_DPR_REPORTS = [
    {
        "label": "CA DPR Pesticide Residue Monitoring 2020",
        "year": 2020,
        "filename": "ca_dpr_2020_residue.csv",
        "source_url": "https://www.cdpr.ca.gov/data-and-reports/residue-monitoring/",
        "published_date": "2021-06-01",
        "data_year": 2020,
    },
    {
        "label": "CA DPR Pesticide Residue Monitoring 2021",
        "year": 2021,
        "filename": "ca_dpr_2021_residue.csv",
        "source_url": "https://www.cdpr.ca.gov/data-and-reports/residue-monitoring/",
        "published_date": "2022-06-01",
        "data_year": 2021,
    },
    {
        "label": "CA DPR Pesticide Residue Monitoring 2022",
        "year": 2022,
        "filename": "ca_dpr_2022_residue.csv",
        "source_url": "https://www.cdpr.ca.gov/data-and-reports/residue-monitoring/",
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

# Known URL patterns for CA DPR residue data files.
# The old /docs/pml/ paths are all 404 after DPR's site restructuring.
# Current patterns point to the new site structure.
CA_DPR_URL_PATTERNS = {
    "residue_landing": "https://www.cdpr.ca.gov/data-and-reports/residue-monitoring/",
    "reports_directory": "https://www.cdpr.ca.gov/reports-directory/",
    # Legacy patterns (all 404, kept for reference only):
    # "residue_dir": "https://www.cdpr.ca.gov/docs/pml/residue/{year}/",
    # "pmrc_html": "https://www.cdpr.ca.gov/docs/pml/pmrchtm/{year}pmrc.htm",
    # "reports_page": "https://www.cdpr.ca.gov/docs/pml/reports.htm",
}

# Common file name patterns DPR uses for downloadable data.
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
    "TOMATOES": "tomatoes",
    "TOMATO": "tomatoes",
    "PEPPERS, BELL": "peppers",
    "PEPPERS": "peppers",
    "CUCUMBERS": "cucumbers",
    "BROCCOLI": "broccoli",
    "CARROTS": "carrots",
    "POTATOES": "potatoes",
    "ONIONS": "onions",
    "CABBAGE": "cabbage",
    "MUSHROOMS": "mushrooms",
    "STRAWBERRIES": "strawberries",
    "GRAPES, TABLE": "grapes",
    "GRAPES": "grapes",
    "ORANGES": "oranges",
    "APPLES": "apples",
    "PEACHES": "peaches",
    "PEARS": "pears",
    "BANANAS": "bananas",
    "OATS": "oats",
    "OAT FLOUR": "oats",
    "WHEAT FLOUR": "wheat flour",
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
    "CANTALOUPE": "fresh_fruit",
    "WATERMELON": "fresh_fruit",
    "MELONS": "fresh_fruit",
    "KALE": "fresh_vegetables",
    "CHARD": "fresh_vegetables",
    "ARUGULA": "fresh_vegetables",
    "CILANTRO": "fresh_vegetables",
    "BASIL": "fresh_vegetables",
    "PARSLEY": "fresh_vegetables",
    "MINT": "fresh_vegetables",
    "HERBS": "fresh_vegetables",
    "MANGOES": "fresh_fruit",
    "PINEAPPLE": "fresh_fruit",
    "AVOCADOS": "fresh_fruit",
    "LIMES": "fresh_fruit",
    "LEMONS": "fresh_fruit",
    "GRAPEFRUIT": "fresh_fruit",
    "TANGERINES": "fresh_fruit",
    "PLUMS": "fresh_fruit",
    "NECTARINES": "fresh_fruit",
    "APRICOTS": "fresh_fruit",
    "FIGS": "fresh_fruit",
    "KIWI": "fresh_fruit",
    "PAPAYA": "fresh_fruit",
    "ASPARAGUS": "fresh_vegetables",
    "ARTICHOKES": "fresh_vegetables",
    "BEETS": "fresh_vegetables",
    "CAULIFLOWER": "fresh_vegetables",
    "EGGPLANT": "fresh_vegetables",
    "GREEN BEANS": "beans",
    "SNAP PEAS": "peas",
    "SQUASH": "fresh_vegetables",
    "ZUCCHINI": "fresh_vegetables",
    "TURNIPS": "fresh_vegetables",
    "RADISHES": "fresh_vegetables",
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
    """California DPR Marketplace Surveillance residue monitoring fetcher."""

    SOURCE_NAME = "CA_DPR"

    def fetch(self) -> list[Path]:
        """
        Download CA DPR residue data files for each registered year.
        Tries known URL patterns; falls back to scraping the reports page.
        Returns list of local file paths (may be fewer than registered years
        if some years have no downloadable data).
        """
        paths = []
        for report in CA_DPR_REPORTS:
            cache_path = RAW_DATA_DIR / report["filename"]
            if cache_path.exists():
                logger.info("Cache hit: %s", report["filename"])
                paths.append(cache_path)
                continue

            path = self._try_fetch_year(report)
            if path is not None:
                paths.append(path)
            else:
                logger.warning(
                    "CA DPR: could not download data for %d — skipping year",
                    report["year"],
                )
        return paths

    def _try_fetch_year(self, report: dict) -> Path | None:
        """
        Attempt multiple strategies to download data for a given year.
        Strategy 1: Scrape the reports directory for year-specific data links.
        Strategy 2: Scrape the residue monitoring landing page for data links.
        Returns the local file path or None.
        """
        year = report["year"]

        # Strategy 1: Scrape the reports directory for download links.
        path = self._scrape_reports_directory(report)
        if path is not None:
            return path

        # Strategy 2: Scrape the residue monitoring landing page for links.
        path = self._scrape_landing_page(report)
        return path

    def _scrape_reports_directory(self, report: dict) -> Path | None:
        """Scrape the DPR reports directory for download links matching this year."""
        try:
            from bs4 import BeautifulSoup

            html = fetch_page(CA_DPR_URL_PATTERNS["reports_directory"])
            soup = BeautifulSoup(html, "html.parser")
            year_str = str(report["year"])

            # Look for links that reference this year's data.
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True).lower()
                if year_str not in href and year_str not in text:
                    continue
                # Match data file links (CSV, XLSX, XLS).
                if not any(href.lower().endswith(ext) for ext in _DPR_FILE_EXTENSIONS):
                    continue
                if not href.startswith("http"):
                    href = f"https://www.cdpr.ca.gov{href}"
                try:
                    path = download_file(href, report["filename"])
                    logger.info(
                        "CA DPR %d: found data link on reports directory: %s",
                        report["year"], href,
                    )
                    return path
                except Exception as e:
                    logger.debug("CA DPR: download failed for %s: %s", href, e)
                    continue

            logger.info("CA DPR: no data link found on reports directory for %d", report["year"])
            return None
        except Exception as e:
            logger.warning("CA DPR: failed to scrape reports directory: %s", e)
            return None

    def _scrape_landing_page(self, report: dict) -> Path | None:
        """Scrape the DPR residue monitoring landing page for linked data files."""
        try:
            from bs4 import BeautifulSoup

            url = CA_DPR_URL_PATTERNS["residue_landing"]
            html = fetch_page(url)
            soup = BeautifulSoup(html, "html.parser")
            year_str = str(report["year"])

            # Look for links referencing this year's residue data.
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True).lower()
                if year_str not in href and year_str not in text:
                    continue
                if not any(href.lower().endswith(ext) for ext in _DPR_FILE_EXTENSIONS):
                    continue
                if not href.startswith("http"):
                    href = f"https://www.cdpr.ca.gov{href}"
                try:
                    path = download_file(href, report["filename"])
                    logger.info(
                        "CA DPR %d: found data link on landing page: %s",
                        report["year"], href,
                    )
                    return path
                except Exception as e:
                    logger.debug("CA DPR: download failed for %s: %s", href, e)
                    continue

            # Save the HTML itself as a fallback for inline tables.
            cache_path = RAW_DATA_DIR / report["filename"].replace(".csv", ".html")
            cache_path.write_text(html, encoding="utf-8")
            logger.info(
                "CA DPR %d: saved landing page HTML (%d bytes) for inline parsing",
                report["year"], len(html),
            )
            return cache_path
        except Exception as e:
            logger.warning("CA DPR: failed to fetch landing page for %d: %s", report["year"], e)
            return None

    def parse(self, files: list[Path]) -> list[dict]:
        """
        Parse downloaded CA DPR data files into Tier 2 aggregate rows.
        Handles CSV, XLSX, XLS, and HTML formats.
        Filters for glyphosate, aggregates by commodity category.
        """
        all_rows = []
        # Build a map from filename to report metadata.
        # Also try HTML fallback names (year.csv -> year.html).
        file_map = {}
        for f in files:
            file_map[f.name] = f
            # Register HTML fallback name if it was saved.
            if f.suffix == ".html":
                csv_name = f.name.replace(".html", ".csv")
                file_map[csv_name] = f

        for report in CA_DPR_REPORTS:
            path = file_map.get(report["filename"])
            if path is None:
                logger.warning("CA DPR: no file for %s — skipping", report["label"])
                continue

            if path.suffix == ".html":
                rows = self._parse_html_file(path, report)
            elif path.suffix in (".xlsx", ".xls"):
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

    def _parse_html_file(self, html_path: Path, report: dict) -> list[dict]:
        """
        Parse HTML data — either inline tables from the PMRC page or
        tables from the saved reports page.
        """
        try:
            tables = pd.read_html(html_path, flavor="html5lib")
        except ValueError:
            logger.warning("CA DPR: no tables found in %s", html_path.name)
            return []

        all_rows = []
        for table in tables:
            if table.empty:
                continue
            rows = self._parse_dataframe(table, html_path, report)
            if rows:
                all_rows.extend(rows)
                return all_rows  # Use the first table that yields glyphosate data.

        if not all_rows:
            logger.warning(
                "CA DPR: no glyphosate data found in any table in %s",
                html_path.name,
            )
        return all_rows

    def _parse_dataframe(
        self, df: pd.DataFrame, file_path: Path, report: dict
    ) -> list[dict]:
        """
        Core parser: identify columns dynamically, filter for glyphosate,
        aggregate by canonical food category.
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
            logger.warning(
                "CA DPR: no pesticide column found in %s — skipping", file_path.name
            )
            return []
        if comm_col is None:
            logger.warning(
                "CA DPR: no commodity column found in %s — skipping", file_path.name
            )
            return []
        if result_col is None:
            logger.warning(
                "CA DPR: no result column found in %s — skipping", file_path.name
            )
            return []

        # Filter for glyphosate (case-insensitive substring match).
        gly_mask = df[pest_col].astype(str).str.lower().str.contains(
            "glyphosate", na=False
        )
        gly_df = df[gly_mask].copy()

        if gly_df.empty:
            logger.warning(
                "CA DPR: no glyphosate rows found in %s", file_path.name
            )
            return []

        # Exclude AMPA metabolite.
        ampa_mask = gly_df[pest_col].astype(str).str.lower().str.contains(
            "ampa", na=False
        )
        gly_df = gly_df[~ampa_mask]

        if gly_df.empty:
            logger.warning(
                "CA DPR: only AMPA found (no glyphosate) in %s", file_path.name
            )
            return []

        logger.info(
            "CA DPR %d: %d glyphosate sample rows", report["year"], len(gly_df)
        )

        # Determine unit conversion from unit column or default to ppm -> ppb.
        conversion = 1000.0
        original_unit = "ppm"
        if unit_col:
            unit_val = str(gly_df[unit_col].iloc[0]).lower().strip()
            if "ppb" in unit_val or "µg/kg" in unit_val or "ug/kg" in unit_val:
                conversion = 1.0
                original_unit = unit_val
            elif "ppm" in unit_val or "mg/kg" in unit_val:
                conversion = 1000.0
                original_unit = unit_val

        # Aggregate by commodity → canonical food category.
        by_category = defaultdict(
            lambda: {"total": 0, "detected": [], "raw_cats": []}
        )

        for commodity, group in gly_df.groupby(comm_col):
            raw_cat = self._map_commodity(str(commodity).strip())
            if not raw_cat:
                continue

            food_category = normalize_category(raw_cat)
            if not food_category:
                logger.debug(
                    "CA DPR: no canonical category for commodity '%s' (raw: '%s')",
                    commodity, raw_cat,
                )
                continue

            total = len(group)
            values = pd.to_numeric(group[result_col], errors="coerce")
            detected = values[values > 0].tolist()

            by_category[food_category]["total"] += total
            by_category[food_category]["detected"].extend(detected)
            by_category[food_category]["raw_cats"].append(str(commodity).strip())

        rows = []
        for food_category, stats in by_category.items():
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
                "samples_total": total,
                "samples_detected": n_detected,
                "detection_rate": detection_rate,
                "avg_ppb": avg_ppb,
                "max_ppb": max_ppb,
                "original_unit": original_unit,
                "unit_conversion": conversion,
                "methodology_note": (
                    f"{report['label']}. CA DPR Marketplace Surveillance Program. "
                    "Individual sample results aggregated by canonical food category. "
                    "Glyphosate filtered from multi-pesticide residue data."
                ),
                "confidence": "high",
                "raw_file_path": str(file_path),
                "dedup_key": build_dedup_key("CA_DPR", food_category, report["data_year"]),
            })

        logger.info(
            "CA DPR %d: parsed %d category rows from %s",
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
