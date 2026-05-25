"""
fetchers/cfia.py  /  fetchers/efsa.py  /  fetchers/fda.py

Structured government data sources — all Tier 2 (category aggregates).
All values computed from raw data files, nothing hardcoded.
"""

# ══════════════════════════════════════════════════════════════════════
# CFIA
# ══════════════════════════════════════════════════════════════════════

import io
import logging
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from fetchers.base import BaseFetcher, download_file, SESSION
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# CFIA — Canada Food Inspection Agency
# ─────────────────────────────────────────────────────────────────────

# The peer-reviewed scientific publication from CFIA contains structured
# supplementary tables (Tables S2–S7) with per-category breakdown.
# Primary source: pubs.acs.org/doi/10.1021/acs.jafc.9b07819
# The Open Government Portal CSV: open.canada.ca dataset
CFIA_GOV_PORTAL_URL = (
    "https://open.canada.ca/data/en/dataset/"
    "906cd35c-d396-4999-9a9f-f5351796661f"
)
# Direct CSV link (retrieved from portal — may need update if portal changes)
CFIA_CSV_URL = (
    "https://open.canada.ca/data/dataset/"
    "906cd35c-d396-4999-9a9f-f5351796661f/resource/"
    "glyphosate_food_residues_2015_2017.csv"
)
CFIA_FILENAME = "cfia_glyphosate_2015_2017.csv"
CFIA_SOURCE_URL = "https://inspection.canada.ca/en/food-safety-industry/food-chemistry-and-microbiology/food-safety-testing-reports-and-journal-articles/executive-summary"


class CFIAFetcher(BaseFetcher):
    SOURCE_NAME = "CFIA"

    def fetch(self) -> list[Path]:
        """
        Attempt to download the CFIA CSV from Open Government Portal.
        If direct URL fails (portal URL structure can change), scrape the
        portal page to find the current CSV resource URL.
        """
        try:
            path = download_file(CFIA_CSV_URL, CFIA_FILENAME)
            return [path]
        except Exception as e:
            logger.warning("Direct CFIA CSV URL failed: %s — trying portal page", e)
            return [self._fetch_via_portal()]

    def _fetch_via_portal(self) -> Path:
        """Scrape Open Government Portal to find the real CSV download link."""
        from bs4 import BeautifulSoup
        from fetchers.base import fetch_page

        html = fetch_page(CFIA_GOV_PORTAL_URL)
        soup = BeautifulSoup(html, "html.parser")

        # Portal lists resources as links ending in .csv
        csv_links = [
            a["href"] for a in soup.find_all("a", href=True)
            if a["href"].endswith(".csv") and "glyphosate" in a["href"].lower()
        ]
        if not csv_links:
            # Fallback: any .csv resource on the page
            csv_links = [
                a["href"] for a in soup.find_all("a", href=True)
                if a["href"].endswith(".csv")
            ]

        if not csv_links:
            raise RuntimeError(
                "Could not find CSV download link on CFIA Open Government Portal. "
                f"Visit {CFIA_GOV_PORTAL_URL} and find the correct CSV URL."
            )

        csv_url = csv_links[0]
        if not csv_url.startswith("http"):
            csv_url = "https://open.canada.ca" + csv_url

        return download_file(csv_url, CFIA_FILENAME)

    def parse(self, files: list[Path]) -> list[dict]:
        df = pd.read_csv(files[0], low_memory=False)

        # Normalize column names: lowercase, strip whitespace, replace spaces with _
        df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]
        logger.info("CFIA columns: %s", list(df.columns))

        # Identify required columns dynamically
        category_col = self._find_col(df, ["food_category", "category", "commodity", "food_type"])
        total_col    = self._find_col(df, ["total_samples", "total", "n_samples", "samples"])
        detected_col = self._find_col(df, ["samples_detected", "detected", "positive", "n_detected"])
        mean_col     = self._find_col(df, ["mean", "avg", "mean_concentration", "average"])
        max_col      = self._find_col(df, ["max", "maximum", "max_concentration"])

        if not category_col or not total_col:
            raise ValueError(
                f"Required columns not found in CFIA CSV. "
                f"Available: {list(df.columns)}. "
                "The CSV structure may have changed — check the source file."
            )

        rows = []
        for _, row in df.iterrows():
            raw_cat = str(row[category_col]).strip()
            if not raw_cat or raw_cat.lower() in ("nan", "total", "all"):
                continue

            food_category = normalize_category(raw_cat)
            if not food_category:
                logger.debug("CFIA: no canonical category for '%s' — skipping", raw_cat)
                continue

            total = int(row[total_col]) if total_col and pd.notna(row[total_col]) else None
            detected = int(row[detected_col]) if detected_col and pd.notna(row[detected_col]) else None
            detection_rate = round(detected / total, 4) if total and detected is not None else None

            # CFIA reports concentrations in mg/kg — convert to ppb (× 1000)
            avg_ppb = None
            if mean_col and pd.notna(row.get(mean_col)):
                avg_ppb = round(float(row[mean_col]) * 1000, 2)
            max_ppb = None
            if max_col and pd.notna(row.get(max_col)):
                max_ppb = round(float(row[max_col]) * 1000, 2)

            rows.append({
                "tier": 2,
                "source_name": "CFIA",
                "source_url": CFIA_SOURCE_URL,
                "report_label": "CFIA Glyphosate Testing 2015-2016",
                "published_date": "2017-04-01",
                "data_year": 2017,
                "food_category": food_category,
                "raw_category": raw_cat,
                "samples_total": total,
                "samples_detected": detected,
                "detection_rate": detection_rate,
                "avg_ppb": avg_ppb,
                "max_ppb": max_ppb,
                "original_unit": "mg/kg",
                "unit_conversion": 1000.0,
                "methodology_note": (
                    "CFIA Safeguarding with Science: Glyphosate Testing 2015-2016. "
                    "LC-MS/MS method. 7,955 domestic and imported samples. "
                    "No brand names disclosed."
                ),
                "confidence": "medium",
                "raw_file_path": str(files[0]),
                "dedup_key": build_dedup_key("CFIA", food_category, "2017"),
            })

        logger.info("CFIA: parsed %d category rows", len(rows))
        return rows

    def _find_col(self, df, candidates: list[str]) -> str | None:
        for col in candidates:
            if col in df.columns:
                return col
        return None


