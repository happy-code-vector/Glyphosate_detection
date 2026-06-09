"""
fetchers/germany_bvl.py

Germany BVL (Bundesamt für Verbraucherschutz und Lebensmittelsicherheit)
National Pesticide Monitoring Programme — Tier 2 (category aggregates).

Source:
  BVL "Nationale Berichterstattung Pflanzenschutzmittelrückstände"
  https://www.bvl.bund.de/DE/Arbeitsbereiche/01_Lebensmittel/01_Aufgaben/
      02_AmtlicheLebensmittelueberwachung/07_PSMRueckstaende/lm_nbpsm_node.html

Years: 2011–2024 (excluding 2012, PDF only). Format: Excel/CSV with German-language column headers.

This is a higher-value EU data source than EFSA enforcement data because BVL
reports ALL detections (not just MRL exceedances), providing both detection
rates and average residue levels.

No values are hardcoded. All data comes from downloaded BVL files.
German commodity names are translated via _map_german_commodity().
"""

import logging
import re
from pathlib import Path

import pandas as pd

from fetchers.base import BaseFetcher, download_file, SESSION, RAW_DATA_DIR, fetch_page
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

BVL_OVERVIEW_URL = (
    "https://www.bvl.bund.de/DE/Arbeitsbereiche/01_Lebensmittel/"
    "01_Aufgaben/02_AmtlicheLebensmittelueberwachung/"
    "07_PSMRueckstaende/lm_nbpsm_node.html"
)

