"""
fetchers/fda_total_diet_study.py

FDA Total Diet Study (TDS) — comprehensive food contaminant monitoring.

Source:
  FDA Total Diet Study (TDS) / Center for Food Safety and Applied Nutrition
  https://www.fda.gov/food/total-diet-study-center-food-safety-and-applied-nutrition

Content:
  ~280 foods tested for 400+ analytes including:
  - Heavy metals (lead, arsenic, cadmium, mercury)
  - Perchlorate
  - PFAS (PFOA, PFOS)
  - Dioxins & Furans, PCBs
  - Benzene
  - Radionuclides (Cesium-137, Strontium-90, Potassium-40)
  - Pesticides

File formats handled:
  1. TDS_Elements_Report.csv — CSV, columns: fiscal_year, tds_food_name, display_analyte, units, upper_bound
  2. TDS_Radionuclides_Report.csv — CSV, columns: fiscal_year, tds_food_desc, analyte, units, concentration
  3. TDS_Pesticides_Report_ByYear.xlsx — Excel, columns: fiscal_year, tds_food_desc, analyte, etc.
  4. TDS-ReportSupplement-*.xlsx — Excel, columns: TDS Food Description, Analyte (units), Mean Conc.
  5. Downloaded TSV files — tab-separated, columns: FiscalYear, TDSFoodDescription, Analyte, Units, Concentration

Strategy:
  1. Scan data/raw_data/tds/ for all TDS files
  2. Auto-detect format (CSV, TSV, Excel)
  3. Parse and normalize to category_summaries rows
  4. Insert into database
"""

import logging
import re
from pathlib import Path

from fetchers.base import BaseFetcher, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

SOURCE_NAME = "FDA_TDS"

# Analyte name → canonical contaminant key mapping
ANALYTE_MAP = {
    # Heavy metals
    "lead": "lead", "pb": "lead",
    "inorganic arsenic": "inorganic_arsenic", "arsenic": "inorganic_arsenic", "as": "inorganic_arsenic",
    "cadmium": "cadmium", "cd": "cadmium",
    "mercury": "mercury", "hg": "mercury", "methylmercury": "mercury",
    # Environmental
    "perchlorate": "perchlorate",
    "pfoa": "pfas_pfoa", "perfluorooctanoic acid": "pfas_pfoa",
    "pfos": "pfas_pfos", "perfluorooctane sulfonic acid": "pfas_pfos",
    "dioxin": "dioxins", "tcdd": "dioxins", "2,3,7,8-tcdd": "dioxins",
    "pcb": "pcbs", "polychlorinated biphenyls": "pcbs", "aroclor": "pcbs",
    "benzene": "benzene",
    "cesium-137": "radionuclides", "137-cs": "radionuclides", "137cs": "radionuclides",
    "strontium-90": "radionuclides", "90-sr": "radionuclides", "90sr": "radionuclides",
    "potassium-40": "radionuclides", "40-k": "radionuclides", "40k": "radionuclides",
    # Pesticides
    "glyphosate": "glyphosate", "atrazine": "atrazine", "chlorpyrifos": "chlorpyrifos",
}

# Unit conversion to ppb
UNIT_TO_PPB = {
    "ppb": 1.0, "ug/kg": 1.0, "µg/kg": 1.0, "ng/g": 1.0,
    "ppt": 0.001, "ng/l": 0.001,
    "ppm": 1000.0, "mg/kg": 1000.0, "ug/g": 1000.0, "µg/g": 1000.0, "mg/l": 1000.0,
    "pci/l": 1.0, "pci/kg": 1.0,
    "bq/kg": 1.0,  # Becquerel/kg (for radionuclides, approximate)
    "mp/kg": 1.0,  # mBq/kg
}


