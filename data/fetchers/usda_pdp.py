"""
fetchers/usda_pdp.py

USDA Pesticide Data Program (PDP) — Tier 2 (category aggregates).

Source:
  USDA Agricultural Marketing Service, Pesticide Data Program.
  https://www.ams.usda.gov/datasets/pdp/pdpdata

Downloads ZIP archives containing pipe-delimited .txt files with
individual sample-level pesticide residue data. Processes ALL pesticides
(not just glyphosate), aggregates by (commodity, pesticide) into
canonical food categories.

All measurement values come directly from the PDP data files —
nothing is hardcoded. PDP reports residues in ppm (mg/kg); values
are converted to ppb (x1000) for the pipeline.
"""

import logging
import zipfile
from collections import defaultdict
from pathlib import Path

import pandas as pd

from fetchers.base import BaseFetcher, download_file, RAW_DATA_DIR
from fetchers.pdp_pesticide_names import get_pesticide_name
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# USDA PDP report registry
# ─────────────────────────────────────────────────────────────────────
USDA_PDP_REPORTS = [
    {"label": "USDA PDP 2011", "url": "https://www.ams.usda.gov/sites/default/files/media/2011PDPDatabase.zip", "zip_filename": "usda_pdp_2011.zip", "data_year": 2011, "published_date": "2013-01-01"},
    {"label": "USDA PDP 2012", "url": "https://www.ams.usda.gov/sites/default/files/media/2012PDPDatabase.zip", "zip_filename": "usda_pdp_2012.zip", "data_year": 2012, "published_date": "2014-01-01"},
    {"label": "USDA PDP 2013", "url": "https://www.ams.usda.gov/sites/default/files/media/2013PDPDatabase.zip", "zip_filename": "usda_pdp_2013.zip", "data_year": 2013, "published_date": "2015-01-01"},
    {"label": "USDA PDP 2014", "url": "https://www.ams.usda.gov/sites/default/files/media/2014PDPDatabase.zip", "zip_filename": "usda_pdp_2014.zip", "data_year": 2014, "published_date": "2016-01-01"},
    {"label": "USDA PDP 2015", "url": "https://www.ams.usda.gov/sites/default/files/media/2015PDPDatabase.zip", "zip_filename": "usda_pdp_2015.zip", "data_year": 2015, "published_date": "2017-01-01"},
    {"label": "USDA PDP 2016", "url": "https://www.ams.usda.gov/sites/default/files/media/2016PDPDatabase.zip", "zip_filename": "usda_pdp_2016.zip", "data_year": 2016, "published_date": "2018-01-01"},
    {"label": "USDA PDP 2017", "url": "https://www.ams.usda.gov/sites/default/files/media/2017PDPDatabase.zip", "zip_filename": "usda_pdp_2017.zip", "data_year": 2017, "published_date": "2019-01-01"},
    {"label": "USDA PDP 2018", "url": "https://www.ams.usda.gov/sites/default/files/media/2018PDPDatabase.zip", "zip_filename": "usda_pdp_2018.zip", "data_year": 2018, "published_date": "2020-01-01"},
    {"label": "USDA PDP 2019", "url": "https://www.ams.usda.gov/sites/default/files/media/2019PDPDatabase.zip", "zip_filename": "usda_pdp_2019.zip", "data_year": 2019, "published_date": "2021-01-01"},
    {"label": "USDA PDP 2020", "url": "https://www.ams.usda.gov/sites/default/files/media/2020PDPDatabase.zip", "zip_filename": "usda_pdp_2020.zip", "data_year": 2020, "published_date": "2022-01-01"},
    {"label": "USDA PDP 2021", "url": "https://www.ams.usda.gov/sites/default/files/media/2021PDPDatabase.zip", "zip_filename": "usda_pdp_2021.zip", "data_year": 2021, "published_date": "2023-01-01"},
    {"label": "USDA PDP 2022", "url": "https://www.ams.usda.gov/sites/default/files/media/2022PDPDatabase.zip", "zip_filename": "usda_pdp_2022.zip", "data_year": 2022, "published_date": "2024-01-01"},
    {"label": "USDA PDP 2023", "url": "https://www.ams.usda.gov/sites/default/files/media/2023PDPDatabase.zip", "zip_filename": "usda_pdp_2023.zip", "data_year": 2023, "published_date": "2025-01-01"},
]

