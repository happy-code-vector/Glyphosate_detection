"""
fetchers/efsa_mrls.py

EFSA Pesticide Residues MRL Database — comprehensive EU Maximum Residue Limits
for pesticides in food.

Source:
  European Food Safety Authority (EFSA)
  Pesticide Residues in Food Data
  https://www.efsa.europa.eu/en/data/pest-chem-occur-data

Content:
  EU MRLs (Regulation (EC) No 396/2005) for hundreds of pesticides across
  hundreds of food categories. These are generally the strictest internationally.

Strategy:
  1. Download the EFSA MRL Excel file (updated annually).
  2. Parse pesticide/commodity/MRL columns.
  3. Convert mg/kg (ppm) to ppb (× 1000).
  4. Handle "*" entries (default 0.01 mg/kg = 10 ppb) — these are the strictest limits.
  5. Insert into international_mrls table with country_region="EU", regulatory_body="EFSA".
"""

import logging
from pathlib import Path

from fetchers.base import BaseFetcher, RAW_DATA_DIR, SESSION
from db.database import build_dedup_key, get_connection, normalize_category

logger = logging.getLogger(__name__)

SOURCE_NAME = "EFSA_MRLs"
SOURCE_URL = "https://www.efsa.europa.eu/en/data/pest-chem-occur-data"

# EFSA default MRL for unauthorized pesticides: 0.01 mg/kg = 10 ppb
DEFAULT_MRL_PPM = 0.01
DEFAULT_MRL_PPB = 10.0

# Known EFSA food category → our canonical category mapping
# These will be expanded during the alias audit step
EFSA_CATEGORY_MAP = {
    # Cereals
    "wheat": "wheat",
    "barley": "barley",
    "oat": "oats",
    "oats": "oats",
    "rye": "rye",
    "rice": "rice",
    "corn": "corn",
    "maize": "corn",
    "sorghum": "sorghum",
    "millet": "millet",
    # Fruits
    "apple": "apple",
    "apples": "apple",
    "pear": "pear",
    "pears": "pear",
    "grape": "grape",
    "grapes": "grape",
    "strawberry": "strawberry",
    "strawberries": "strawberry",
    "blueberry": "blueberry",
    "blueberries": "blueberry",
    "cherry": "cherry",
    "cherries": "cherry",
    "peach": "peach",
    "peaches": "peach",
    "orange": "orange",
    "oranges": "orange",
    "lemon": "lemon",
    "lemons": "lemon",
    "banana": "banana",
    "bananas": "banana",
    # Vegetables
    "potato": "potato",
    "potatoes": "potato",
    "tomato": "tomato",
    "tomatoes": "tomato",
    "carrot": "carrot",
    "carrots": "carrot",
    "lettuce": "lettuce",
    "spinach": "spinach",
    "kale": "kale",
    "cucumber": "cucumber",
    "cucumbers": "cucumber",
    "celery": "celery",
    "broccoli": "broccoli",
    "onion": "onion",
    "garlic": "garlic",
    "pepper": "pepper",
    "peppers": "pepper",
    "bean": "bean",
    "beans": "bean",
    "pea": "pea",
    "peas": "pea",
    # Oilseeds
    "soybean": "soybean",
    "soybeans": "soybean",
    "soya": "soybean",
    "rapeseed": "rapeseed",
    "canola": "rapeseed",
    "sunflower": "sunflower",
    "peanut": "peanut",
    "peanuts": "peanut",
    "groundnut": "peanut",
    "almond": "almond",
    "almonds": "almond",
    # Animal products
    "milk": "milk",
    "egg": "egg",
    "eggs": "egg",
    "meat": "meat",
    "poultry": "poultry",
    "fish": "fish",
    # Nuts
    "walnut": "walnut",
    "walnuts": "walnut",
    "hazelnut": "hazelnut",
    "hazelnuts": "hazelnut",
    "cashew": "cashew",
    "cashews": "cashew",
    "pistachio": "pistachio",
    "pistachios": "pistachio",
}


