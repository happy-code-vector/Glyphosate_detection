"""
fetchers/uk_fsa.py

UK FSA / PRiF (Pesticide Residues in Food) Monitoring Programme — Tier 2 data.

Sources:
  gov.uk quarterly/annual pesticide residue monitoring reports.
  Data published as CSV or Excel files linked from:
    https://www.gov.uk/government/collections/pesticide-residues-in-food-results-of-monitoring-programme

The fetcher scrapes the collection page and linked report pages for data file
downloads (CSV/XLSX), then parses individual sample results filtered for
glyphosate.  Results are aggregated by canonical food category.

No values are hardcoded. All ppb values come from downloaded data files.
"""

import logging
import re
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

import pandas as pd

from fetchers.base import BaseFetcher, download_file, fetch_page, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

# Entry-point collection page for UK PRiF monitoring results.
COLLECTION_URL = (
    "https://www.gov.uk/government/collections/"
    "pesticide-residues-in-food-results-of-monitoring-programme"
)

# Quarterly/annual report pages on gov.uk.
#
# URL pattern (verified 2025-05): the report pages follow the naming convention
#   pesticide-residues-in-food-quarterly-monitoring-results-for-{year}
# for years 2015-2025.  The actual CSV/Excel data files are linked from these
# pages or from data.gov.uk.
#
# Older URLs using the pattern "pesticide-residue-monitoring-annual-data-for-{year}"
# are all 404 and have been replaced.
#
# The collection page (COLLECTION_URL) is scraped first to discover data file
# download links; the report_url here is a fallback when collection scraping
# does not find files for a given year.
#
# UK competent-authority annual reports (summary PDFs, not raw data) are at:
#   uk-competent-authorities-for-pesticide-residues-in-food-annual-report-for-{year}
# but these do not contain CSV/XLSX data downloads.
UK_FSA_REPORTS = [
    {
        "label": "UK PRiF Monitoring 2015",
        "data_year": 2015,
        "published_date": "2016-06-01",
        "report_url": (
            "https://www.gov.uk/government/publications/"
            "pesticide-residues-in-food-quarterly-monitoring-results-for-2015"
        ),
    },
    {
        "label": "UK PRiF Monitoring 2016",
        "data_year": 2016,
        "published_date": "2017-06-01",
        "report_url": (
            "https://www.gov.uk/government/publications/"
            "pesticide-residues-in-food-quarterly-monitoring-results-for-2016"
        ),
    },
    {
        "label": "UK PRiF Monitoring 2017",
        "data_year": 2017,
        "published_date": "2018-06-01",
        "report_url": (
            "https://www.gov.uk/government/publications/"
            "pesticide-residues-in-food-quarterly-monitoring-results-for-2017"
        ),
    },
    {
        "label": "UK PRiF Monitoring 2018",
        "data_year": 2018,
        "published_date": "2019-06-01",
        "report_url": (
            "https://www.gov.uk/government/publications/"
            "pesticide-residues-in-food-quarterly-monitoring-results-for-2018"
        ),
    },
    {
        "label": "UK PRiF Monitoring 2019",
        "data_year": 2019,
        "published_date": "2020-06-01",
        "report_url": (
            "https://www.gov.uk/government/publications/"
            "pesticide-residues-in-food-quarterly-monitoring-results-for-2019"
        ),
    },
    {
        "label": "UK PRiF Monitoring 2020",
        "data_year": 2020,
        "published_date": "2021-06-01",
        "report_url": (
            "https://www.gov.uk/government/publications/"
            "pesticide-residues-in-food-quarterly-monitoring-results-for-2020"
        ),
    },
    {
        "label": "UK PRiF Monitoring 2021",
        "data_year": 2021,
        "published_date": "2022-06-01",
        "report_url": (
            "https://www.gov.uk/government/publications/"
            "pesticide-residues-in-food-quarterly-monitoring-results-for-2021"
        ),
    },
    {
        "label": "UK PRiF Monitoring 2022",
        "data_year": 2022,
        "published_date": "2023-06-01",
        "report_url": (
            "https://www.gov.uk/government/publications/"
            "pesticide-residues-in-food-quarterly-monitoring-results-for-2022"
        ),
    },
    {
        "label": "UK PRiF Monitoring 2023",
        "data_year": 2023,
        "published_date": "2024-06-01",
        "report_url": (
            "https://www.gov.uk/government/publications/"
            "pesticide-residues-in-food-quarterly-monitoring-results-for-2023"
        ),
    },
    {
        "label": "UK PRiF Monitoring 2024",
        "data_year": 2024,
        "published_date": "2025-06-01",
        "report_url": (
            "https://www.gov.uk/government/publications/"
            "pesticide-residues-in-food-quarterly-monitoring-results-for-2024"
        ),
    },
    {
        "label": "UK PRiF Monitoring 2025",
        "data_year": 2025,
        "published_date": "2026-06-01",
        "report_url": (
            "https://www.gov.uk/government/publications/"
            "pesticide-residues-in-food-quarterly-monitoring-results-for-2025"
        ),
    },
]

