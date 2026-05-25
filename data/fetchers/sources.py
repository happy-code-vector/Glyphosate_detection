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
import zipfile
from pathlib import Path

import pandas as pd
import requests

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
        df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]
        logger.info("CFIA columns: %s", list(df.columns))

        product_col   = self._find_col(df, ["product", "produit", "commodity", "food_category"])
        component_col = self._find_col(df, ["component", "composant", "pesticide", "substance"])
        result_col    = self._find_col(df, ["result", "r_sultat", "concentration", "value"])
        # Match result column by partial match (encoding-safe)
        if not result_col:
            result_col = next((c for c in df.columns if "result" in c or "rsultat" in c), None)
        unit_col = self._find_col(df, ["reportunit", "unit"])

        if not product_col or not component_col or not result_col:
            raise ValueError(
                f"Required columns not found in CFIA CSV. "
                f"Available: {list(df.columns)}. "
                "The CSV structure may have changed — check the source file."
            )

        # Filter to glyphosate only (not AMPA metabolite)
        gly_df = df[df[component_col].str.lower().str.contains("glyphosate", na=False)].copy()
        if gly_df.empty:
            raise ValueError("No glyphosate rows found in CFIA CSV")

        logger.info("CFIA: %d glyphosate sample rows", len(gly_df))

        # Determine unit conversion — CFIA reports in µg/g (= mg/kg = ppm, so ×1000 for ppb)
        conversion = 1.0
        original_unit = "µg/g"
        if unit_col:
            unit_val = str(gly_df[unit_col].iloc[0]).lower()
            if "mg/kg" in unit_val or "µg/g" in unit_val or "ug/g" in unit_val:
                conversion = 1000.0
                original_unit = unit_val

        rows = []
        # First pass: collect per-product stats, then aggregate by canonical category
        product_stats = []
        for product, group in gly_df.groupby(product_col):
            raw_cat = str(product).strip()
            if not raw_cat or raw_cat.lower() in ("nan", "total", "all"):
                continue

            food_category = normalize_category(raw_cat)
            if not food_category:
                logger.debug("CFIA: no canonical category for '%s' — skipping", raw_cat)
                continue

            values = pd.to_numeric(group[result_col], errors="coerce").fillna(0)
            product_stats.append({
                "food_category": food_category,
                "raw_cat": raw_cat,
                "total": len(group),
                "detected_values": values[values > 0].tolist(),
            })

        # Second pass: aggregate across products within same canonical category
        from collections import defaultdict
        by_category = defaultdict(lambda: {"total": 0, "detected": [], "raw_cats": []})
        for ps in product_stats:
            cat = ps["food_category"]
            by_category[cat]["total"] += ps["total"]
            by_category[cat]["detected"].extend(ps["detected_values"])
            by_category[cat]["raw_cats"].append(ps["raw_cat"])

        for food_category, stats in by_category.items():
            total = stats["total"]
            n_detected = len(stats["detected"])
            detection_rate = round(n_detected / total, 4) if total > 0 else None
            avg_ppb = round(sum(stats["detected"]) / n_detected * conversion, 2) if n_detected > 0 else None
            max_ppb = round(max(stats["detected"]) * conversion, 2) if stats["detected"] else None
            raw_cat = ", ".join(sorted(set(stats["raw_cats"])))

            rows.append({
                "tier": 2,
                "source_name": "CFIA",
                "source_url": CFIA_SOURCE_URL,
                "report_label": "CFIA Glyphosate Testing 2015-2017",
                "published_date": "2019-04-01",
                "data_year": 2017,
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
                    "CFIA Safeguarding with Science: Glyphosate Testing 2015-2017. "
                    "Individual sample results aggregated by canonical food category. "
                    "LC-MS/MS method. Domestic and imported samples. "
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

# EFSA publishes enforcement data as XLSX on Zenodo.
# Table 2.2 contains individual MRL exceedance records with food matrix,
# substance name, and measured concentration (mg/kg).
EFSA_REPORTS = [
    {
        "label": "EFSA EU Pesticide Residue Monitoring 2023",
        "zenodo_record": "14765085",
        "filename": "efsa_2023_enforcement.xlsx",
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
            path = self._fetch_enforcement(report)
            paths.append(path)
        return paths

    def _fetch_enforcement(self, report: dict) -> Path:
        """Download enforcement data XLSX from Zenodo."""
        cache_path = Path(__file__).parent.parent / "raw_data" / report["filename"]

        if cache_path.exists():
            logger.info("Cache hit: %s", cache_path.name)
            return cache_path

        record_id = report["zenodo_record"]
        api_url = EFSA_ZENODO_API.format(record_id=record_id)
        resp = SESSION.get(api_url, timeout=30)
        resp.raise_for_status()
        record_data = resp.json()

        files = record_data.get("files", [])
        # Find the enforcement/supporting data XLSX (smallest XLSX, not the huge ZIP)
        xlsx_files = [
            f for f in files
            if f.get("key", "").lower().endswith(".xlsx")
            and "enforcement" in f.get("key", "").lower()
        ]
        if not xlsx_files:
            xlsx_files = [f for f in files if f.get("key", "").lower().endswith(".xlsx")]

        if not xlsx_files:
            raise RuntimeError(f"No XLSX files found in Zenodo record {record_id}")

        # Pick the smallest XLSX (enforcement data, not huge exposure assessments)
        data_file = min(xlsx_files, key=lambda f: f.get("size", 0))
        download_url = data_file.get("links", {}).get("self")
        if not download_url:
            raise RuntimeError(f"No download URL for {data_file.get('key','')}")

        return download_file(download_url, report["filename"])

    def parse(self, files: list[Path]) -> list[dict]:
        all_rows = []
        for path, report in zip(files, EFSA_REPORTS):
            rows = self._parse_enforcement(path, report)
            all_rows.extend(rows)
        return all_rows

    def _parse_enforcement(self, xlsx_path: Path, report: dict) -> list[dict]:
        """
        Parse EFSA enforcement data (Table 2.2) for glyphosate MRL exceedances.
        These are individual sample results where glyphosate exceeded the legal limit.
        Table 2.3 provides overall rates but not per-category.
        """
        df = pd.read_excel(
            xlsx_path, sheet_name="Table 2.2",
            header=None, skiprows=3
        )
        # First row after skip is the actual header
        header = df.iloc[0].tolist()
        df = df.iloc[1:].reset_index(drop=True)
        df.columns = [str(h).strip() for h in header]
        logger.info("EFSA Table 2.2 columns: %s", list(df.columns))

        # Filter to glyphosate (substance name contains "glyphosate")
        gly_mask = df["Substance Name"].str.lower().str.contains("glyphosate", na=False)
        gly_df = df[gly_mask].copy()

        if gly_df.empty:
            logger.warning("EFSA: no glyphosate rows found in %s", xlsx_path.name)
            return []

        logger.info("EFSA: %d glyphosate MRL exceedance rows", len(gly_df))

        rows = []
        for matrix, group in gly_df.groupby("Food MATRIX Name"):
            raw_cat = str(matrix).strip()
            food_category = normalize_category(raw_cat)
            if not food_category:
                logger.debug("EFSA: no canonical category for '%s'", raw_cat)
                continue

            total = len(group)
            values = pd.to_numeric(group["Result (mg/kg)"], errors="coerce").fillna(0)
            detected = values[values > 0]
            n_detected = len(detected)

            # mg/kg → ppb (× 1000)
            avg_ppb = round(float(detected.mean()) * 1000, 2) if len(detected) > 0 else None
            max_ppb = round(float(detected.max()) * 1000, 2) if len(detected) > 0 else None

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
                "detection_rate": None,
                "avg_ppb": avg_ppb,
                "max_ppb": max_ppb,
                "original_unit": "mg/kg",
                "unit_conversion": 1000.0,
                "methodology_note": (
                    "EFSA enforcement data: only samples exceeding MRL are reported. "
                    "Detection rate cannot be computed from exceedance data alone. "
                    f"{total} MRL exceedance(s) for {raw_cat} across EU member states."
                ),
                "confidence": "low",
                "raw_file_path": str(xlsx_path),
                "dedup_key": build_dedup_key("EFSA", food_category, report["data_year"]),
            })

        logger.info("EFSA: parsed %d category rows from %s", len(rows), xlsx_path.name)
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
