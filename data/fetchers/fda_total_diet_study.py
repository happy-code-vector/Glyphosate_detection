"""
fetchers/fda_total_diet_study.py

FDA Total Diet Study (TDS) — comprehensive food contaminant monitoring.

Source:
  FDA Total Diet Study (TDS) / Center for Food Safety and Applied Nutrition
  https://www.fda.gov/food/total-diet-study-center-food-safety-and-applied-nutrition

Content:
  ~280 foods tested for 400+ analytes including:
  - Perchlorate
  - PFAS (PFOA, PFOS)
  - Dioxins & Furans
  - PCBs
  - Benzene
  - Radionuclides
  - Heavy metals (lead, arsenic, cadmium, mercury)
  - Pesticides

Strategy:
  1. Check for local TDS data files (manual download)
  2. Try FDA download URLs
  3. Parse Excel/CSV files with analyte/food/concentration data
  4. Map to canonical contaminant names
  5. Insert into category_summaries (Tier 2)
"""

import logging
from pathlib import Path

from fetchers.base import BaseFetcher, RAW_DATA_DIR, SESSION
from db.database import normalize_category, build_dedup_key, get_connection

logger = logging.getLogger(__name__)

SOURCE_NAME = "FDA_TDS"

# Analyte name → canonical contaminant key mapping
ANALYTE_MAP = {
    # Heavy metals
    "lead": "lead",
    "pb": "lead",
    "inorganic arsenic": "inorganic_arsenic",
    "arsenic": "inorganic_arsenic",
    "as": "inorganic_arsenic",
    "cadmium": "cadmium",
    "cd": "cadmium",
    "mercury": "mercury",
    "hg": "mercury",
    "methylmercury": "mercury",
    # Environmental
    "perchlorate": "perchlorate",
    "pfoa": "pfas_pfoa",
    "perfluorooctanoic acid": "pfas_pfoa",
    "pfos": "pfas_pfos",
    "perfluorooctane sulfonic acid": "pfas_pfos",
    "dioxin": "dioxins",
    "tcdd": "dioxins",
    "2,3,7,8-tcdd": "dioxins",
    "dioxins": "dioxins",
    "furans": "dioxins",
    "pcb": "pcbs",
    "pcbs": "pcbs",
    "polychlorinated biphenyls": "pcbs",
    "aroclor": "pcbs",
    "benzene": "benzene",
    "cesium-137": "radionuclides",
    "strontium-90": "radionuclides",
    # Pesticides
    "glyphosate": "glyphosate",
    "atrazine": "atrazine",
    "chlorpyrifos": "chlorpyrifos",
    "imidacloprid": "imidacloprid",
}

# Unit conversion to ppb
UNIT_TO_PPB = {
    "ppb": 1.0,
    "ug/kg": 1.0,
    "µg/kg": 1.0,
    "ng/g": 1.0,
    "ppt": 0.001,  # parts per trillion → ppb
    "ng/l": 0.001,
    "ppm": 1000.0,
    "mg/kg": 1000.0,
    "ug/g": 1000.0,
    "µg/g": 1000.0,
    "mg/l": 1000.0,
    "pci/l": 1.0,  # picocuries per liter (for radionuclides)
}


