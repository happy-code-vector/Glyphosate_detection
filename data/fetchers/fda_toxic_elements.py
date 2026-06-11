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

from fetchers.base import BaseFetcher, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key, get_connection

logger = logging.getLogger(__name__)

SOURCE_NAME = "FDA_ToxicElements"

# FDA Closer to Zero data sources
# These URLs may change as FDA updates their data — check periodically
FDA_SOURCES = [
    {
        "name": "Closer to Zero - Baby Food Lead",
        "url": "https://www.fda.gov/media/156498/download",
        "filename": "fda_closer_to_zero_lead.xlsx",
        "contaminant": "lead",
        "format": "xlsx",
    },
    {
        "name": "Closer to Zero - Baby Food Arsenic",
        "url": "https://www.fda.gov/media/156502/download",
        "filename": "fda_closer_to_zero_arsenic.xlsx",
        "contaminant": "inorganic_arsenic",
        "format": "xlsx",
    },
    {
        "name": "Closer to Zero - Baby Food Cadmium",
        "url": "https://www.fda.gov/media/156504/download",
        "filename": "fda_closer_to_zero_cadmium.xlsx",
        "contaminant": "cadmium",
        "format": "xlsx",
    },
    {
        "name": "Closer to Zero - Baby Food Mercury",
        "url": "https://www.fda.gov/media/156506/download",
        "filename": "fda_closer_to_zero_mercury.xlsx",
        "contaminant": "mercury",
        "format": "xlsx",
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
        """Download FDA toxic elements data files."""
        paths = []
        for source in FDA_SOURCES:
            dest = RAW_DATA_DIR / source["filename"]
            if dest.exists():
                logger.info("FDA ToxicElements cache hit: %s", dest.name)
                paths.append(dest)
                continue

            try:
                logger.info("FDA ToxicElements: fetching %s...", source["name"])
                resp = self.SESSION.get(source["url"], timeout=120)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    dest.write_bytes(resp.content)
                    paths.append(dest)
                    logger.info("FDA ToxicElements: downloaded %s (%d bytes)",
                                dest.name, len(resp.content))
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
        all_rows = []
        for path in files:
            rows = self._parse_file(path)
            all_rows.extend(rows)
        return all_rows

    def _parse_file(self, path: Path) -> list[dict]:
        """Parse a single FDA toxic elements data file."""
        import pandas as pd

        logger.info("FDA ToxicElements: parsing %s", path.name)

        # Determine contaminant from filename
        contaminant = self._detect_contaminant(path.name)

        try:
            if path.suffix in ('.xlsx', '.xls'):
                df = pd.read_excel(path, engine='openpyxl')
            else:
                df = pd.read_csv(path, encoding='latin-1')
        except Exception as e:
            logger.warning("FDA ToxicElements: failed to read %s: %s", path.name, e)
            return []

        if df.empty:
            return []

        # Clean column names
        df.columns = [str(c).strip() for c in df.columns]
        logger.info("FDA ToxicElements: columns = %s", list(df.columns))

        # Find key columns
        product_col = self._find_col(df, ['Product', 'Product Name', 'product_name',
                                           'Food', 'Food Product', 'Sample Description'])
        brand_col = self._find_col(df, ['Brand', 'Brand Name', 'brand', 'Manufacturer'])
        value_col = self._find_col(df, ['Result', 'Concentration', 'Level', 'Value',
                                         'Mean', 'Average', 'Lead', 'Arsenic', 'Cadmium', 'Mercury'])
        unit_col = self._find_col(df, ['Unit', 'Units', 'unit', 'Units (ppb)', 'Units (ppm)'])
        category_col = self._find_col(df, ['Category', 'Food Category', 'Food Type', 'Type'])

        if not product_col:
            logger.warning("FDA ToxicElements: no product column found in %s", path.name)
            logger.warning("Available columns: %s", list(df.columns))
            return []

        rows = []
        for _, row in df.iterrows():
            product_name = str(row.get(product_col, '')).strip()
            if not product_name or product_name in ('nan', 'None', ''):
                continue

            # Get measurement value
            measured_ppb = None
            if value_col:
                raw_value = row.get(value_col)
                if raw_value is not None:
                    try:
                        value = float(raw_value)
                        # Determine unit
                        unit = 'ppb'  # default
                        if unit_col:
                            raw_unit = str(row.get(unit_col, '')).strip().lower()
                            if raw_unit in UNIT_TO_PPB:
                                unit = raw_unit
                        # Convert to ppb
                        measured_ppb = value * UNIT_TO_PPB.get(unit, 1.0)
                    except (ValueError, TypeError):
                        pass

            if measured_ppb is None or measured_ppb <= 0:
                continue

            # Get brand
            brand = ''
            if brand_col:
                brand = str(row.get(brand_col, '')).strip()
                if brand in ('nan', 'None'):
                    brand = ''

            # Get food category
            food_category = None
            if category_col:
                raw_cat = str(row.get(category_col, '')).strip()
                if raw_cat and raw_cat not in ('nan', 'None'):
                    food_category = normalize_category(raw_cat)

            if not food_category:
                food_category = normalize_category(product_name)

            if not food_category:
                food_category = 'unknown'

            # Determine contaminant for this row
            row_contaminant = contaminant
            if not row_contaminant:
                # Try to detect from value column name
                if value_col:
                    col_lower = value_col.lower()
                    for key, val in CONTAMINANT_MAP.items():
                        if key in col_lower:
                            row_contaminant = val
                            break
                if not row_contaminant:
                    row_contaminant = 'lead'  # default

            dedup = build_dedup_key(SOURCE_NAME, product_name, row_contaminant, food_category)
            rows.append({
                "tier": 1,
                "source_name": SOURCE_NAME,
                "source_url": "https://www.fda.gov/food/metals-and-your-food",
                "report_label": f"FDA Toxic Elements - {path.stem}",
                "published_date": None,
                "data_year": None,
                "food_category": food_category,
                "raw_category": product_name,
                "contaminant": row_contaminant,
                "product_name": product_name,
                "measured_ppb": round(measured_ppb, 2),
                "below_detection": 0,
                "original_unit": "ppb",
                "unit_conversion": 1.0,
                "is_organic": 0,
                "is_grf_certified": 0,
                "methodology_note": f"FDA Toxic Elements testing. Brand: {brand}" if brand else "FDA Toxic Elements testing.",
                "confidence": "high",
                "dedup_key": dedup,
            })

        logger.info("FDA ToxicElements: parsed %d rows from %s", len(rows), path.name)
        return rows

    def _detect_contaminant(self, filename: str) -> str | None:
        """Detect contaminant from filename."""
        fn = filename.lower()
        for key, val in CONTAMINANT_MAP.items():
            if key in fn:
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