# Registry of BVL national monitoring reports for 2011–2024 (excluding 2012, PDF only).
# Direct download URLs point to the tab-24 / Substanzen surveillance files which
# contain substance-level data (the files we need for pesticide residue lookups).
GERMANY_BVL_REPORTS = [
    {
        "label": "Germany BVL National Monitoring 2011",
        "year": 2011,
        "filename": "bvl_2011_tab24_surveillance.xls",
        "direct_url": (
            "https://www.bvl.bund.de/SharedDocs/Downloads/01_Lebensmittel/"
            "nbpsm/01_nbpsm_2011/psmr-2011-tab-24-surveillance-xls.xls"
            "?__blob=publicationFile&v=2"
        ),
        "published_date": "2013-06-01",
        "data_year": 2011,
    },
    {
        "label": "Germany BVL National Monitoring 2013",
        "year": 2013,
        "filename": "bvl_2013_tab24_surveillance.xls",
        "direct_url": (
            "https://www.bvl.bund.de/SharedDocs/Downloads/01_Lebensmittel/"
            "nbpsm/03_nbpsm_2013/psmr-2013-tab-24-surveillance-xls.xls"
            "?__blob=publicationFile&v=2"
        ),
        "published_date": "2015-06-01",
        "data_year": 2013,
    },
    {
        "label": "Germany BVL National Monitoring 2014",
        "year": 2014,
        "filename": "bvl_2014_tab24_surveillance.xls",
        "direct_url": (
            "https://www.bvl.bund.de/SharedDocs/Downloads/01_Lebensmittel/"
            "nbpsm/03_nbpsm_2014/07_psmr-2014-tab-24-surveillance-xls.xls"
            "?__blob=publicationFile&v=2"
        ),
        "published_date": "2016-06-01",
        "data_year": 2014,
    },
    {
        "label": "Germany BVL National Monitoring 2015",
        "year": 2015,
        "filename": "bvl_2015_tab24_surveillance.xls",
        "direct_url": (
            "https://www.bvl.bund.de/SharedDocs/Downloads/01_Lebensmittel/"
            "nbpsm/05_nbpsm_2015/07_psmr-2015-tab-24-surveillance-xls.xls"
            "?__blob=publicationFile&v=2"
        ),
        "published_date": "2017-06-01",
        "data_year": 2015,
    },
    {
        "label": "Germany BVL National Monitoring 2016",
        "year": 2016,
        "filename": "bvl_2016_tab24_surveillance.xls",
        "direct_url": (
            "https://www.bvl.bund.de/SharedDocs/Downloads/01_Lebensmittel/"
            "nbpsm/06_nbpsm_2016/psmr-2016-tab-24-surveillance_xls.xls"
            "?__blob=publicationFile&v=2"
        ),
        "published_date": "2018-06-01",
        "data_year": 2016,
    },
    {
        "label": "Germany BVL National Monitoring 2017",
        "year": 2017,
        "filename": "bvl_2017_tab24_surveillance.xlsx",
        "direct_url": (
            "https://www.bvl.bund.de/SharedDocs/Downloads/01_Lebensmittel/"
            "nbpsm/07_nbpsm_2017/psmr-2017-tab-24-surveillance_xls.xlsx"
            "?__blob=publicationFile&v=2"
        ),
        "published_date": "2019-06-01",
        "data_year": 2017,
    },
    {
        "label": "Germany BVL National Monitoring 2018",
        "year": 2018,
        "filename": "bvl_2018_tab24_surveillance.xlsx",
        "direct_url": (
            "https://www.bvl.bund.de/SharedDocs/Downloads/01_Lebensmittel/"
            "nbpsm/08_nbpsm_2018/psmr-2018-tab-24-surveillance_xls.xlsx"
            "?__blob=publicationFile&v=2"
        ),
        "published_date": "2020-06-01",
        "data_year": 2018,
    },
    {
        "label": "Germany BVL National Monitoring 2019",
        "year": 2019,
        "filename": "bvl_2019_tab24_surveillance.xlsx",
        "direct_url": (
            "https://www.bvl.bund.de/SharedDocs/Downloads/01_Lebensmittel/"
            "nbpsm/09_nbpsm_2019/psmr-2019-tab-24-surveillance_xlsx.xlsx"
            "?__blob=publicationFile&v=2"
        ),
        "published_date": "2021-06-01",
        "data_year": 2019,
    },
    {
        "label": "Germany BVL National Monitoring 2020",
        "year": 2020,
        "filename": "bvl_2020_tab24_surveillance.xlsx",
        "direct_url": (
            "https://www.bvl.bund.de/SharedDocs/Downloads/01_Lebensmittel/"
            "nbpsm/09_nbpsm_2020/psmr-2020-tab-24-surveillance_xlsx.xlsx"
            "?__blob=publicationFile&v=2"
        ),
        "published_date": "2022-06-01",
        "data_year": 2020,
    },
    {
        "label": "Germany BVL National Monitoring 2021",
        "year": 2021,
        "filename": "bvl_2021_tab24_surveillance.xlsx",
        "direct_url": (
            "https://www.bvl.bund.de/SharedDocs/Downloads/01_Lebensmittel/"
            "nbpsm/09_nbpsm_2021/psmr-2021-tab-24-surveillance_xlsx.xlsx"
            "?__blob=publicationFile&v=2"
        ),
        "published_date": "2023-06-01",
        "data_year": 2021,
    },
    {
        "label": "Germany BVL National Monitoring 2022",
        "year": 2022,
        "filename": "bvl_2022_lebensmittel_substanzen_mitR.xlsx",
        "direct_url": (
            "https://www.bvl.bund.de/SharedDocs/Downloads/01_Lebensmittel/"
            "nbpsm/10_nbpsm_2022/PSMR_Insgesamt_2022_Lebensmittel_Substanzen_mitR.xlsx.xlsx"
            "?__blob=publicationFile&v=2"
        ),
        "published_date": "2024-06-01",
        "data_year": 2022,
    },
    {
        "label": "Germany BVL National Monitoring 2023",
        "year": 2023,
        "filename": "bvl_2023_lebensmittel_substanzen_mitR.xlsx",
        "direct_url": (
            "https://www.bvl.bund.de/SharedDocs/Downloads/01_Lebensmittel/"
            "nbpsm/11_nbpsm_2023/PSMR_Insgesamt_2023_Lebensmittel_Substanzen_mitR.xlsx.xlsx"
            "?__blob=publicationFile&v=2"
        ),
        "published_date": "2025-06-01",
        "data_year": 2023,
    },
    {
        "label": "Germany BVL National Monitoring 2024",
        "year": 2024,
        "filename": "bvl_2024_lebensmittel_substanzen_mitR.xlsx",
        "direct_url": (
            "https://www.bvl.bund.de/SharedDocs/Downloads/01_Lebensmittel/"
            "nbpsm/12_nbpsm_2024/PSMR_Insgesamt_2024_Lebensmittel_Substanzen_mitR.xlsx.xlsx"
            "?__blob=publicationFile&v=2"
        ),
        "published_date": "2026-06-01",
        "data_year": 2024,
    },
]

