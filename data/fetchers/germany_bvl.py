"""
fetchers/germany_bvl.py

Germany BVL (Bundesamt für Verbraucherschutz und Lebensmittelsicherheit)
National Pesticide Monitoring Programme — Tier 2 (category aggregates).

Source:
  BVL "Nationale Berichterstattung Pflanzenschutzmittelrückstände"
  https://www.bvl.bund.de/DE/Arbeitsbereiche/01_Lebensmittel/01_Aufgaben/
      02_AmtlicheLebensmittelueberwachung/07_PSMRueckstaende/lm_nbpsm_node.html

Years: 2011–2022. Format: Excel/CSV with German-language column headers.

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

# Registry of BVL national monitoring reports for 2011–2022.
# Known direct download URLs are included where available; many will require
# scraping the overview page because BVL restructures its site frequently.
GERMANY_BVL_REPORTS = [
    {
        "label": "Germany BVL National Monitoring 2011",
        "year": 2011,
        "filename": "bvl_2011_national_monitoring.xlsx",
        "direct_url": "",
        "published_date": "2013-06-01",
        "data_year": 2011,
    },
    {
        "label": "Germany BVL National Monitoring 2012",
        "year": 2012,
        "filename": "bvl_2012_national_monitoring.xlsx",
        "direct_url": "",
        "published_date": "2014-06-01",
        "data_year": 2012,
    },
    {
        "label": "Germany BVL National Monitoring 2013",
        "year": 2013,
        "filename": "bvl_2013_national_monitoring.xlsx",
        "direct_url": "",
        "published_date": "2015-06-01",
        "data_year": 2013,
    },
    {
        "label": "Germany BVL National Monitoring 2014",
        "year": 2014,
        "filename": "bvl_2014_national_monitoring.xlsx",
        "direct_url": "",
        "published_date": "2016-06-01",
        "data_year": 2014,
    },
    {
        "label": "Germany BVL National Monitoring 2015",
        "year": 2015,
        "filename": "bvl_2015_national_monitoring.xlsx",
        "direct_url": "",
        "published_date": "2017-06-01",
        "data_year": 2015,
    },
    {
        "label": "Germany BVL National Monitoring 2016",
        "year": 2016,
        "filename": "bvl_2016_national_monitoring.xlsx",
        "direct_url": "",
        "published_date": "2018-06-01",
        "data_year": 2016,
    },
    {
        "label": "Germany BVL National Monitoring 2017",
        "year": 2017,
        "filename": "bvl_2017_national_monitoring.xlsx",
        "direct_url": "",
        "published_date": "2019-06-01",
        "data_year": 2017,
    },
    {
        "label": "Germany BVL National Monitoring 2018",
        "year": 2018,
        "filename": "bvl_2018_national_monitoring.xlsx",
        "direct_url": "",
        "published_date": "2020-06-01",
        "data_year": 2018,
    },
    {
        "label": "Germany BVL National Monitoring 2019",
        "year": 2019,
        "filename": "bvl_2019_national_monitoring.xlsx",
        "direct_url": "",
        "published_date": "2021-06-01",
        "data_year": 2019,
    },
    {
        "label": "Germany BVL National Monitoring 2020",
        "year": 2020,
        "filename": "bvl_2020_national_monitoring.xlsx",
        "direct_url": "",
        "published_date": "2022-06-01",
        "data_year": 2020,
    },
    {
        "label": "Germany BVL National Monitoring 2021",
        "year": 2021,
        "filename": "bvl_2021_national_monitoring.xlsx",
        "direct_url": "",
        "published_date": "2023-06-01",
        "data_year": 2021,
    },
    {
        "label": "Germany BVL National Monitoring 2022",
        "year": 2022,
        "filename": "bvl_2022_national_monitoring.xlsx",
        "direct_url": "",
        "published_date": "2024-06-01",
        "data_year": 2022,
    },
]

# German substance names to exclude (metabolites, not glyphosate itself)
_EXCLUDED_SUBSTANCES = {
    "ampa",
    "aminomethylphosphonsäure",
    "aminomethylphosphonsaeure",
    "n-acetyl-glyphosat",
    "n-acetyl glyphosate",
}

# German column header patterns for dynamic detection
_SUBSTANCE_COL_PATTERNS = [
    "wirkstoff", "pflanzenschutzmittel", "substance", "pestizid",
    "wirkstoffe", "parameter", "analyt",
]
_COMMODITY_COL_PATTERNS = [
    "lebensmittel", "matrix", " commodity", "produkt", "lebensmittelgruppe",
    "probe", "warengruppe", "food", "product",
]
_SAMPLES_COL_PATTERNS = [
    "anzahl prober", "anzahl", "proben", "anzahl_proben", "gesamt",
    "anzahl der prober", "untersuchte prober", "number of samples",
    "gesamtzahl", "anzahl untersuchte",
]
_RESIDUES_COL_PATTERNS = [
    "davon mit rückständen", "rückstände", "mit rückständen",
    "davon mit rueckstaenden", "positiv", "fundhäufigkeit", "detektiert",
    "mit rückstand", "anzahl positiv", "davon positiv",
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

    def _fetch_report(self, report: dict) -> Path | None:
        """Download a single BVL report, with caching and fallback."""
        cache_path = RAW_DATA_DIR / report["filename"]
        if cache_path.exists():
            logger.info("Cache hit: %s", report["filename"])
            return cache_path

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
        across years. Filters for glyphosate, excludes AMPA, translates
        German commodity names, and computes detection rates.
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
        samples_col = self._detect_column(df, _SAMPLES_COL_PATTERNS)
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
            logger.warning(
                "Germany_BVL: no commodity column found in %s "
                "(columns: %s) — skipping",
                file_path.name, list(df.columns),
            )
            return []

        # Filter for glyphosate
        gly_mask = (
            df[substance_col]
            .astype(str)
            .str.lower()
            .str.strip()
            .apply(lambda s: "glyphosat" in s)
        )
        gly_df = df[gly_mask].copy()

        if gly_df.empty:
            logger.info(
                "Germany_BVL: no glyphosate rows in %s", report["label"]
            )
            return []

        # Exclude AMPA and other metabolites
        for exclude_term in _EXCLUDED_SUBSTANCES:
            gly_df = gly_df[
                ~gly_df[substance_col]
                .astype(str)
                .str.lower()
                .str.contains(exclude_term, na=False)
            ]

        if gly_df.empty:
            logger.info(
                "Germany_BVL: no glyphosate rows after excluding metabolites in %s",
                report["label"],
            )
            return []

        logger.info(
            "Germany_BVL: %d glyphosate rows in %s",
            len(gly_df), report["label"],
        )

        # Aggregate by mapped commodity category
        from collections import defaultdict
        by_category = defaultdict(
            lambda: {"total": 0, "detected": 0, "ppb_values": [], "raw_cats": []}
        )

        for _, row in gly_df.iterrows():
            raw_commodity = str(row[commodity_col]).strip()
            if not raw_commodity or raw_commodity.lower() in ("nan", "gesamt", "total", "summe"):
                continue

            mapped_commodity = self._map_german_commodity(raw_commodity)
            food_category = normalize_category(mapped_commodity)
            if not food_category:
                food_category = mapped_commodity
            if not food_category:
                continue

            cat = by_category[food_category]

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
                    "German-language pesticide residue data from "
                    "Bundesamt für Verbraucherschutz und Lebensmittelsicherheit. "
                    "Reports ALL detections (not just MRL exceedances). "
                    "German commodity names translated to English canonical categories. "
                    "Residue levels converted from mg/kg to ppb."
                ),
                "confidence": "high",
                "raw_file_path": str(file_path),
                "dedup_key": build_dedup_key(
                    "Germany_BVL", food_category, report["data_year"]
                ),
            })

        logger.info(
            "Germany_BVL: parsed %d category rows from %s",
            len(rows), report["label"],
        )
        return rows

    def _read_excel(self, path: Path) -> pd.DataFrame:
        """Read Excel file, trying different sheet names."""
        import openpyxl

        # Try common sheet name patterns for BVL data
        wb = openpyxl.load_workbook(path, read_only=True)
        sheet_names = wb.sheetnames
        wb.close()

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

        df = pd.read_excel(path, sheet_name=target_sheet, header=None)

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
        column header keywords.
        """
        all_patterns = (
            _SUBSTANCE_COL_PATTERNS
            + _COMMODITY_COL_PATTERNS
            + _SAMPLES_COL_PATTERNS
        )
        for idx, row in df.iterrows():
            row_text = " ".join(str(v).lower() for v in row if pd.notna(v))
            matches = sum(
                1 for p in all_patterns if p.lower() in row_text
            )
            if matches >= 2:
                return int(idx)
        return None

    @staticmethod
    def _detect_column(df: pd.DataFrame, patterns: list[str]) -> str | None:
        """
        Find a column whose name matches any of the given patterns.
        Checks both original and lowercased column names.
        """
        for col in df.columns:
            col_lower = col.lower().strip()
            for pattern in patterns:
                if pattern.lower() in col_lower:
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
            "erbsen": "beans",
            "leinsamen": "flax",
            "leinensamen": "flax",
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

        return name
