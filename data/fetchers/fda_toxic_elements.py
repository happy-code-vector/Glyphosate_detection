"""
fetchers/fda_toxic_elements.py

FDA Toxic Elements in Food — product-level heavy metal measurements.

Sources:
  1. FDA Closer to Zero program: lead, arsenic, cadmium, mercury in baby food
     https://www.fda.gov/food/metals-and-your-food/closer-zero-reducing-childhood-exposure-contaminants-foods
  2. FDA Total Diet Study (TDS): broad food category coverage for heavy metals
     https://www.fda.gov/food/total-diet-study-tds
  3. FDA Toxic Elements in Food and Foodware program

Content:
  Product-level (Tier 1) heavy metal measurements for:
  - lead, inorganic_arsenic, cadmium, mercury
  - In baby food, general food, and specific products

Strategy:
  1. Download data files from FDA (Excel/CSV).
  2. Parse product names and measurement values.
  3. Handle unit conversions (µg/g=ppm=1000ppb, µg/kg=ppb, ng/g=ppb).
  4. Map to canonical contaminant names matching _HEAVY_METALS frozenset.
  5. Insert into product_tests table.
"""

import logging
from pathlib import Path

from fetchers.base import BaseFetcher, RAW_DATA_DIR, SESSION
from db.database import normalize_category, build_dedup_key, get_connection

logger = logging.getLogger(__name__)

SOURCE_NAME = "FDA_ToxicElements"

# FDA Closer to Zero data sources
# These URLs may change as FDA updates their data — check periodically
FDA_SOURCES = [
    {
        "name": "FDA Toxic Elements - Baby Food (As, Pb, Cd, Hg)",
        "url": "https://www.fda.gov/media/164682/download?attachment",
        "filename": "fda_toxic_elements_baby_food.xlsx",
        "contaminant": None,  # Multi-contaminant file — detected from sheet name
        "format": "xlsx",
        "data_year": 2024,
        "published_date": "2024-01-01",
        "header_row": 1,  # Row 0 is title, row 1 is headers
    },
    {
        "name": "FDA Closer to Zero - Lead FY2023",
        "url": "https://www.fda.gov/media/184798/download?attachment",
        "filename": "fda_closer_to_zero_lead_fy2023.xlsx",
        "contaminant": "lead",
        "format": "xlsx",
        "data_year": 2023,
        "published_date": "2023-01-01",
        "header_row": 3,  # Row 0-2 are title/description, Row 3 is headers
    },
    {
        "name": "FDA Cadmium and Lead in Infant Food",
        "url": "https://www.fda.gov/media/100386/download",
        "filename": "fda_infant_food_cadmium_lead.xlsx",
        "contaminant": None,  # Multi-contaminant
        "format": "xlsx",
        "data_year": 2021,
        "published_date": "2021-01-01",
        "header_row": 2,  # Row 0=title, Row 1=empty, Row 2=headers
    },
    {
        "name": "FDA Arsenic, Cadmium, Lead in Carrageenan",
        "url": "https://www.fda.gov/media/100391/download",
        "filename": "fda_carrageenan_metals.xlsx",
        "contaminant": None,  # Multi-contaminant
        "format": "xlsx",
        "data_year": 2021,
        "published_date": "2021-01-01",
        "header_row": 2,  # Row 0=title, Row 1=empty, Row 2=headers
    },
]

# Canonical contaminant names matching _HEAVY_METALS frozenset
CONTAMINANT_MAP = {
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
}

# Unit conversion factors to ppb
UNIT_TO_PPB = {
    "ppb": 1.0,
    "ug/kg": 1.0,
    "µg/kg": 1.0,
    "ng/g": 1.0,
    "ppm": 1000.0,
    "mg/kg": 1000.0,
    "ug/g": 1000.0,
    "µg/g": 1000.0,
    "mg/L": 1000.0,
}