# German column header patterns for dynamic detection
_SUBSTANCE_COL_PATTERNS = [
    "wirkstoff", "pflanzenschutzmittel", "substance", "pestizid",
    "wirkstoffe", "parameter", "analyt", "substanzen",
]
_COMMODITY_COL_PATTERNS = [
    "lebensmittel", "matrix", " commodity", "produkt", "lebensmittelgruppe",
    "warengruppe", "food", "product",
]
_SAMPLES_COL_PATTERNS = [
    "anzahl prober", "anzahl", "proben", "anzahl_proben", "gesamt",
    "anzahl der prober", "untersuchte prober", "number of samples",
    "gesamtzahl", "anzahl untersuchte",
    "anzahl der untersuchungen", "anzahl der proben",
]
# Exact-match names for total-sample columns (short names that would
# cause false positives with substring matching).
_SAMPLES_EXACT_NAMES = {"n"}
_RESIDUES_COL_PATTERNS = [
    "mit rückständen", "mit ruckstanden",
    "davon mit rückständen", "davon mit rueckstaenden",
    "mit rückstand", "positiv", "fundhäufigkeit", "detektiert",
    "anzahl positiv", "davon positiv",
    "mit r",
]
_LEVEL_COL_PATTERNS = [
    "rückstandshöhe", "mittelwert", "mittlere rückstandshöhe",
    "durchschnitt", "mean", "mittel", "mg/kg", "rückstandsgehalt",
    "durchschnittlicher gehalt", "average",
]