# PDP commodity name → canonical food category mapping.
COMMODITY_MAP = {
    # PDP 2-letter commodity codes
    "SY": "soybeans",       # Soybean Grain
    "CO": "corn",           # Corn Grain
    "BT": "canned_beets",   # Beets, Canned
    "BB": "blueberries",    # Blueberries, Cultivated
    "BZ": "blueberries",    # Blueberries, Frozen
    "BU": "butter",         # Butter
    "WH": "wheat",          # Wheat Flour
    "OA": "oats",           # Oats
    "RC": "rice",           # Rice
    "BA": "barley",         # Barley
    "BN": "beans",          # Beans
    "GP": "grapes",         # Grapes
    "ST": "strawberries",   # Strawberries
    "AP": "fresh_fruit",    # Apples
    "BJ": "fresh_fruit",    # Apple Juice
    "PB": "fresh_fruit",    # Peaches
    "PR": "fresh_fruit",    # Pears
    "CT": "fresh_fruit",    # Cantaloupe
    "SP": "fresh_vegetables",  # Spinach
    "PT": "fresh_vegetables",  # Potatoes
    "TM": "fresh_vegetables",  # Tomatoes
    "TP": "fresh_vegetables",  # Tomato Paste
    "TK": "fresh_vegetables",  # Tomato Ketchup/Catsup
    "CJ": "fresh_vegetables",  # Celery
    "PK": "fresh_vegetables",  # Kale
    "LT": "fresh_vegetables",  # Lettuce
    "CU": "fresh_vegetables",  # Cucumber
    "CA": "fresh_vegetables",  # Carrots
    "OP": "infant_cereal",    # Oat Products, Infant
    "IF": "infant_cereal",    # Infant Formula
    # Full commodity names (for fallback)
    "SOYBEANS": "soybeans", "SOYBEAN": "soybeans", "SOYBEAN GRAIN": "soybeans",
    "CORN GRAIN": "corn", "CORN, SWEET, FROZEN": "corn", "CORN, SWEET, CANNED": "corn",
    "CORN, SWEET": "corn", "SWEET CORN": "corn", "CORN": "corn",
    "BEETS, CANNED": "canned_beets", "CANNED BEETS": "canned_beets",
    "BLUEBERRIES": "blueberries", "BLUEBERRY": "blueberries",
    "BLUEBERRIES, FROZEN": "blueberries", "BLUEBERRIES, WILD": "blueberries",
    "BUTTER": "butter",
    "WHEAT FLOUR": "wheat", "WHEAT, FLOUR": "wheat", "WHEAT": "wheat",
    "OATS": "oats", "OAT PRODUCTS": "oats", "OAT, ROLLED": "oats",
    "RICE": "rice", "RICE, BROWN": "rice", "RICE, WHITE": "rice",
    "BARLEY": "barley", "BARLEY, PEARLED": "barley",
    "BEANS": "beans", "BEANS, DRY": "beans", "BEANS, GREEN, CANNED": "beans",
    "BEANS, SNAP": "fresh_vegetables", "BEANS, LIMA, FROZEN": "beans",
    "GRAPES": "fresh_fruit", "GRAPE JUICE": "fresh_fruit",
    "STRAWBERRIES": "fresh_fruit",
    "APPLES": "fresh_fruit", "APPLE JUICE": "fresh_fruit",
    "PEACHES": "fresh_fruit", "PEARS": "fresh_fruit",
    "CANTALOUPE": "fresh_fruit",
    "SPINACH": "fresh_vegetables", "SPINACH, FROZEN": "fresh_vegetables",
    "POTATOES": "fresh_vegetables", "POTATOES, SWEET": "fresh_vegetables",
    "TOMATOES": "fresh_vegetables", "TOMATO PASTE": "fresh_vegetables",
    "TOMATOES, CANNED": "fresh_vegetables",
    "CELERY": "fresh_vegetables",
    "KALE": "fresh_vegetables",
    "LETTUCE": "fresh_vegetables", "LETTUCE, HEAD": "fresh_vegetables",
    "CUCUMBER": "fresh_vegetables",
    "CARROTS": "fresh_vegetables",
    "PEPPERS, BELL": "fresh_vegetables",
    "ONIONS": "fresh_vegetables",
    "INFANT FORMULA": "infant_cereal",
    "OAT PRODUCTS, INFANT/TODDLER": "infant_cereal",
    "OAT PRODUCTS,INFANT/TODDLER": "infant_cereal",
}