class FDATotalDietStudyFetcher(BaseFetcher):
    """Fetch FDA Total Diet Study data."""

    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        """Locate TDS data files in raw_data/tds/ directory."""
        tds_dir = RAW_DATA_DIR / "tds"
        paths = []

        if tds_dir.exists():
            for f in sorted(tds_dir.iterdir()):
                if f.suffix in ('.csv', '.xlsx', '.xls', '.tsv'):
                    paths.append(f)
                    logger.info("FDA TDS: found %s", f.name)

        # Also check for downloaded files in raw_data/
        for pattern in ["tds_*.xlsx", "tds_*.csv", "tds_*.tsv"]:
            for f in RAW_DATA_DIR.glob(pattern):
                if f.is_file() and f not in paths:
                    paths.append(f)
                    logger.info("FDA TDS: found %s", f.name)

        if not paths:
            logger.warning("FDA TDS: no data files found in data/raw_data/tds/")
            logger.warning("Download TDS data from https://www.fda.gov/food/total-diet-study-center-food-safety-and-applied-nutrition")

        return paths

    def parse(self, files: list[Path]) -> list[dict]:
        """Parse all TDS files."""
        all_rows = []
        for path in files:
            try:
                rows = self._parse_file(path)
                all_rows.extend(rows)
            except Exception as e:
                logger.warning("FDA TDS: failed to parse %s: %s", path.name, e)
        return all_rows

    def _parse_file(self, path: Path) -> list[dict]:
        """Auto-detect format and parse a TDS file."""
        import pandas as pd

        logger.info("FDA TDS: parsing %s", path.name)

        # Extract default year from filename (e.g., "FY2018toFY2020" → 2018)
        default_year = self._extract_year_from_filename(path.name)

        # Detect format
        if path.suffix == '.csv':
            df = pd.read_csv(path, encoding='latin-1')
            return self._parse_sheet(df, path, 'data', default_year)
        elif path.suffix == '.tsv':
            df = pd.read_csv(path, sep='\t', encoding='latin-1')
            return self._parse_sheet(df, path, 'data', default_year)
        elif path.suffix in ('.xlsx', '.xls'):
            try:
                xl = pd.ExcelFile(path, engine='openpyxl')
            except Exception:
                # Some .xlsx files are actually TSV
                try:
                    df = pd.read_csv(path, sep='\t', encoding='latin-1')
                    return self._parse_sheet(df, path, 'data', default_year)
                except:
                    df = pd.read_csv(path, encoding='latin-1')
                    return self._parse_sheet(df, path, 'data', default_year)

            all_rows = []
            for sheet in xl.sheet_names:
                try:
                    df = pd.read_excel(xl, sheet_name=sheet)
                    rows = self._parse_sheet(df, path, sheet, default_year)
                    all_rows.extend(rows)
                except Exception as e:
                    logger.warning("FDA TDS: failed to read sheet '%s': %s", sheet, e)
            return all_rows
        else:
            try:
                df = pd.read_csv(path, sep='\t', encoding='latin-1')
            except:
                df = pd.read_csv(path, encoding='latin-1')
            return self._parse_sheet(df, path, 'data', default_year)

    def _extract_year_from_filename(self, filename: str) -> int | None:
        """Extract year from filename like 'TDS-ReportSupplement-FY2018toFY2020-...'."""
        m = re.search(r'FY(\d{4})', filename)
        if m:
            return int(m.group(1))
        m = re.search(r'(\d{4})', filename)
        if m:
            year = int(m.group(1))
            if 2000 <= year <= 2030:
                return year
        return None

    def _parse_sheet(self, df, path: Path, sheet_name: str, default_year: int = None) -> list[dict]:
        """Parse a single sheet/DataFrame into category_summaries rows."""
        if df.empty:
            return []

        # Clean column names
        df.columns = [str(c).strip().replace('﻿', '').replace('"', '') for c in df.columns]

        # Detect format and find columns
        cols = list(df.columns)

        # Format 1: Standard TDS (fiscal_year, tds_food_name, display_analyte, units, upper_bound)
        food_col = self._find_col(cols, ['tds_food_name', 'tds_food_desc', 'TDSFoodDescription',
                                          'TDS Food Description', 'Food Description'])
        analyte_col = self._find_col(cols, ['display_analyte', 'analyte', 'Analyte',
                                             'Analyte (units)', 'AnalyteName'])
        unit_col = self._find_col(cols, ['units', 'Units', 'unit'])
        value_col = self._find_col(cols, ['upper_bound', 'concentration', 'Concentration',
                                           'Mean Conc.', 'Result', 'Value'])
        year_col = self._find_col(cols, ['fiscal_year', 'FiscalYear', 'Year', 'FY'])
        category_col = self._find_col(cols, ['tds_food_category', 'TDSFoodCategory',
                                              'Food Category', 'tds_overarching_category'])
        detect_col = self._find_col(cols, ['Number of Detects', 'trace', 'Trace'])
        total_col = self._find_col(cols, ['Number of Samples', 'total_samples'])
        lod_col = self._find_col(cols, ['reporting_limit', 'ReportingLimit', 'Reporting Limit', 'MDC', 'LOQ'])

        if not food_col or not analyte_col:
            logger.warning("FDA TDS: missing required columns in %s/%s. Found: %s",
                           path.name, sheet_name, cols[:10])
            return []

        rows = []
        for _, row in df.iterrows():
            food_name = str(row.get(food_col, '')).strip().strip('"')
            analyte_raw = str(row.get(analyte_col, '')).strip()

            if not food_name or food_name in ('nan', 'None', ''):
                continue
            if not analyte_raw or analyte_raw in ('nan', 'None', ''):
                continue

            # Parse contaminant from analyte name
            contaminant = self._map_analyte(analyte_raw)
            if not contaminant:
                continue  # Skip unknown analytes (calcium, sodium, etc.)

            # Parse unit from analyte string or unit column
            unit = 'ppb'
            if unit_col:
                raw_unit = str(row.get(unit_col, '')).strip().lower()
                if raw_unit in UNIT_TO_PPB:
                    unit = raw_unit

            # Also try to extract unit from analyte string like "Lead, Pb (ppb)"
            unit_match = re.search(r'\((\w+)\)', analyte_raw)
            if unit_match:
                extracted_unit = unit_match.group(1).lower()
                if extracted_unit in UNIT_TO_PPB:
                    unit = extracted_unit

            # Get measurement value
            measured_ppb = None
            below_detection = False
            if value_col:
                raw_value = row.get(value_col)
                if raw_value is not None:
                    raw_str = str(raw_value).strip()
                    if raw_str in ('nan', 'None', '', 'ND', 'nd', '< LOD', '<LOD', 'N/A'):
                        below_detection = True
                        measured_ppb = 0.0
                    else:
                        try:
                            value = float(raw_str)
                            measured_ppb = value * UNIT_TO_PPB.get(unit, 1.0)
                        except (ValueError, TypeError):
                            below_detection = True
                            measured_ppb = 0.0

            # Get detection info
            samples_total = 1
            samples_detected = 0 if below_detection else 1
            if total_col:
                try:
                    samples_total = int(float(str(row.get(total_col, 1))))
                except:
                    pass
            if detect_col:
                try:
                    samples_detected = int(float(str(row.get(detect_col, 1))))
                except:
                    pass

            if measured_ppb is None or measured_ppb <= 0:
                if samples_detected > 0:
                    measured_ppb = 0.01  # Below detection but detected
                else:
                    continue

            detection_rate = samples_detected / samples_total if samples_total > 0 else 0

            # Get data year — try column first, then default from filename
            data_year = None
            if year_col:
                try:
                    raw_year = row.get(year_col)
                    if raw_year is not None and str(raw_year) not in ('nan', 'None', ''):
                        data_year = int(float(str(raw_year)))
                except:
                    pass
            if data_year is None:
                data_year = default_year

            # Map food to category
            food_category = normalize_category(food_name.lower())
            if not food_category:
                food_category = normalize_category(food_name)
            if not food_category:
                food_category = 'unknown'

            # Include sheet_name and row index in dedup_key to avoid collisions
            # when data_year is None
            dedup = build_dedup_key(SOURCE_NAME, food_category, contaminant,
                                    data_year or 'none', sheet_name, len(rows))
            rows.append({
                "tier": 2,
                "source_name": SOURCE_NAME,
                "source_url": "https://www.fda.gov/food/total-diet-study-center-food-safety-and-applied-nutrition",
                "report_label": f"FDA TDS - {path.stem} - {sheet_name}",
                "published_date": f"{data_year or 2018}-01-01",
                "data_year": data_year,
                "food_category": food_category,
                "raw_category": food_name,
                "contaminant": contaminant,
                "samples_total": samples_total,
                "samples_detected": samples_detected,
                "detection_rate": round(detection_rate, 4),
                "avg_ppb": round(measured_ppb, 2),
                "max_ppb": round(measured_ppb, 2),
                "original_unit": unit,
                "unit_conversion": UNIT_TO_PPB.get(unit, 1.0),
                "methodology_note": f"FDA Total Diet Study. Analyte: {analyte_raw}",
                "confidence": "high",
                "dedup_key": dedup,
            })

        logger.info("FDA TDS: parsed %d rows from %s/%s", len(rows), path.name, sheet_name)
        return rows

    def _map_analyte(self, analyte: str) -> str | None:
        """Map analyte name to canonical contaminant key."""
        lower = analyte.lower().strip()

        # Direct match
        if lower in ANALYTE_MAP:
            return ANALYTE_MAP[lower]

        # Extract name before parentheses: "Lead, Pb (ppb)" → "lead"
        base = re.split(r'[\(,]', lower)[0].strip()
        if base in ANALYTE_MAP:
            return ANALYTE_MAP[base]

        # Exact word match (not substring) to avoid "potassium" matching "as"
        for key, val in ANALYTE_MAP.items():
            if len(key) >= 4:  # Only match longer keys
                # Check if key appears as a whole word
                if re.search(r'\b' + re.escape(key) + r'\b', lower):
                    return val

        return None

    @staticmethod
    def _find_col(columns: list[str], candidates: list[str]) -> str | None:
        """Find a column by trying multiple candidate names."""
        for c in candidates:
            if c in columns:
                return c
            for col in columns:
                if col.lower() == c.lower():
                    return col
        for c in candidates:
            if len(c) >= 5:
                for col in columns:
                    if c.lower() in col.lower():
                        return col
        return None