class FDATotalDietStudyFetcher(BaseFetcher):
    """Fetch FDA Total Diet Study data."""

    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        """Download or locate TDS data files."""
        paths = []

        # Check for local files first
        local_patterns = [
            "tds_*", "total_diet*", "fda_tds*",
            "total-diet-study*", "fda_total_diet*",
        ]
        for pattern in local_patterns:
            for f in RAW_DATA_DIR.glob(pattern):
                if f.suffix in ('.xlsx', '.xls', '.csv') and f not in paths:
                    paths.append(f)
                    logger.info("FDA TDS: found local file %s", f.name)

        if paths:
            return paths

        # Try FDA download URLs
        urls = [
            # TDS data tables (may be outdated)
            "https://www.fda.gov/media/87289/download",
            "https://www.fda.gov/media/87291/download",
            "https://www.fda.gov/media/120377/download",
        ]

        for url in urls:
            try:
                logger.info("FDA TDS: fetching %s...", url)
                resp = SESSION.get(url, timeout=60)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    if resp.content[:2] == b'PK':  # Excel file
                        dest = RAW_DATA_DIR / f"tds_data_{len(paths)}.xlsx"
                        dest.write_bytes(resp.content)
                        paths.append(dest)
                        logger.info("FDA TDS: downloaded %s (%d bytes)", dest.name, len(resp.content))
                    elif resp.content[:1] == b'\xef' or resp.content[:1] == b'\xff':  # CSV
                        dest = RAW_DATA_DIR / f"tds_data_{len(paths)}.csv"
                        dest.write_bytes(resp.content)
                        paths.append(dest)
                        logger.info("FDA TDS: downloaded %s (%d bytes)", dest.name, len(resp.content))
            except Exception as e:
                logger.warning("FDA TDS fetch failed for %s: %s", url, e)

        if not paths:
            logger.warning("FDA TDS: no data files found.")
            logger.warning("Manual download: Go to https://www.fda.gov/food/total-diet-study-center-food-safety-and-applied-nutrition")
            logger.warning("Download TDS data tables and place them in data/raw_data/tds_*.xlsx")

        return paths

    def parse(self, files: list[Path]) -> list[dict]:
        """Parse TDS data files into category_summaries rows."""
        all_rows = []
        for path in files:
            rows = self._parse_file(path)
            all_rows.extend(rows)
        return all_rows

    def _parse_file(self, path: Path) -> list[dict]:
        """Parse a single TDS data file."""
        import pandas as pd

        logger.info("FDA TDS: parsing %s", path.name)

        try:
            if path.suffix in ('.xlsx', '.xls'):
                xl = pd.ExcelFile(path, engine='openpyxl')
                # Try each sheet
                all_rows = []
                for sheet in xl.sheet_names:
                    df = pd.read_excel(xl, sheet_name=sheet)
                    rows = self._parse_sheet(df, path, sheet)
                    all_rows.extend(rows)
                return all_rows
            else:
                df = pd.read_csv(path, encoding='latin-1')
                return self._parse_sheet(df, path, 'Sheet1')
        except Exception as e:
            logger.warning("FDA TDS: failed to read %s: %s", path.name, e)
            return []

    def _parse_sheet(self, df, path: Path, sheet_name: str) -> list[dict]:
        """Parse a single sheet into category_summaries rows."""
        import pandas as pd

        if df.empty:
            return []

        # Clean column names
        df.columns = [str(c).strip() for c in df.columns]

        # Find key columns
        food_col = self._find_col(df, ['Food', 'Food Name', 'Product', 'Commodity',
                                        'Food Description', 'food_name', 'Sample'])
        analyte_col = self._find_col(df, ['Analyte', 'Analyte Name', 'Contaminant',
                                           'Chemical', 'analyte', 'Parameter'])
        value_col = self._find_col(df, ['Concentration', 'Result', 'Level', 'Value',
                                         'Mean', 'Average', 'conc', 'Result (ppb)'])
        unit_col = self._find_col(df, ['Unit', 'Units', 'unit', 'Conc Unit'])
        year_col = self._find_col(df, ['Year', 'FY', 'Survey Year', 'data_year'])
        lod_col = self._find_col(df, ['LOD', 'Detection Limit', 'MDL', 'Limit of Detection'])

        if not food_col or not analyte_col:
            logger.warning("FDA TDS: missing required columns in sheet '%s'. Found: %s",
                           sheet_name, list(df.columns)[:10])
            return []

        rows = []
        for _, row in df.iterrows():
            food_name = str(row.get(food_col, '')).strip()
            analyte_name = str(row.get(analyte_col, '')).strip()

            if not food_name or food_name in ('nan', 'None', ''):
                continue
            if not analyte_name or analyte_name in ('nan', 'None', ''):
                continue

            # Map analyte to canonical contaminant
            contaminant = self._map_analyte(analyte_name)
            if not contaminant:
                continue  # Skip unknown analytes

            # Get measurement value
            measured_ppb = None
            if value_col:
                raw_value = row.get(value_col)
                if raw_value is not None:
                    try:
                        value = float(raw_value)
                        # Determine unit
                        unit = 'ppb'
                        if unit_col:
                            raw_unit = str(row.get(unit_col, '')).strip().lower()
                            if raw_unit in UNIT_TO_PPB:
                                unit = raw_unit
                        measured_ppb = value * UNIT_TO_PPB.get(unit, 1.0)
                    except (ValueError, TypeError):
                        pass

            # Get LOD
            lod = None
            if lod_col:
                raw_lod = row.get(lod_col)
                if raw_lod is not None:
                    try:
                        lod = float(raw_lod)
                    except (ValueError, TypeError):
                        pass

            # Get data year
            data_year = None
            if year_col:
                raw_year = row.get(year_col)
                if raw_year is not None:
                    try:
                        data_year = int(float(str(raw_year)))
                    except (ValueError, TypeError):
                        pass

            # Map food to category
            food_category = normalize_category(food_name)
            if not food_category:
                food_category = normalize_category(food_name.lower())
            if not food_category:
                food_category = 'unknown'

            # Build row
            if measured_ppb is not None and measured_ppb > 0:
                dedup = build_dedup_key(SOURCE_NAME, food_category, contaminant, data_year)
                rows.append({
                    "tier": 2,
                    "source_name": SOURCE_NAME,
                    "source_url": "https://www.fda.gov/food/total-diet-study-center-food-safety-and-applied-nutrition",
                    "report_label": f"FDA TDS - {path.stem} - {sheet_name}",
                    "published_date": None,
                    "data_year": data_year,
                    "food_category": food_category,
                    "raw_category": food_name,
                    "contaminant": contaminant,
                    "samples_total": 1,
                    "samples_detected": 1,
                    "detection_rate": 1.0,
                    "avg_ppb": round(measured_ppb, 2),
                    "max_ppb": round(measured_ppb, 2),
                    "original_unit": "ppb",
                    "unit_conversion": 1.0,
                    "methodology_note": f"FDA Total Diet Study. Analyte: {analyte_name}",
                    "confidence": "high",
                    "dedup_key": dedup,
                })

        logger.info("FDA TDS: parsed %d rows from sheet '%s'", len(rows), sheet_name)
        return rows

    def _map_analyte(self, analyte: str) -> str | None:
        """Map analyte name to canonical contaminant key."""
        lower = analyte.lower().strip()

        # Direct match
        if lower in ANALYTE_MAP:
            return ANALYTE_MAP[lower]

        # Substring match
        for key, val in ANALYTE_MAP.items():
            if key in lower or lower in key:
                return val

        return None

    @staticmethod
    def _find_col(df, candidates: list[str]) -> str | None:
        """Find a column by trying multiple candidate names."""
        for c in candidates:
            if c in df.columns:
                return c
            for col in df.columns:
                if col.lower() == c.lower():
                    return col
        for c in candidates:
            for col in df.columns:
                if c.lower() in col.lower():
                    return col
        return None