class GermanyBVLFetcher(BaseFetcher):
    SOURCE_NAME = "Germany_BVL"

    def fetch(self) -> list[Path]:
        """
        Download BVL data files. Tries known direct URLs first, then
        falls back to scraping the overview page. Handles failures
        gracefully — BVL site structure changes frequently.
        """
        paths = []
        for report in GERMANY_BVL_REPORTS:
            path = self._fetch_report(report)
            if path is not None:
                paths.append(path)
        if not paths:
            logger.warning(
                "Germany_BVL: no data files could be downloaded. "
                "BVL site may be blocking automated access or has restructured. "
                "Check %s manually.", BVL_OVERVIEW_URL
            )
        return paths

    @staticmethod
    def _is_valid_cache(path: Path) -> bool:
        """Check that a cached file is a real data file, not an HTML error page."""
        try:
            header = path.read_bytes()[:100]
            return not header.strip().startswith(b"<")
        except Exception:
            return False

    def _fetch_report(self, report: dict) -> Path | None:
        """Download a single BVL report, with caching and fallback."""
        cache_path = RAW_DATA_DIR / report["filename"]
        if cache_path.exists():
            # Validate the cache is not an HTML error page
            if self._is_valid_cache(cache_path):
                logger.info("Cache hit: %s", report["filename"])
                return cache_path
            logger.warning(
                "Germany_BVL: cached file %s is corrupted (HTML), re-downloading",
                report["filename"],
            )
            cache_path.unlink()

        # Attempt 1: known direct URL
        if report.get("direct_url"):
            try:
                path = download_file(
                    report["direct_url"], report["filename"]
                )
                return path
            except Exception as e:
                logger.warning(
                    "Germany_BVL: direct URL failed for %s: %s",
                    report["label"], e,
                )

        # Attempt 2: scrape overview page for download links
        try:
            path = self._scrape_overview_page(report)
            if path:
                return path
        except Exception as e:
            logger.error(
                "Germany_BVL: scraping overview page failed for %s: %s",
                report["label"], e,
            )

        logger.warning(
            "Germany_BVL: could not download %s — skipping",
            report["label"],
        )
        return None

    def _scrape_overview_page(self, report: dict) -> Path | None:
        """
        Scrape the BVL overview page for links to data files matching
        the report year. Looks for Excel/CSV links containing the year.
        """
        from bs4 import BeautifulSoup

        try:
            html = fetch_page(BVL_OVERVIEW_URL)
        except Exception as e:
            logger.warning("Germany_BVL: could not fetch overview page: %s", e)
            return None

        soup = BeautifulSoup(html, "html.parser")
        year_str = str(report["year"])

        # Look for links that reference data files with the year
        candidates = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True).lower()
            href_lower = href.lower()
            # Match links that look like data files for this year
            if year_str in href or year_str in text:
                if any(ext in href_lower for ext in [".xlsx", ".xls", ".csv", ".download"]):
                    full_url = href if href.startswith("http") else (
                        "https://www.bvl.bund.de" + href
                    )
                    candidates.append(full_url)

        if not candidates:
            logger.warning(
                "Germany_BVL: no data link found for %s on overview page",
                report["label"],
            )
            return None

        # Try each candidate
        for url in candidates:
            try:
                return download_file(url, report["filename"])
            except Exception as e:
                logger.debug(
                    "Germany_BVL: candidate URL %s failed: %s", url, e
                )
                continue

        return None

    def parse(self, files: list[Path]) -> list[dict]:
        """Parse all downloaded BVL files into normalized row dicts."""
        all_rows = []
        file_map = {f.name: f for f in files}

        for report in GERMANY_BVL_REPORTS:
            path = file_map.get(report["filename"])
            if path is None:
                continue
            rows = self._parse_bvl_file(path, report)
            all_rows.extend(rows)

        return all_rows

    def _parse_bvl_file(
        self, file_path: Path, report: dict
    ) -> list[dict]:
        """
        Parse a single BVL data file (Excel or CSV).
        Uses dynamic German column detection to handle format changes
        across years. Processes all detected pesticides/substances,
        translates German commodity names, and computes detection rates.
        """
        ext = file_path.suffix.lower()
        try:
            if ext in (".xlsx", ".xls"):
                df = self._read_excel(file_path)
            elif ext == ".csv":
                df = self._read_csv(file_path)
            else:
                logger.warning(
                    "Germany_BVL: unknown file format %s for %s — skipping",
                    ext, file_path.name,
                )
                return []
        except Exception as e:
            logger.error(
                "Germany_BVL: failed to read %s: %s", file_path.name, e
            )
            return []

        if df.empty:
            logger.warning("Germany_BVL: empty dataframe from %s", file_path.name)
            return []

        # Normalize column names for matching
        df.columns = [c.strip() for c in df.columns]
        logger.info(
            "Germany_BVL %s: %d rows, columns: %s",
            report["label"], len(df), list(df.columns),
        )

        # Dynamic column detection
        substance_col = self._detect_column(df, _SUBSTANCE_COL_PATTERNS)
        commodity_col = self._detect_column(df, _COMMODITY_COL_PATTERNS)
        samples_col = self._detect_column(
            df, _SAMPLES_COL_PATTERNS, _SAMPLES_EXACT_NAMES
        )
        residues_col = self._detect_column(df, _RESIDUES_COL_PATTERNS)
        level_col = self._detect_column(df, _LEVEL_COL_PATTERNS)

        if not substance_col:
            logger.warning(
                "Germany_BVL: no substance column found in %s "
                "(columns: %s) — skipping",
                file_path.name, list(df.columns),
            )
            return []
        if not commodity_col:
            logger.info(
                "Germany_BVL: no commodity column in %s — "
                "using 'all_foods' aggregate",
                file_path.name,
            )

        # Filter out rows with missing substance names
        df[substance_col] = df[substance_col].fillna("").astype(str).str.strip()
        df = df[df[substance_col] != ""]
        df = df[df[substance_col].str.lower() != "nan"]

        if df.empty:
            logger.info(
                "Germany_BVL: no substance rows in %s", report["label"]
            )
            return []

        # Normalize substance names for consistent grouping
        df["__substance_name"] = df[substance_col].str.strip()

        logger.info(
            "Germany_BVL: %d substance rows with %d unique substances in %s",
            len(df), df["__substance_name"].nunique(), report["label"],
        )

        # Aggregate by (mapped commodity category, substance name)
        from collections import defaultdict
        by_category = defaultdict(
            lambda: {"total": 0, "detected": 0, "ppb_values": [], "raw_cats": []}
        )

        for _, row in df.iterrows():
            substance_name = row["__substance_name"]

            if commodity_col:
                raw_commodity = str(row[commodity_col]).strip()
                if not raw_commodity or raw_commodity.lower() in ("nan", "gesamt", "total", "summe"):
                    continue
                mapped_commodity = self._map_german_commodity(raw_commodity)
                food_category = normalize_category(mapped_commodity)
                if not food_category:
                    food_category = mapped_commodity
                if not food_category:
                    continue
            else:
                # No commodity column — aggregate across all foods
                raw_commodity = "all_foods"
                food_category = "all_foods"

            cat = by_category[(food_category, substance_name)]

            # Sample counts
            total_samples = self._safe_int(row.get(samples_col)) if samples_col else 1
            detected_samples = self._safe_int(row.get(residues_col)) if residues_col else 0

            cat["total"] += total_samples
            cat["detected"] += detected_samples
            cat["raw_cats"].append(raw_commodity)

            # Residue level (mg/kg → ppb)
            if level_col:
                level_val = self._safe_float(row.get(level_col))
                if level_val is not None and level_val > 0:
                    cat["ppb_values"].append(level_val * 1000)

        # Build output rows
        rows = []
        for (food_category, substance_name), stats in by_category.items():
            if stats["total"] == 0:
                continue

            total = stats["total"]
            n_detected = stats["detected"]
            detection_rate = round(min(n_detected / total, 1.0), 4) if total > 0 else None
            avg_ppb = (
                round(sum(stats["ppb_values"]) / len(stats["ppb_values"]), 2)
                if stats["ppb_values"]
                else None
            )
            max_ppb = round(max(stats["ppb_values"]), 2) if stats["ppb_values"] else None
            raw_cat = ", ".join(sorted(set(stats["raw_cats"])))

            rows.append({
                "tier": 2,
                "source_name": "Germany_BVL",
                "source_url": BVL_OVERVIEW_URL,
                "report_label": report["label"],
                "published_date": report["published_date"],
                "data_year": report["data_year"],
                "food_category": food_category,
                "contaminant": substance_name,
                "raw_category": raw_cat,
                "samples_total": total,
                "samples_detected": n_detected,
                "detection_rate": detection_rate,
                "avg_ppb": avg_ppb,
                "max_ppb": max_ppb,
                "original_unit": "mg/kg",
                "unit_conversion": 1000.0,
                "methodology_note": (
                    f"BVL National Monitoring Programme ({report['data_year']}). "
                    f"Pesticide residue data for {substance_name} from "
                    "Bundesamt für Verbraucherschutz und Lebensmittelsicherheit. "
                    "Reports ALL detections (not just MRL exceedances). "
                    "German commodity names translated to English canonical categories. "
                    "Residue levels converted from mg/kg to ppb."
                ),
                "confidence": "high",
                "raw_file_path": str(file_path),
                "dedup_key": build_dedup_key(
                    "Germany_BVL", food_category, substance_name,
                    report["data_year"],
                ),
            })

        logger.info(
            "Germany_BVL: parsed %d category-substance rows from %s",
            len(rows), report["label"],
        )
        return rows

    def _read_excel(self, path: Path) -> pd.DataFrame:
        """Read Excel file (.xls or .xlsx), trying different sheet names."""
        ext = path.suffix.lower()
        # Use xlrd for old .xls format, openpyxl for .xlsx
        if ext == ".xls":
            engine = "xlrd"
        else:
            engine = "openpyxl"

        try:
            xl = pd.ExcelFile(path, engine=engine)
        except Exception:
            # Fallback: try the other engine
            fallback = "openpyxl" if engine == "xlrd" else "xlrd"
            try:
                xl = pd.ExcelFile(path, engine=fallback)
            except Exception as e:
                raise ValueError(f"Cannot read {path.name}: {e}")

        sheet_names = xl.sheet_names

        preferred_sheets = [
            "Tabelle 1", "Tabelle1", "Daten", "Ergebnisse",
            "Tabellen", "PSM-Rückstände", "Rückstände",
            "Tabelle", "Datenblatt", "Sheet1",
        ]

        target_sheet = None
        for candidate in preferred_sheets:
            if candidate in sheet_names:
                target_sheet = candidate
                break

        if target_sheet is None and sheet_names:
            target_sheet = sheet_names[0]

        if target_sheet is None:
            return pd.DataFrame()

        df = pd.read_excel(xl, sheet_name=target_sheet, header=None)

        # Find the header row — look for known German column headers
        header_idx = self._find_header_row(df)
        if header_idx is not None:
            header = df.iloc[header_idx].tolist()
            df = df.iloc[header_idx + 1:].reset_index(drop=True)
            df.columns = [str(h).strip() for h in header]
        else:
            # Use first row as header if no better match
            df.columns = [str(c).strip() for c in df.iloc[0]]
            df = df.iloc[1:].reset_index(drop=True)

        return df

    def _read_csv(self, path: Path) -> pd.DataFrame:
        """Read CSV file, trying different delimiters and encodings."""
        for encoding in ["utf-8", "latin-1", "cp1252", "iso-8859-1"]:
            for sep in [";", ",", "\t"]:
                try:
                    df = pd.read_csv(
                        path, sep=sep, encoding=encoding, low_memory=False,
                    )
                    if len(df.columns) > 1:
                        return df
                except Exception:
                    continue
        raise ValueError(
            f"Could not parse CSV file {path.name} with any encoding/delimiter"
        )

    def _find_header_row(self, df: pd.DataFrame) -> int | None:
        """
        Find the header row in a dataframe by scanning for known German
        column header keywords.  Prefers rows where most cells are non-null
        (actual column headers) over title/merged rows (single long text).
        """
        all_patterns = (
            _SUBSTANCE_COL_PATTERNS
            + _COMMODITY_COL_PATTERNS
            + _SAMPLES_COL_PATTERNS
        )
        best_idx = None
        best_score = 0
        for idx, row in df.iterrows():
            non_null = sum(1 for v in row if pd.notna(v) and str(v).strip())
            # Title/merged rows typically have 1-2 non-null cells spanning
            # the whole row; real header rows have a value in every column.
            if non_null < max(2, len(row) // 2):
                continue
            row_text = " ".join(str(v).lower() for v in row if pd.notna(v))
            matches = sum(
                1 for p in all_patterns if p.lower() in row_text
            )
            if matches >= 2 and matches > best_score:
                best_score = matches
                best_idx = int(idx)
        return best_idx

    @staticmethod
    def _detect_column(
        df: pd.DataFrame,
        patterns: list[str],
        exact_names: set[str] | None = None,
    ) -> str | None:
        """
        Find a column whose name matches any of the given patterns.
        Checks both original and lowercased column names.
        If *exact_names* is provided, also checks for exact (case-insensitive)
        matches against that set — useful for short column names like "N".
        Newlines in column names are collapsed to spaces before matching.
        """
        for col in df.columns:
            col_lower = col.lower().strip()
            col_normalized = col_lower.replace("\n", " ").replace("  ", " ")
            # Exact match first (higher priority)
            if exact_names and col_normalized in exact_names:
                return col
            # Substring match on normalized name
            for pattern in patterns:
                if pattern.lower() in col_normalized:
                    return col
        return None

    @staticmethod
    def _safe_int(value) -> int:
        """Convert a value to int, returning 0 on failure."""
        if value is None:
            return 0
        try:
            cleaned = re.sub(r"[^\d]", "", str(value))
            return int(cleaned) if cleaned else 0
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _safe_float(value) -> float | None:
        """Convert a value to float, returning None on failure."""
        if value is None:
            return None
        try:
            cleaned = str(value).replace(",", ".").strip()
            cleaned = re.sub(r"[^\d.]", "", cleaned)
            return float(cleaned) if cleaned else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _map_german_commodity(name: str) -> str:
        """
        Translate German commodity names to English canonical categories.
        Returns the best-matching English name, or the original if no match.
        """
        lower = name.lower().strip()

        # Exact word-boundary matches for common German commodity names
        mappings = {
            # Grains and cereals
            "weizen": "wheat",
            "weizenmehl": "wheat",
            "weizenvollkorn": "wheat",
            "roggen": "rye",
            "roggenmehl": "rye",
            "gerste": "barley",
            "gerstenmehl": "barley",
            "hafer": "oats",
            "haferflocken": "oats",
            "hafermehl": "oats",
            "mais": "corn",
            "maismehl": "corn",
            "maisstärke": "corn",
            "reis": "rice",
            "vollkornreis": "rice",
            "soja": "soybeans",
            "sojabohnen": "soybeans",
            "sojamehl": "soybeans",
            "raps": "canola",
            "rapssaat": "canola",
            "rapsöl": "canola",
            "getreide": "wheat",
            "getreideerzeugnisse": "wheat",
            "getreidemehl": "wheat",
            "sonnenblumen": "sunflower",
            "sonnenblumenkerne": "sunflower",
            "sonnenblumenöl": "sunflower",
            "zucker": "sugar_beets",
            "zuckerrüben": "sugar_beets",
            "hirse": "corn",
            "hirsemehl": "corn",
            "buchweizen": "buckwheat",
            "dinkel": "wheat",
            "dinkelmehl": "wheat",
            "grünkern": "wheat",
            "emmer": "wheat",
            "kamut": "wheat",
            " amarant": "corn",
            "amarant": "corn",
            "quinoa": "quinoa",
            # Fruits
            "äpfel": "fresh_fruit",
            "apfel": "fresh_fruit",
            "apfelsaft": "fresh_fruit",
            "birnen": "fresh_fruit",
            "birne": "fresh_fruit",
            "erdbeeren": "fresh_fruit",
            "erdbeere": "fresh_fruit",
            "trauben": "fresh_fruit",
            "traube": "fresh_fruit",
            "bananen": "fresh_fruit",
            "banane": "fresh_fruit",
            "orangen": "fresh_fruit",
            "orange": "fresh_fruit",
            "zitronen": "fresh_fruit",
            "zitrone": "fresh_fruit",
            "limetten": "fresh_fruit",
            "limette": "fresh_fruit",
            "mandarinen": "fresh_fruit",
            "mandarine": "fresh_fruit",
            "pfirsiche": "fresh_fruit",
            "pfirsich": "fresh_fruit",
            "pflaumen": "fresh_fruit",
            "pflaume": "fresh_fruit",
            "kirschen": "fresh_fruit",
            "kirsche": "fresh_fruit",
            "mangos": "fresh_fruit",
            "mango": "fresh_fruit",
            "kiwis": "fresh_fruit",
            "kiwi": "fresh_fruit",
            "melonen": "fresh_fruit",
            "melone": "fresh_fruit",
            "rosinen": "fresh_fruit",
            "wein": "fresh_fruit",
            "heidelbeeren": "blueberries",
            "himbeeren": "fresh_fruit",
            "himbeere": "fresh_fruit",
            "erdnüsse": "fresh_fruit",
            "erdnuss": "fresh_fruit",
            "walnüsse": "fresh_fruit",
            "walnuss": "fresh_fruit",
            "mohnsamen": "fresh_fruit",
            "koriandersamen": "fresh_vegetables",
            "avocadofrüchte": "fresh_fruit",
            "avocado": "fresh_fruit",
            "persimonen": "fresh_fruit",
            "persimonen/kakis": "fresh_fruit",
            "rhabarber": "fresh_vegetables",
            "johannisbeeren": "fresh_fruit",
            # Vegetables
            "kartoffeln": "fresh_vegetables",
            "kartoffel": "fresh_vegetables",
            "möhren": "fresh_vegetables",
            "möhre": "fresh_vegetables",
            "karotten": "fresh_vegetables",
            "karotte": "fresh_vegetables",
            "tomaten": "fresh_vegetables",
            "tomate": "fresh_vegetables",
            "tomatensaft": "fresh_vegetables",
            "salat": "fresh_vegetables",
            "kopfsalat": "fresh_vegetables",
            "eisbergsalat": "fresh_vegetables",
            "gurke": "fresh_vegetables",
            "gurken": "fresh_vegetables",
            "paprika": "fresh_vegetables",
            "zwiebeln": "fresh_vegetables",
            "zwiebel": "fresh_vegetables",
            "spargel": "fresh_vegetables",
            "auberginen": "fresh_vegetables",
            "aubergine": "fresh_vegetables",
            "kulturpilze": "fresh_vegetables",
            "pilze": "fresh_vegetables",
            "blattgewürze": "fresh_vegetables",
            "frische kräuter": "fresh_vegetables",
            "senfkörner": "fresh_vegetables",
            # Processed / other
            "brot": "wheat",
            "toastbrot": "wheat",
            "vollkornbrot": "wheat",
            "müsli": "oats",
            "müsli (haferflocken)": "oats",
            "cornflakes": "corn",
            "hülsenfrüchte": "beans",
            "hülsenfrüchte (getrocknet)": "beans",
            "bohnen": "beans",
            "linsen": "lentils",
            "kichererbsen": "chickpeas",
            "erbsen": "peas",
            "leinsamen": "canola",
            "leinensamen": "canola",
            "honig": "fresh_fruit",
            "tee": "fresh_fruit",
            "tees": "fresh_fruit",
            # Infant
            "säuglingsnahrung": "infant_cereal",
            "babybrei": "infant_cereal",
            "kindermüsli": "infant_cereal",
        }

        # Try exact match first
        if lower in mappings:
            return mappings[lower]

        # Try partial match — check if any German keyword is contained
        # Sort by length descending so longer (more specific) matches win
        for german_name in sorted(mappings.keys(), key=len, reverse=True):
            if german_name in lower:
                return mappings[german_name]

        # Fallback: classify unmapped names into broad categories
        # German fruit suffixes
        if any(s in lower for s in ["früchte", "frucht", "beeren", "beere", "melone"]):
            return "fresh_fruit"
        # German vegetable suffixes
        if any(s in lower for s in ["gemüse", "gewürz", "kräuter", "salat", "pilze"]):
            return "fresh_vegetables"
        # Frozen variants
        if "tiefgefroren" in lower:
            return "fresh_fruit" if "beere" in lower or "frucht" in lower else "fresh_vegetables"

        return name