# ══════════════════════════════════════════════════════════════════════
# EFSA
# ══════════════════════════════════════════════════════════════════════

# EFSA publishes raw data as ZIP files on Zenodo.
# Each ZIP contains multiple CSVs in SSD2 format.
# Glyphosate substance code: typically contains 'GLY' or 'glyphosate' in param_en.
EFSA_REPORTS = [
    {
        "label": "EFSA EU Pesticide Residue Monitoring 2022",
        "zenodo_record": "10853986",
        "filename_prefix": "efsa_2022",
        "published_date": "2024-04-01",
        "data_year": 2022,
        "source_url": "https://zenodo.org/records/10853986",
    },
    {
        "label": "EFSA EU Pesticide Residue Monitoring 2023",
        "zenodo_record": "14765085",
        "filename_prefix": "efsa_2023",
        "published_date": "2025-01-01",
        "data_year": 2023,
        "source_url": "https://zenodo.org/records/14765085",
    },
]

EFSA_ZENODO_API = "https://zenodo.org/api/records/{record_id}"


class EFSAFetcher(BaseFetcher):
    SOURCE_NAME = "EFSA"

    def fetch(self) -> list[Path]:
        paths = []
        for report in EFSA_REPORTS:
            path = self._fetch_record(report)
            paths.append(path)
        return paths

    def _fetch_record(self, report: dict) -> Path:
        """
        Use Zenodo API to find the correct data CSV inside the record,
        then download it. This handles Zenodo file naming changes gracefully.
        """
        record_id = report["zenodo_record"]
        cache_path = Path(__file__).parent.parent / "raw_data" / f"{report['filename_prefix']}.csv"

        if cache_path.exists():
            logger.info("Cache hit: %s", cache_path.name)
            return cache_path

        # Query Zenodo API to get file list for this record
        api_url = EFSA_ZENODO_API.format(record_id=record_id)
        resp = SESSION.get(api_url, timeout=30)
        resp.raise_for_status()
        record_data = resp.json()

        files = record_data.get("files", [])
        if not files:
            raise RuntimeError(f"No files found in Zenodo record {record_id}")

        # Find the main occurrence/monitoring data file
        # Priority: files with "occurrence" or "monitoring" in name, or largest CSV
        data_file = None
        for f in files:
            fname = f.get("key", "").lower()
            if any(kw in fname for kw in ["occurrence", "monitoring", "residue_data"]):
                if fname.endswith(".csv") or fname.endswith(".zip"):
                    data_file = f
                    break

        if not data_file:
            # Fallback: largest file (usually the main data file)
            data_file = max(files, key=lambda f: f.get("size", 0))

        download_url = data_file.get("links", {}).get("self") or data_file.get("links", {}).get("download")
        if not download_url:
            raise RuntimeError(f"Could not find download URL in Zenodo record {record_id}")

        # If it's a ZIP, download and extract the right CSV
        fname = data_file.get("key", "")
        if fname.endswith(".zip"):
            zip_path = Path(__file__).parent.parent / "raw_data" / f"{report['filename_prefix']}.zip"
            download_file(download_url, zip_path.name)
            return self._extract_csv_from_zip(zip_path, cache_path)
        else:
            return download_file(download_url, cache_path.name)

    def _extract_csv_from_zip(self, zip_path: Path, dest: Path) -> Path:
        with zipfile.ZipFile(zip_path) as zf:
            csv_files = sorted(
                [f for f in zf.namelist() if f.endswith(".csv")],
                key=lambda f: zf.getinfo(f).file_size,
                reverse=True  # largest CSV is most likely the data file
            )
            if not csv_files:
                raise RuntimeError(f"No CSV files found inside {zip_path.name}")

            # Prefer files with "occurrence" or "monitoring" in name
            target = next(
                (f for f in csv_files if any(
                    kw in f.lower() for kw in ["occurrence", "monitoring", "residue"]
                )),
                csv_files[0]  # fallback: largest
            )
            dest.write_bytes(zf.read(target))
            logger.info("Extracted %s from %s", target, zip_path.name)
        return dest

    def parse(self, files: list[Path]) -> list[dict]:
        all_rows = []
        for path, report in zip(files, EFSA_REPORTS):
            rows = self._parse_efsa_csv(path, report)
            all_rows.extend(rows)
        return all_rows

    def _parse_efsa_csv(self, csv_path: Path, report: dict) -> list[dict]:
        """
        EFSA SSD2 format. Key columns (may vary slightly by year):
          param_en / paramText  — pesticide name
          matrix_en / matrixText — food matrix
          result_value / resVal  — concentration
          result_lod / resLOD    — limit of detection
          unit                   — concentration unit
        """
        df = pd.read_csv(csv_path, low_memory=False, sep=None, engine="python")
        df.columns = [c.lower().strip() for c in df.columns]
        logger.info("EFSA columns (%s): %s", csv_path.name, list(df.columns))

        # Find columns
        param_col  = self._find_col(df, ["param_en", "paramtext", "param", "pesticide", "substance"])
        matrix_col = self._find_col(df, ["matrix_en", "matrixtext", "matrix", "commodity"])
        value_col  = self._find_col(df, ["result_value", "resval", "value", "concentration"])
        lod_col    = self._find_col(df, ["result_lod", "reslod", "lod"])
        unit_col   = self._find_col(df, ["unit", "result_unit", "unit_en"])

        if not param_col or not matrix_col or not value_col:
            raise ValueError(
                f"Required EFSA columns not found in {csv_path.name}. "
                f"Available: {list(df.columns)}"
            )

        # Filter to glyphosate only
        gly_mask = df[param_col].str.lower().str.contains("glyphosate", na=False)
        gly_df = df[gly_mask].copy()

        if gly_df.empty:
            logger.warning("No glyphosate rows found in %s", csv_path.name)
            return []

        logger.info("EFSA: %d glyphosate rows found in %s", len(gly_df), csv_path.name)

        rows = []
        for matrix, group in gly_df.groupby(matrix_col):
            raw_cat = str(matrix).strip()
            food_category = normalize_category(raw_cat)
            if not food_category:
                logger.debug("EFSA: no canonical category for '%s'", raw_cat)
                continue

            total = len(group)
            # "detected" = value above LOD
            if lod_col and lod_col in group.columns:
                detected_mask = group[value_col] > group[lod_col].fillna(0)
            else:
                detected_mask = group[value_col] > 0
            n_detected = int(detected_mask.sum())

            detected_values = group.loc[detected_mask, value_col].dropna()

            # Determine unit and convert to ppb
            unit = ""
            if unit_col:
                unit_vals = group[unit_col].dropna().unique()
                unit = unit_vals[0].lower() if len(unit_vals) > 0 else ""
            conversion = 1000.0 if "mg/kg" in unit else 1.0

            avg_ppb = round(float(detected_values.mean()) * conversion, 2) if len(detected_values) > 0 else None
            max_ppb = round(float(detected_values.max()) * conversion, 2) if len(detected_values) > 0 else None
            detection_rate = round(n_detected / total, 4) if total > 0 else None

            rows.append({
                "tier": 2,
                "source_name": "EFSA",
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
                "original_unit": unit or "mg/kg",
                "unit_conversion": conversion,
                "methodology_note": (
                    "EFSA EU coordinated control programme. "
                    "Note: glyphosate requires SRM method — "
                    "not all EU member states report it."
                ),
                "confidence": "medium",
                "raw_file_path": str(csv_path),
                "dedup_key": build_dedup_key("EFSA", food_category, report["data_year"]),
            })

        logger.info("EFSA: parsed %d category rows from %s", len(rows), csv_path.name)
        return rows

    def _find_col(self, df, candidates):
        for col in candidates:
            if col in df.columns:
                return col
        return None