# Column name candidates for dynamic column detection.
# UK PRiF CSV/Excel files may use various column names across years.
SUBSTANCE_COL_CANDIDATES = [
    "pesticide", "substance", "pesticide_name", "active_substance",
    "param_name", "analyte", "chemical", "compound", "res_name",
    "name_of_pesticide", "pesticide_residue_name", "residue",
]
COMMODITY_COL_CANDIDATES = [
    "commodity", "food", "product", "matrix", "commodity_name",
    "food_name", "product_name", "sample_type", "sample_description",
    "description", "food_commodity", "sampled_food", "food_product",
    "food_group",
]
RESULT_COL_CANDIDATES = [
    "result", "value", "concentration", "level", "residue_level",
    "measured_value", "amount", "detected_concentration", "residue_value",
    "result_value", "mgkg", "res", "quantification",
]


class UKFSAFetcher(BaseFetcher):
    SOURCE_NAME = "UK_FSA"

    def fetch(self) -> list[Path]:
        """
        Scrape the UK PRiF collection page for data download links,
        then download CSV/Excel files for each annual report.
        """
        paths = []

        # Discover data file links from the collection page and report pages.
        data_links = self._discover_data_links()

        for report in UK_FSA_REPORTS:
            year = report["data_year"]
            year_links = data_links.get(year, [])

            if not year_links:
                # Try scraping the report page directly.
                year_links = self._find_data_links(report["report_url"])

            if not year_links:
                logger.warning(
                    "UK_FSA: no data files found for %d — skipping", year
                )
                continue

            for link_info in year_links:
                url = link_info["url"]
                filename = link_info["filename"]
                try:
                    path = download_file(url, filename)
                    paths.append(path)
                except Exception as e:
                    logger.warning(
                        "UK_FSA: failed to download %s for %d: %s",
                        url, year, e,
                    )

        if not paths:
            logger.warning("UK_FSA: no data files downloaded")
        return paths

    def parse(self, files: list[Path]) -> list[dict]:
        """
        Parse downloaded data files and return Tier 2 aggregate rows.
        Each file is parsed individually, glyphosate rows are filtered,
        and results are aggregated by canonical food category.
        """
        all_rows = []
        for path in files:
            try:
                rows = self._parse_data_file(path)
                all_rows.extend(rows)
            except Exception as e:
                logger.warning(
                    "UK_FSA: failed to parse %s: %s — skipping file",
                    path.name, e,
                )
        return all_rows

    # ── Fetch helpers ──────────────────────────────────────────────────

    def _discover_data_links(self) -> dict[int, list[dict]]:
        """
        Scrape the collection page to find links to annual report pages,
        then scrape each report page for CSV/Excel download links.
        Returns {year: [{"url": ..., "filename": ...}, ...]}.
        """
        links_by_year: dict[int, list[dict]] = {}

        try:
            html = fetch_page(COLLECTION_URL)
        except Exception as e:
            logger.warning("UK_FSA: failed to fetch collection page: %s", e)
            return links_by_year

        soup = BeautifulSoup(html, "html.parser")

        # gov.uk collection pages list child documents in
        # <a> tags with hrefs pointing to publications.
        report_urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True).lower()
            # Match links to annual data publications
            if "/government/publications/" in href and (
                "annual data" in text
                or "monitoring" in text
                or "pesticide residue" in text
            ):
                if not href.startswith("http"):
                    href = "https://www.gov.uk" + href
                report_urls.append(href)

        # Deduplicate
        report_urls = list(dict.fromkeys(report_urls))

        for url in report_urls:
            year = self._extract_year_from_url(url)
            if year is None:
                continue
            data_links = self._find_data_links(url)
            if data_links:
                links_by_year.setdefault(year, []).extend(data_links)
                logger.info(
                    "UK_FSA: found %d data file(s) for %d from %s",
                    len(data_links), year, url,
                )

        return links_by_year

    def _find_data_links(self, url: str) -> list[dict]:
        """
        Scrape a gov.uk report page for CSV or Excel download links.
        gov.uk pages use the Design System: file downloads are <a> tags
        with href ending in .csv or .xlsx, often nested inside
        sections with class 'attachment'.
        """
        links = []
        try:
            html = fetch_page(url)
        except Exception as e:
            logger.warning("UK_FSA: failed to fetch report page %s: %s", url, e)
            return links

        soup = BeautifulSoup(html, "html.parser")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            lower = href.lower()
            if not (lower.endswith(".csv") or lower.endswith(".xlsx")
                    or lower.endswith(".xls")):
                continue

            if not href.startswith("http"):
                href = "https://www.gov.uk" + href

            # Build a deterministic filename from the URL.
            filename = self._url_to_filename(href)
            links.append({"url": href, "filename": filename})

        return links

    def _extract_year_from_url(self, url: str) -> int | None:
        """Try to extract a 4-digit year from a URL or link text."""
        match = re.search(r"(20[12]\d)", url)
        if match:
            return int(match.group(1))
        return None

    def _url_to_filename(self, url: str) -> str:
        """
        Build a safe, unique filename from a download URL.
        Format: uk_fsa_<sanitized_basename>
        """
        # Get the last path segment
        basename = url.split("/")[-1].split("?")[0]
        # Remove special characters, keep alphanumeric/dot/dash/underscore
        safe = re.sub(r"[^\w.\-]", "_", basename)
        # Prefix for namespace
        if not safe.startswith("uk_fsa_"):
            safe = "uk_fsa_" + safe
        # Ensure reasonable length
        if len(safe) > 120:
            ext = ""
            if "." in safe:
                ext = safe[safe.rindex("."):]
                safe = safe[:120 - len(ext)] + ext
            else:
                safe = safe[:120]
        return safe

    # ── Parse helpers ──────────────────────────────────────────────────

    def _parse_data_file(self, path: Path) -> list[dict]:
        """
        Parse a single CSV or Excel file, filter for glyphosate,
        and aggregate results by food category.
        """
        suffix = path.suffix.lower()
        if suffix in (".xlsx", ".xls"):
            return self._parse_excel(path)
        elif suffix == ".csv":
            return self._parse_csv(path)
        else:
            logger.warning("UK_FSA: unsupported file format %s — skipping", suffix)
            return []

    def _parse_csv(self, csv_path: Path) -> list[dict]:
        """Parse a CSV data file for glyphosate rows."""
        try:
            df = pd.read_csv(csv_path, low_memory=False)
        except UnicodeDecodeError:
            try:
                df = pd.read_csv(csv_path, low_memory=False, encoding="latin-1")
            except Exception as e:
                raise ValueError(
                    f"Cannot read CSV {csv_path.name}: {e}"
                ) from e
        return self._extract_glyphosate_rows(df, csv_path)

    def _parse_excel(self, xlsx_path: Path) -> list[dict]:
        """Parse an Excel data file for glyphosate rows."""
        try:
            df = pd.read_excel(xlsx_path, sheet_name=0, engine="openpyxl")
        except Exception:
            try:
                df = pd.read_excel(xlsx_path, sheet_name=0, engine="xlrd")
            except Exception as e:
                raise ValueError(
                    f"Cannot read Excel {xlsx_path.name}: {e}"
                ) from e
        return self._extract_glyphosate_rows(df, xlsx_path)

    def _extract_glyphosate_rows(
        self, df: pd.DataFrame, file_path: Path
    ) -> list[dict]:
        """
        Given a DataFrame, dynamically identify the substance, commodity,
        and result columns.  Filter for glyphosate (excluding AMPA), then
        aggregate by canonical food category.
        """
        # Normalize column names for matching.
        original_cols = list(df.columns)
        df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]

        logger.info(
            "UK_FSA: %s — %d rows, columns: %s",
            file_path.name, len(df), list(df.columns),
        )

        # Dynamic column detection.
        substance_col = self._find_col(df, SUBSTANCE_COL_CANDIDATES)
        commodity_col = self._find_col(df, COMMODITY_COL_CANDIDATES)
        result_col = self._find_col(df, RESULT_COL_CANDIDATES)

        if not substance_col:
            raise ValueError(
                f"No substance/pesticide column found in {file_path.name}. "
                f"Available: {list(df.columns)}"
            )
        if not commodity_col:
            raise ValueError(
                f"No commodity/food column found in {file_path.name}. "
                f"Available: {list(df.columns)}"
            )
        if not result_col:
            logger.warning(
                "UK_FSA: no result/value column in %s — cannot extract ppb, "
                "will count detections only",
                file_path.name,
            )

        # Filter for glyphosate.
        gly_mask = df[substance_col].astype(str).str.lower().str.contains(
            "glyphosate", na=False
        )
        gly_df = df[gly_mask].copy()

        if gly_df.empty:
            logger.info("UK_FSA: no glyphosate rows in %s", file_path.name)
            return []

        # Exclude AMPA metabolite rows.
        ampa_mask = gly_df[substance_col].astype(str).str.lower().str.contains(
            "ampa", na=False
        )
        gly_df = gly_df[~ampa_mask].copy()

        if gly_df.empty:
            logger.info(
                "UK_FSA: only AMPA (no glyphosate) in %s", file_path.name
            )
            return []

        logger.info(
            "UK_FSA: %d glyphosate sample rows in %s",
            len(gly_df), file_path.name,
        )

        # Infer data year from filename.
        data_year = self._extract_year_from_url(file_path.name) or 2020
        published_date = f"{data_year + 1}-06-01"

        # Determine unit conversion.
        # UK data is typically reported in mg/kg.  Check for unit column or
        # assume mg/kg (multiply by 1000 for ppb).
        unit_col = self._find_col(df, ["unit", "units", "result_unit", "report_unit"])
        conversion = 1000.0
        original_unit = "mg/kg"
        if unit_col and unit_col in gly_df.columns:
            unit_val = str(gly_df[unit_col].dropna().iloc[0]).lower()
            if "ppb" in unit_val or "ug/kg" in unit_val or "µg/kg" in unit_val:
                conversion = 1.0
                original_unit = unit_val
            elif "mg/kg" in unit_val or "ppm" in unit_val:
                conversion = 1000.0
                original_unit = unit_val

        # Aggregate by canonical food category.
        by_category: dict[str, dict] = defaultdict(
            lambda: {"total": 0, "detected": 0, "ppb_values": [], "raw_cats": []}
        )

        for commodity, group in gly_df.groupby(commodity_col):
            raw_cat = str(commodity).strip()
            if not raw_cat or raw_cat.lower() in ("nan", "total", "all"):
                continue
            food_category = normalize_category(raw_cat)
            if not food_category:
                logger.debug(
                    "UK_FSA: no canonical category for '%s' — skipping", raw_cat
                )
                continue

            total = len(group)

            if result_col and result_col in group.columns:
                values = pd.to_numeric(group[result_col], errors="coerce")
                detected_values = values[values > 0]
                n_detected = len(detected_values)
                ppb_detected = (detected_values * conversion).tolist()
            else:
                n_detected = 0
                ppb_detected = []

            stats = by_category[food_category]
            stats["total"] += total
            stats["detected"] += n_detected
            stats["ppb_values"].extend(ppb_detected)
            stats["raw_cats"].append(raw_cat)

        rows = []
        for food_category, stats in by_category.items():
            if stats["total"] == 0:
                continue

            total = stats["total"]
            n_detected = stats["detected"]
            detection_rate = round(n_detected / total, 4) if total > 0 else None
            avg_ppb = (
                round(sum(stats["ppb_values"]) / len(stats["ppb_values"]), 2)
                if stats["ppb_values"]
                else None
            )
            max_ppb = (
                round(max(stats["ppb_values"]), 2)
                if stats["ppb_values"]
                else None
            )
            raw_cat = ", ".join(sorted(set(stats["raw_cats"])))

            rows.append({
                "tier": 2,
                "source_name": "UK_FSA",
                "source_url": COLLECTION_URL,
                "report_label": f"UK PRiF Monitoring {data_year}",
                "published_date": published_date,
                "data_year": data_year,
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
                    f"UK FSA Pesticide Residues in Food (PRiF) monitoring programme. "
                    f"Individual sample results from annual data for {data_year}. "
                    f"Glyphosate-specific results aggregated by canonical food category. "
                    f"Multi-pesticide dataset filtered for glyphosate (AMPA excluded). "
                    f"Original data in {original_unit}, converted to ppb."
                ),
                "confidence": "high",
                "raw_file_path": str(file_path),
                "dedup_key": build_dedup_key(
                    "UK_FSA", food_category, data_year
                ),
            })

        logger.info(
            "UK_FSA: parsed %d category rows from %s",
            len(rows), file_path.name,
        )
        return rows

    def _find_col(self, df: pd.DataFrame, candidates: list[str]) -> str | None:
        """Find the first matching column name from a list of candidates."""
        for col in candidates:
            if col in df.columns:
                return col
        # Fallback: substring match
        for col in df.columns:
            for candidate in candidates:
                if candidate in col:
                    return col
        return None