class FDAToxicElementsFetcher(BaseFetcher):
    """Fetch FDA heavy metal testing data for food products."""

    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        """Download FDA toxic elements data files.

        Strategy:
        1. Check for local files first (manual download — most reliable)
        2. Try FDA download URLs
        """
        # Check for local files first
        local_patterns = ["fda_closer_to_zero_*", "fda_toxic_*", "fda_tds_*"]
        local_files = set()
        for pattern in local_patterns:
            for f in RAW_DATA_DIR.glob(pattern):
                if f.suffix in ('.xlsx', '.xls', '.csv'):
                    local_files.add(f.name)

        paths = []
        for source in FDA_SOURCES:
            dest = RAW_DATA_DIR / source["filename"]

            # Check if file already exists (local or cached)
            if dest.exists():
                logger.info("FDA ToxicElements cache hit: %s", dest.name)
                paths.append(dest)
                continue

            # Check if a local file with this name exists
            if source["filename"] in local_files:
                logger.info("FDA ToxicElements: using local file %s", source["filename"])
                paths.append(dest)
                continue

            # Try downloading
            try:
                logger.info("FDA ToxicElements: fetching %s...", source["name"])
                resp = SESSION.get(source["url"], timeout=120)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    # Verify it's an Excel file (PK zip signature) not HTML
                    if resp.content[:2] == b'PK':
                        dest.write_bytes(resp.content)
                        paths.append(dest)
                        logger.info("FDA ToxicElements: downloaded %s (%d bytes)",
                                    dest.name, len(resp.content))
                    else:
                        logger.warning("FDA ToxicElements: %s returned non-Excel content (%d bytes)",
                                       source["name"], len(resp.content))
                else:
                    logger.warning("FDA ToxicElements: %s status %d (%d bytes)",
                                   source["name"], resp.status_code, len(resp.content))
            except Exception as e:
                logger.warning("FDA ToxicElements: %s failed: %s", source["name"], e)

        # Also check for any local data files
        for f in RAW_DATA_DIR.glob("fda_toxic*"):
            if f.suffix in ('.xlsx', '.xls', '.csv') and f not in paths:
                paths.append(f)
                logger.info("FDA ToxicElements: found local file %s", f.name)

        for f in RAW_DATA_DIR.glob("fda_closer*"):
            if f.suffix in ('.xlsx', '.xls', '.csv') and f not in paths:
                paths.append(f)
                logger.info("FDA ToxicElements: found local file %s", f.name)

        return paths

    def parse(self, files: list[Path]) -> list[dict]:
        """Parse FDA toxic elements data files into product_tests rows."""
        # Build lookup from filename to source config
        source_by_file = {s["filename"]: s for s in FDA_SOURCES}

        all_rows = []
        for path in files:
            source_config = source_by_file.get(path.name, {})
            rows = self._parse_file(path, source_config)
            all_rows.extend(rows)
        return all_rows

    def _parse_file(self, path: Path, source_config: dict = None) -> list[dict]:
        """Parse a single FDA toxic elements data file.

        Handles:
        - Multi-sheet Excel files (one sheet per contaminant)
        - Header row offset (row 0 is title, row 1 is headers)
        - '<LOD' and 'NDb' values (below detection → skip or mark)
        """
        import pandas as pd

        source_config = source_config or {}
        header_row = source_config.get("header_row", 0)
        file_contaminant = source_config.get("contaminant") or self._detect_contaminant(path.name)

        logger.info("FDA ToxicElements: parsing %s (header_row=%d, contaminant=%s)",
                    path.name, header_row, file_contaminant)

        try:
            if path.suffix in ('.xlsx', '.xls'):
                xl = pd.ExcelFile(path, engine='openpyxl')
                sheets = xl.sheet_names
            else:
                sheets = ['Sheet1']
                xl = None
        except Exception as e:
            logger.warning("FDA ToxicElements: failed to read %s: %s", path.name, e)
            return []

        all_rows = []
        for sheet in sheets:
            try:
                if xl:
                    df = pd.read_excel(xl, sheet_name=sheet, header=header_row)
                else:
                    df = pd.read_csv(path, encoding='latin-1', header=header_row)
            except Exception as e:
                logger.warning("FDA ToxicElements: failed to read sheet '%s': %s", sheet, e)
                continue

            if df.empty:
                continue

            # Clean column names
            df.columns = [str(c).strip() for c in df.columns]

            # Detect contaminant from sheet name if multi-contaminant
            sheet_contaminant = self._detect_contaminant(sheet)
            contaminant = file_contaminant or sheet_contaminant or 'lead'

            rows = self._parse_sheet(df, path, sheet, contaminant, source_config)
            all_rows.extend(rows)

        logger.info("FDA ToxicElements: parsed %d rows from %s", len(all_rows), path.name)
        return all_rows

    def _parse_sheet(self, df, path: Path, sheet_name: str, contaminant: str,
                     source_config: dict) -> list[dict]:
        """Parse a single sheet into product_tests rows.

        Handles two formats:
        1. Single value column (e.g., "As Concentration (ppb)")
        2. Multi-column (e.g., "Cadmium (ppb)", "Lead (ppb)" as separate columns)
        """
        # Find key columns — order matters: more specific first
        product_col = self._find_col(df, ['Sample Description', 'Baby Food Name',
                                           'Product Name', 'product_name', 'Food Product'])
        category_col = self._find_col(df, ['Product Category', 'Baby Food Category',
                                            'Food Category', 'Food Type'])
        year_col = self._find_col(df, ['Fiscal Year', 'Year', 'FY', 'data_year'])

        if not product_col:
            logger.warning("FDA ToxicElements: no product column in sheet '%s'. Columns: %s",
                           sheet_name, list(df.columns)[:8])
            return []

        # Detect value columns — either single or multi-column format
        value_col = self._find_col(df, ['Concentration', 'Result', 'Level', 'Value',
                                         'Mean', 'Average', 'As Concentration',
                                         'Lead Concentration', 'Cd Concentration',
                                         'Hg Concentration'])

        # Multi-column detection: find all columns that contain contaminant names + "(ppb)"
        contaminant_cols = {}
        for col in df.columns:
            col_lower = col.lower()
            if 'ppb' in col_lower:
                # Try to detect which contaminant this column represents
                detected = self._detect_contaminant(col)
                if detected:
                    contaminant_cols[col] = detected
                elif 'total arsenic' in col_lower or ('arsenic' in col_lower and 'inorganic' not in col_lower):
                    contaminant_cols[col] = 'inorganic_arsenic'
                elif 'lead' in col_lower:
                    contaminant_cols[col] = 'lead'
                elif 'cadmium' in col_lower:
                    contaminant_cols[col] = 'cadmium'
                elif 'mercury' in col_lower:
                    contaminant_cols[col] = 'mercury'

        if not value_col and not contaminant_cols:
            # Try any column with 'ppb' in the name
            for col in df.columns:
                if 'ppb' in col.lower():
                    value_col = col
                    break

        if not value_col and not contaminant_cols:
            logger.warning("FDA ToxicElements: no value column in sheet '%s'. Columns: %s",
                           sheet_name, list(df.columns)[:8])
            return []

        rows = []
        for _, row in df.iterrows():
            product_name = str(row.get(product_col, '')).strip()
            if not product_name or product_name in ('nan', 'None', ''):
                continue

            # Get food category
            food_category = None
            if category_col:
                raw_cat = str(row.get(category_col, '')).strip()
                if raw_cat and raw_cat not in ('nan', 'None'):
                    food_category = normalize_category(raw_cat)
            if not food_category:
                food_category = normalize_category(product_name)
            if not food_category:
                food_category = 'baby_food'

            # Get data year
            data_year = source_config.get("data_year")
            if year_col:
                raw_year = row.get(year_col)
                if raw_year is not None:
                    try:
                        data_year = int(float(str(raw_year)))
                    except (ValueError, TypeError):
                        pass

            # Parse values — multi-column or single column
            if contaminant_cols:
                # Multi-column format: one column per contaminant
                for col, contam in contaminant_cols.items():
                    raw_value = str(row.get(col, '')).strip()
                    below_detection, measured_ppb = self._parse_value(raw_value)
                    if below_detection or (measured_ppb and measured_ppb > 0):
                        dedup = build_dedup_key(SOURCE_NAME, product_name, contam, food_category, data_year)
                        rows.append(self._build_row(
                            product_name, contam, measured_ppb, below_detection,
                            food_category, data_year, source_config,
                            f"FDA Toxic Elements - {path.stem} - {sheet_name}",
                            dedup
                        ))
            elif value_col:
                # Single column format
                raw_value = str(row.get(value_col, '')).strip()
                below_detection, measured_ppb = self._parse_value(raw_value)
                if below_detection or (measured_ppb and measured_ppb > 0):
                    dedup = build_dedup_key(SOURCE_NAME, product_name, contaminant, food_category, data_year)
                    rows.append(self._build_row(
                        product_name, contaminant, measured_ppb, below_detection,
                        food_category, data_year, source_config,
                        f"FDA Toxic Elements - {path.stem} - {sheet_name}",
                        dedup
                    ))

        return rows

    def _parse_value(self, raw_value: str) -> tuple:
        """Parse a measurement value, handling '<LOD', 'NDb', 'TR', numeric."""
        if not raw_value or raw_value in ('nan', 'None', ''):
            return False, None

        below_detection = 0
        if '<LOD' in raw_value or 'NDb' in raw_value.lower() or 'not detected' in raw_value.lower():
            below_detection = 1
            return below_detection, 0.0

        # Handle 'TR (value)' — trace detected
        if raw_value.startswith('TR'):
            import re
            m = re.search(r'[\d.]+', raw_value)
            if m:
                return 0, float(m.group())
            return 1, 0.0

        try:
            return below_detection, float(raw_value)
        except ValueError:
            return False, None

    def _build_row(self, product_name, contaminant, measured_ppb, below_detection,
                   food_category, data_year, source_config, report_label, dedup) -> dict:
        """Build a product_tests row dict."""
        return {
            "tier": 1,
            "source_name": SOURCE_NAME,
            "source_url": "https://www.fda.gov/food/environmental-contaminants-food",
            "report_label": report_label,
            "published_date": source_config.get("published_date"),
            "data_year": data_year,
            "food_category": food_category,
            "raw_category": product_name,
            "contaminant": contaminant,
            "product_name": product_name,
            "measured_ppb": round(measured_ppb, 2) if measured_ppb else 0.0,
            "below_detection": below_detection,
            "original_unit": "ppb",
            "unit_conversion": 1.0,
            "is_organic": 0,
            "is_grf_certified": 0,
            "methodology_note": f"FDA Toxic Elements testing",
            "confidence": "high",
            "dedup_key": dedup,
        }

    def _detect_contaminant(self, filename: str) -> str | None:
        """Detect contaminant from filename."""
        fn = filename.lower()
        for key, val in CONTAMINANT_MAP.items():
            if key in fn:
                return val
        return None

    @staticmethod
    def _find_col(df, candidates: list[str]) -> str | None:
        """Find a column by trying multiple candidate names.

        Exact match first, then partial match (only for candidates >= 5 chars
        to avoid 'Product' matching 'Product Category').
        """
        for c in candidates:
            if c in df.columns:
                return c
            for col in df.columns:
                if col.lower() == c.lower():
                    return col
        # Partial match — only for longer candidates to avoid false matches
        for c in candidates:
            if len(c) >= 5:
                for col in df.columns:
                    if c.lower() in col.lower():
                        return col
        return None