class EFSAMrlFetcher(BaseFetcher):
    """Fetch EU MRLs from EFSA's pesticide residues database."""

    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        """Download EFSA MRL Excel file."""
        # EFSA publishes MRLs as part of their pesticide residues data
        # The MRL reference file is typically at a stable URL
        # If the URL changes, update here
        url = "https://www.efsa.europa.eu/sites/default/files/2024-11/mrl_data.xlsx"

        # Also try the consolidated regulation annex
        alt_urls = [
            "https://www.efsa.europa.eu/sites/default/files/2024-01/mrl-regulation-396-2005-annexes.xlsx",
            "https://www.efsa.europa.eu/sites/default/files/2023-11/mrl_data.xlsx",
        ]

        dest = RAW_DATA_DIR / "efsa_mrls.xlsx"
        if dest.exists():
            logger.info("EFSA MRL cache hit: %s", dest.name)
            return [dest]

        # Try primary URL first, then alternatives
        for url in [url] + alt_urls:
            try:
                logger.info("EFSA MRL: fetching %s...", url)
                resp = SESSION.get(url, timeout=120)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    dest.write_bytes(resp.content)
                    logger.info("EFSA MRL: downloaded %d bytes", len(resp.content))
                    return [dest]
                else:
                    logger.warning("EFSA MRL: status %d (%d bytes)",
                                   resp.status_code, len(resp.content))
            except Exception as e:
                logger.warning("EFSA MRL fetch failed for %s: %s", url, e)

        # If download fails, try to use any existing local file
        local_patterns = ["efsa_mrl*", "mrl_data*", "mrl-regulation*"]
        for pattern in local_patterns:
            for f in RAW_DATA_DIR.glob(pattern):
                if f.suffix in ('.xlsx', '.xls', '.csv'):
                    logger.info("EFSA MRL: using local file %s", f.name)
                    return [f]

        logger.error("EFSA MRL: could not download or find MRL data file")
        return []

    def parse(self, files: list[Path]) -> list[dict]:
        """Parse EFSA MRL Excel file into international_mrls rows."""
        if not files:
            return []

        import pandas as pd

        path = files[0]
        logger.info("EFSA MRL: parsing %s", path.name)

        # Try reading the Excel file — EFSA files may have multiple sheets
        try:
            # First, try to read all sheets to find the MRL data
            xl = pd.ExcelFile(path)
            logger.info("EFSA MRL: sheets = %s", xl.sheet_names)

            # Look for the sheet with MRL data
            df = None
            for sheet_name in xl.sheet_names:
                sheet_lower = sheet_name.lower()
                if any(kw in sheet_lower for kw in ['mrl', 'maximum', 'residue', 'limit', 'annex']):
                    df = pd.read_excel(xl, sheet_name=sheet_name, nrows=5)
                    logger.info("EFSA MRL: trying sheet '%s', columns = %s",
                                sheet_name, list(df.columns))
                    break

            if df is None:
                # Try first sheet
                df = pd.read_excel(xl, sheet_name=0, nrows=5)
                logger.info("EFSA MRL: using first sheet, columns = %s", list(df.columns))

            # Now read the full sheet
            sheet_to_use = sheet_name if df is not None else 0
            df = pd.read_excel(xl, sheet_name=sheet_to_use)
            logger.info("EFSA MRL: read %d rows from sheet '%s'", len(df), sheet_to_use)

        except Exception as e:
            logger.error("EFSA MRL: failed to read Excel: %s", e)
            # Try CSV fallback
            try:
                df = pd.read_csv(path, encoding='latin-1')
                logger.info("EFSA MRL: read %d rows from CSV", len(df))
            except Exception as e2:
                logger.error("EFSA MRL: failed to read CSV: %s", e2)
                return []

        # Identify columns — EFSA uses various column names
        cols = [str(c).strip() for c in df.columns]
        df.columns = cols

        # Find the key columns
        pest_col = self._find_col(df, ['Active substance', 'Pesticide', 'Analyte',
                                        'Substance', 'pesticide', 'active_substance'])
        comm_col = self._find_col(df, ['Commodity', 'Food category', 'Product',
                                        'Food', 'commodity', 'food_category'])
        mrl_col = self._find_col(df, ['MRL (mg/kg)', 'MRL', 'Maximum residue level',
                                       'mrl_ppm', 'mrl', 'MRL mg/kg'])

        if not pest_col or not comm_col or not mrl_col:
            logger.error("EFSA MRL: could not identify columns. Found: pest=%s, comm=%s, mrl=%s",
                         pest_col, comm_col, mrl_col)
            logger.error("Available columns: %s", list(df.columns))
            return []

        logger.info("EFSA MRL: using columns: pesticide=%s, commodity=%s, mrl=%s",
                    pest_col, comm_col, mrl_col)

        # Parse rows
        rows = []
        skipped = 0
        for _, row in df.iterrows():
            pesticide = str(row[pest_col]).strip().lower()
            commodity = str(row[comm_col]).strip()
            mrl_raw = str(row[mrl_col]).strip()

            # Skip empty/header rows
            if not pesticide or pesticide in ('nan', 'none', ''):
                skipped += 1
                continue
            if not commodity or commodity in ('nan', 'none', ''):
                skipped += 1
                continue

            # Parse MRL value
            mrl_ppm = self._parse_mrl(mrl_raw)
            if mrl_ppm is None:
                skipped += 1
                continue

            mrl_ppb = mrl_ppm * 1000.0

            # Map commodity to canonical category
            food_category = self._map_category(commodity.lower())
            if not food_category:
                # Use the raw commodity lowercased as the category
                food_category = commodity.lower().strip()

            dedup = build_dedup_key("EFSA", food_category, pesticide, "EU")
            rows.append({
                "food_category": food_category,
                "raw_commodity": commodity,
                "pesticide": pesticide,
                "country_region": "EU",
                "mrl_ppm": mrl_ppm,
                "mrl_ppb": mrl_ppb,
                "regulatory_body": "EFSA",
                "source_url": SOURCE_URL,
                "dedup_key": dedup,
            })

        logger.info("EFSA MRL: parsed %d MRL entries, skipped %d", len(rows), skipped)
        return rows

    def _parse_mrl(self, raw: str) -> float | None:
        """Parse an MRL value, handling '*' (default) and various formats."""
        if not raw or raw in ('nan', 'None', ''):
            return None

        raw = raw.strip()

        # "*" means default MRL: 0.01 mg/kg = 10 ppb
        if raw == '*':
            return DEFAULT_MRL_PPM

        # Try direct float conversion
        try:
            return float(raw)
        except ValueError:
            pass

        # Try removing common suffixes
        for suffix in [' mg/kg', ' ppm', ' mg/L']:
            if raw.endswith(suffix):
                try:
                    return float(raw[:-len(suffix)])
                except ValueError:
                    pass

        return None

    def _map_category(self, raw: str) -> str | None:
        """Map EFSA commodity name to our canonical category."""
        # Direct lookup
        if raw in EFSA_CATEGORY_MAP:
            return EFSA_CATEGORY_MAP[raw]

        # Try normalize_category from database
        canonical = normalize_category(raw)
        if canonical:
            return canonical

        # Try substring matching against our map
        for key, val in EFSA_CATEGORY_MAP.items():
            if key in raw or raw in key:
                return val

        return None

    @staticmethod
    def _find_col(df, candidates: list[str]) -> str | None:
        """Find a column by trying multiple candidate names."""
        for c in candidates:
            if c in df.columns:
                return c
            # Case-insensitive match
            for col in df.columns:
                if col.lower() == c.lower():
                    return col
        # Partial match
        for c in candidates:
            for col in df.columns:
                if c.lower() in col.lower():
                    return col
        return None