# ══════════════════════════════════════════════════════════════════════
# FDA
# ══════════════════════════════════════════════════════════════════════

# FDA Pesticide Residue Monitoring Program — annual TXT files
# FY2023 is current. Update FDA_REPORTS when new FY data is released.
FDA_BASE = "https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-report-and-data-fy-"
FDA_REPORTS = [
    {
        "label": "FDA Pesticide Monitoring FY2023",
        "year": 2023,
        "sample_file_url": f"{FDA_BASE}2023",   # landing page — real URLs below
        "sample_zip": "https://www.fda.gov/media/161430/download",  # SampleData2023.zip
        "chem_zip":   "https://www.fda.gov/media/161432/download",  # Chemical2023.zip
        "prod_file":  "https://www.fda.gov/media/161433/download",  # ProdCode.txt
        "source_url": "https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-report-and-data-fy-2023",
        "published_date": "2025-01-01",
        "data_year": 2023,
    },
]


class FDAFetcher(BaseFetcher):
    SOURCE_NAME = "FDA"

    def fetch(self) -> list[Path]:
        raw = Path(__file__).parent.parent / "raw_data"
        paths = []
        for report in FDA_REPORTS:
            year = report["year"]
            sample_path = self._get_txt_from_zip(
                report["sample_zip"], f"fda_{year}_samples.zip", f"SampleData{year}.txt"
            )
            chem_path = self._get_txt_from_zip(
                report["chem_zip"], f"fda_{year}_chemical.zip", f"Chemical{year}.txt"
            )
            prod_path = download_file(report["prod_file"], f"fda_{year}_prodcode.txt")
            paths.append((sample_path, chem_path, prod_path, report))
        return paths

    def _get_txt_from_zip(self, zip_url: str, zip_name: str, txt_name: str) -> Path:
        raw = Path(__file__).parent.parent / "raw_data"
        txt_path = raw / txt_name
        if txt_path.exists():
            logger.info("Cache hit: %s", txt_name)
            return txt_path
        zip_path = download_file(zip_url, zip_name)
        with zipfile.ZipFile(zip_path) as zf:
            if txt_name not in zf.namelist():
                available = zf.namelist()
                # Try case-insensitive match
                match = next(
                    (f for f in available if f.lower() == txt_name.lower()), None
                )
                if not match:
                    raise ValueError(
                        f"{txt_name} not found in {zip_name}. "
                        f"Available files: {available}"
                    )
                txt_name = match
            txt_path.write_bytes(zf.read(txt_name))
        return txt_path

    def parse(self, files) -> list[dict]:
        all_rows = []
        for sample_path, chem_path, prod_path, report in files:
            rows = self._parse_fda(sample_path, chem_path, prod_path, report)
            all_rows.extend(rows)
        return all_rows

    def _parse_fda(self, sample_path, chem_path, prod_path, report) -> list[dict]:
        """
        FDA files are tab-delimited TXT. Columns documented in FDA User Manual PDF.
        SampleData: SAMPLE_ID, PROD_CODE, CHEM_CODE, CONCEN, UNIT, ...
        Chemical:   CHEM_CODE, CHEM_NAME, ...
        ProdCode:   PROD_CODE, PRODUCT, ...
        """
        samples  = pd.read_csv(sample_path, sep="\t", low_memory=False)
        chemicals = pd.read_csv(chem_path,  sep="\t", low_memory=False)
        products  = pd.read_csv(prod_path,   sep="\t", low_memory=False)

        # Normalize column names
        for df in [samples, chemicals, products]:
            df.columns = [c.upper().strip() for c in df.columns]

        logger.info("FDA sample columns: %s", list(samples.columns))
        logger.info("FDA chemical columns: %s", list(chemicals.columns))
        logger.info("FDA product columns: %s", list(products.columns))

        # Find glyphosate chemical code(s)
        chem_name_col = self._find_col(chemicals, ["CHEM_NAME", "CHEMICAL_NAME", "NAME", "PESTICIDE"])
        chem_code_col = self._find_col(chemicals, ["CHEM_CODE", "CHEMICAL_CODE", "CODE"])
        if not chem_name_col or not chem_code_col:
            raise ValueError(f"Cannot find chemical name/code columns. Available: {list(chemicals.columns)}")

        gly_codes = chemicals[
            chemicals[chem_name_col].str.lower().str.contains("glyphosate", na=False)
        ][chem_code_col].tolist()

        if not gly_codes:
            logger.warning("FDA: no glyphosate rows found in chemical file")
            return []

        logger.info("FDA: glyphosate chemical codes: %s", gly_codes)

        # Filter samples to glyphosate
        sample_chem_col = self._find_col(samples, ["CHEM_CODE", "CHEMICAL_CODE", "PESTICIDE_CODE"])
        gly_samples = samples[samples[sample_chem_col].isin(gly_codes)].copy()

        if gly_samples.empty:
            logger.warning("FDA: no glyphosate sample results found")
            return []

        # Merge product names
        prod_code_col_s = self._find_col(gly_samples, ["PROD_CODE", "PRODUCT_CODE"])
        prod_code_col_p = self._find_col(products, ["PROD_CODE", "PRODUCT_CODE"])
        prod_name_col   = self._find_col(products, ["PRODUCT", "PROD_NAME", "FOOD_ITEM"])
        conc_col        = self._find_col(gly_samples, ["CONCEN", "CONCENTRATION", "RESULT"])
        unit_col        = self._find_col(gly_samples, ["UNIT", "RESULT_UNIT"])

        if prod_code_col_s and prod_code_col_p:
            gly_samples = gly_samples.merge(
                products[[prod_code_col_p, prod_name_col]].drop_duplicates(),
                left_on=prod_code_col_s,
                right_on=prod_code_col_p,
                how="left"
            )

        rows = []
        for prod_code, group in gly_samples.groupby(prod_code_col_s):
            raw_cat = str(group[prod_name_col].iloc[0]).strip() if prod_name_col else str(prod_code)
            food_category = normalize_category(raw_cat)
            if not food_category:
                logger.debug("FDA: no canonical category for '%s'", raw_cat)
                continue

            total = len(group)
            conc_values = pd.to_numeric(group[conc_col], errors="coerce") if conc_col else pd.Series([])
            detected = conc_values[conc_values > 0]
            n_detected = len(detected)
            detection_rate = round(n_detected / total, 4) if total > 0 else None

            # FDA concentrations in ppm (mg/kg) → ppb × 1000
            unit = str(group[unit_col].iloc[0]).lower() if unit_col else "ppm"
            conversion = 1000.0 if "ppm" in unit or "mg/kg" in unit else 1.0
            avg_ppb = round(float(detected.mean()) * conversion, 2) if len(detected) > 0 else None
            max_ppb = round(float(detected.max()) * conversion, 2) if len(detected) > 0 else None

            rows.append({
                "tier": 2,
                "source_name": "FDA",
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
                "original_unit": unit,
                "unit_conversion": conversion,
                "methodology_note": "FDA Pesticide Residue Monitoring Program. US regulatory monitoring data.",
                "confidence": "high",
                "raw_file_path": str(sample_path),
                "dedup_key": build_dedup_key("FDA", food_category, report["data_year"]),
            })

        logger.info("FDA: parsed %d category rows", len(rows))
        return rows

    def _find_col(self, df, candidates):
        for col in candidates:
            if col in df.columns:
                return col
        return None