PDP_SOURCE_URL = "https://www.ams.usda.gov/datasets/pdp/pdpdata"


class USDA_PDPFetcher(BaseFetcher):
    SOURCE_NAME = "USDA_PDP"

    def fetch(self) -> list[Path]:
        """
        Download PDP ZIP archives and extract the pipe-delimited data files.
        Returns list of extracted .txt file paths (one per year).
        """
        paths = []
        for report in USDA_PDP_REPORTS:
            year = report["data_year"]
            try:
                zip_path = download_file(
                    url=report["url"],
                    dest_filename=report["zip_filename"],
                )
            except Exception as e:
                logger.error("USDA PDP %d: download failed: %s — skipping", year, e)
                continue

            txt_path = RAW_DATA_DIR / f"usda_pdp_{year}_data.txt"
            if txt_path.exists():
                logger.info("Cache hit: %s", txt_path.name)
                paths.append(txt_path)
                continue

            try:
                extracted = self._extract_data_file(zip_path, year, txt_path)
                if extracted:
                    paths.append(txt_path)
                else:
                    logger.warning("USDA PDP %d: no data file found in ZIP — skipping year", year)
            except zipfile.BadZipFile:
                logger.error("USDA PDP %d: downloaded file is not a valid ZIP — skipping", year)
                if zip_path.exists():
                    zip_path.unlink()

        return paths

    def _extract_data_file(self, zip_path: Path, year: int, dest: Path) -> bool:
        """Find and extract the main PDP data file from the ZIP archive."""
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            txt_files = [
                n for n in names
                if n.lower().endswith(".txt")
                and not n.lower().startswith("__")
                and "readme" not in n.lower()
                and "note" not in n.lower()
            ]

            if not txt_files:
                logger.error("USDA PDP %d: no .txt data files found in ZIP. Contents: %s", year, names)
                return False

            year_str = str(year)
            pdp_match = next(
                (f for f in txt_files if "pdp" in f.lower() and year_str in f),
                None,
            )
            if pdp_match:
                data = zf.read(pdp_match)
                dest.write_bytes(data)
                logger.info("Extracted %s from %s (%d bytes)", pdp_match, zip_path.name, len(data))
                return True

            if len(txt_files) == 1:
                chosen = txt_files[0]
            else:
                file_sizes = [(f, zf.getinfo(f).file_size) for f in txt_files]
                file_sizes.sort(key=lambda x: x[1], reverse=True)
                chosen = file_sizes[0][0]

            data = zf.read(chosen)
            dest.write_bytes(data)
            logger.info("Extracted %s from %s (%d bytes)", chosen, zip_path.name, len(data))
            return True

    def parse(self, files: list[Path]) -> list[dict]:
        """
        Parse extracted PDP pipe-delimited data files.
        Processes ALL pesticides (not just glyphosate).
        Aggregates by (commodity, pesticide) into Tier 2 category rows.
        """
        all_rows = []
        file_map = {f.name: f for f in files}
        for report in USDA_PDP_REPORTS:
            year = report["data_year"]
            expected_name = f"usda_pdp_{year}_data.txt"
            path = file_map.get(expected_name)
            if path is None:
                logger.info("USDA PDP %d: no data file — skipping", year)
                continue
            rows = self._parse_pdp_year(path, report)
            all_rows.extend(rows)
        return all_rows

    # PDP Results file column layout (from USDA PDP Data Dictionary).
    _PDP_RESULTS_COLUMNS = [
        "SAMPLE_PK", "COMMOD", "COMMTYPE", "LAB", "PESTCODE",
        "TESTCLASS", "CONCEN", "LOD", "CONUNIT", "CONFMETHOD",
        "CONFMETHOD2", "ANNOTATE", "QUANTITATE", "MEAN",
        "EXTRACT", "DETERMIN",
    ]

    def _parse_pdp_year(self, data_path: Path, report: dict) -> list[dict]:
        """
        Parse a single year's PDP data file. Processes ALL pesticides.
        Aggregates by (commodity, pesticide_code) into category rows.
        """
        year = report["data_year"]

        try:
            df = pd.read_csv(
                data_path, sep="|", low_memory=False,
                header=None,
                names=self._PDP_RESULTS_COLUMNS,
                dtype=str,
                encoding="latin-1",
            )
        except Exception as e:
            logger.error("USDA PDP %d: failed to read %s: %s", year, data_path.name, e)
            return []

        logger.info("USDA PDP %d: %d total rows", year, len(df))

        # Clean pesticide codes
        df["PESTCODE"] = df["PESTCODE"].str.strip()
        df["_ppm"] = pd.to_numeric(df["CONCEN"].str.strip(), errors="coerce").fillna(0)

        # Get unique pesticide codes in this year
        unique_codes = df["PESTCODE"].dropna().unique()
        logger.info("USDA PDP %d: %d unique pesticide codes found", year, len(unique_codes))

        # Aggregate by (commodity, pestcode)
        by_cat_pest = defaultdict(
            lambda: {"total": 0, "detected": 0, "ppm_values": [], "raw_cats": []}
        )

        for (commodity, pestcode), group in df.groupby(["COMMOD", "PESTCODE"]):
            raw_cat = str(commodity).strip()
            pestcode_str = str(pestcode).strip()

            if not raw_cat or raw_cat.lower() in ("nan", "total", "all"):
                continue
            if not pestcode_str or pestcode_str.lower() in ("nan", ""):
                continue

            food_category = self._map_commodity(raw_cat)
            if not food_category:
                food_category = normalize_category(raw_cat)
            if not food_category:
                continue

            pesticide_name = get_pesticide_name(pestcode_str)
            key = (food_category, pesticide_name)

            total = len(group)
            ppm_vals = group["_ppm"]
            detected_vals = ppm_vals[ppm_vals > 0]
            n_detected = len(detected_vals)

            cat = by_cat_pest[key]
            cat["total"] += total
            cat["detected"] += n_detected
            cat["ppm_values"].extend(detected_vals.tolist())
            cat["raw_cats"].append(raw_cat)

        rows = []
        for (food_category, pesticide_name), stats in by_cat_pest.items():
            if stats["total"] == 0:
                continue

            total = stats["total"]
            n_detected = stats["detected"]
            detection_rate = round(n_detected / total, 4) if total > 0 else None

            ppm_values = stats["ppm_values"]
            if ppm_values:
                avg_ppb = round(sum(ppm_values) / len(ppm_values) * 1000, 2)
                max_ppb = round(max(ppm_values) * 1000, 2)
            else:
                avg_ppb = None
                max_ppb = None

            raw_cat = ", ".join(sorted(set(stats["raw_cats"])))

            rows.append({
                "tier": 2,
                "source_name": "USDA_PDP",
                "source_url": PDP_SOURCE_URL,
                "report_label": report["label"],
                "published_date": report["published_date"],
                "data_year": report["data_year"],
                "food_category": food_category,
                "raw_category": raw_cat,
                "contaminant": pesticide_name,
                "samples_total": total,
                "samples_detected": n_detected,
                "detection_rate": detection_rate,
                "avg_ppb": avg_ppb,
                "max_ppb": max_ppb,
                "original_unit": "ppm",
                "unit_conversion": 1000.0,
                "methodology_note": (
                    f"USDA Pesticide Data Program ({year}). "
                    f"Individual sample results for {pesticide_name}, "
                    f"aggregated by commodity. "
                    "Method: multi-residue screening including LC-MS/MS."
                ),
                "confidence": "high",
                "raw_file_path": str(data_path),
                "dedup_key": build_dedup_key(
                    "USDA_PDP", food_category, pesticide_name, report["data_year"]
                ),
            })

        logger.info(
            "USDA PDP %d: parsed %d (category, pesticide) rows from %s",
            year, len(rows), data_path.name,
        )
        return rows

    def _map_commodity(self, raw_commodity: str) -> str | None:
        """Map a PDP commodity name to a canonical food category key."""
        canonical = COMMODITY_MAP.get(raw_commodity.upper().strip())
        if canonical:
            return canonical

        upper = raw_commodity.upper().strip()
        for pdp_name, canonical_key in COMMODITY_MAP.items():
            if pdp_name in upper or upper in pdp_name:
                return canonical_key

        return None
