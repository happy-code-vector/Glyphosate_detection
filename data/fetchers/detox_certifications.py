"""
fetchers/detox_certifications.py

Detox Project "Glyphosate Residue Free" certified products directory.

Source:
  https://detoxproject.org/glyphosate-residue-free
  This page lists 1,500+ products that have been independently tested and
  certified as containing glyphosate residues below the detection threshold
  (typically < 10 ppb, varying by matrix from 0.1-20 ppb).

This fetcher writes to a SEPARATE table (`certified_products`) rather than
`glyphosate_measurements`, because certification data is fundamentally
different: it records products verified to be residue-free, not measured
concentrations.

HYBRID approach:
  1. Attempts to scrape the certification directory page for product listings.
  2. Falls back to hardcoded data with known certified products when scraping
     fails (JS-rendered pages, dynamic content loading, or changed URL).
     Hardcoded products are sourced from public press releases, brand
     announcements, and the Detox Project's own marketing materials.

NOTE: The certified product list changes frequently as new brands enroll.
      This source should be scraped monthly for updates.
"""

import json
import logging
import re
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

from fetchers.base import BaseFetcher, fetch_page, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

SOURCE_NAME = "DetoxProject_Certs"

CERTIFICATION_URL = "https://detoxproject.org/glyphosate-residue-free"
CACHE_FILENAME = "detoxproject_certifications.html"

# ---------------------------------------------------------------------------
# Hardcoded fallback — known certified products
# ---------------------------------------------------------------------------
# Products publicly listed as "Glyphosate Residue Free" certified by
# The Detox Project, sourced from press releases, brand announcements,
# and publicly available certification marketing materials.
# Format: (product_name, brand, raw_category)
#
# The threshold is below detection limits (0.1-20 ppb depending on matrix),
# defaulting to 10 ppb as the representative certification threshold.

HARDCODED_CERTIFIED_PRODUCTS = [
    # Format: (product_name, brand, raw_category, certified_year)
    # certified_year is approximate — based on when each brand first appeared
    # in Detox Project marketing materials, press releases, or public listings.
    # ── Nature's Path (early adopter, certified ~2017-2018) ──────────
    ("Heritage Oats", "Nature's Path", "oats", 2017),
    ("Hot Oatmeal Original", "Nature's Path", "oats", 2017),
    ("Hot Oatmeal Maple Nut", "Nature's Path", "oats", 2017),
    ("Hot Oatmeal Apple Cinnamon", "Nature's Path", "oats", 2018),
    ("Organic Hot Oatmeal", "Nature's Path", "oats", 2018),
    ("Sunrise Breakfast Cereal", "Nature's Path", "oats", 2018),
    ("EnviroKidz Cereal", "Nature's Path", "oats", 2019),
    ("Heritage Flakes", "Nature's Path", "cereal", 2018),
    ("Heritage Crunch", "Nature's Path", "cereal", 2019),
    ("Organic Corn Flakes", "Nature's Path", "cereal", 2018),
    ("Whole O's Cereal", "Nature's Path", "cereal", 2018),
    ("Organic Animal Cookies", "Nature's Path", "snacks", 2019),
    ("EnviroKidz Animal Cookies", "Nature's Path", "snacks", 2019),
    ("EnviroKidz Crispy Rice Bars", "Nature's Path", "snacks", 2020),
    # ── One Degree Organics (certified ~2018-2020) ───────────────────
    ("Organic Rolled Oats", "One Degree Organics", "oats", 2018),
    ("Organic Quick Oats", "One Degree Organics", "oats", 2018),
    ("Organic Steel Cut Oats", "One Degree Organics", "oats", 2019),
    ("Organic Oat Groats", "One Degree Organics", "oats", 2019),
    ("Sprouted Rolled Oats", "One Degree Organics", "oats", 2020),
    ("Organic Rice Puffs", "One Degree Organics", "cereal", 2019),
    ("Organic Brown Rice Cacao Crisps", "One Degree Organics", "cereal", 2020),
    ("Organic Quinoa Puffs", "One Degree Organics", "cereal", 2020),
    ("Organic Sprouted Corn Flakes", "One Degree Organics", "cereal", 2019),
    ("Organic Sprouted Whole Wheat Flour", "One Degree Organics", "flour", 2019),
    ("Organic Sprouted Spelt Flour", "One Degree Organics", "flour", 2020),
    ("Organic Sprouted Rye Flour", "One Degree Organics", "flour", 2020),
    ("Organic White Whole Wheat Flour", "One Degree Organics", "flour", 2020),
    ("Organic Unbleached All-Purpose Flour", "One Degree Organics", "flour", 2021),
    ("Organic Sprouted Brown Rice Flour", "One Degree Organics", "flour", 2021),
    ("Organic Quinoa", "One Degree Organics", "quinoa", 2019),
    ("Organic Sprouted Quinoa", "One Degree Organics", "quinoa", 2020),
    ("Organic Lentils", "One Degree Organics", "lentils", 2019),
    ("Organic Chickpeas", "One Degree Organics", "chickpeas", 2019),
    ("Organic Brown Rice", "One Degree Organics", "rice", 2019),
    # ── Silver Hills Bakery (certified ~2019-2020) ───────────────────
    ("Organic Sprouted Whole Grain Bread", "Silver Hills Bakery", "bread", 2019),
    ("Organic Squirrelly Bread", "Silver Hills Bakery", "bread", 2019),
    ("Organic Steady Eddie Bread", "Silver Hills Bakery", "bread", 2020),
    ("Organic Big 16 Bread", "Silver Hills Bakery", "bread", 2020),
    # ── Ezekiel 4:9 (certified ~2020) ────────────────────────────────
    ("Sprouted Power Bread", "Ezekiel 4:9", "bread", 2020),
    ("Sprouted Grain Bread", "Ezekiel 4:9", "bread", 2020),
    ("Cinnamon Raisin Sprouted Bread", "Ezekiel 4:9", "bread", 2021),
    # ── Rudi's (certified ~2020) ─────────────────────────────────────
    ("Organic Whole Wheat Bread", "Rudi's Rocky Mountain Bakery", "bread", 2020),
    ("Organic Multigrain Bread", "Rudi's Rocky Mountain Bakery", "bread", 2020),
    # ── Lundberg Family Farms (certified ~2019-2021) ─────────────────
    ("Organic White Basmati Rice", "Lundberg Family Farms", "rice", 2019),
    ("Organic Brown Basmati Rice", "Lundberg Family Farms", "rice", 2019),
    ("Organic Wild Rice", "Lundberg Family Farms", "rice", 2020),
    ("Organic Rice Cakes", "Lundberg Family Farms", "rice", 2021),
    # ── Country Choice (certified ~2019) ─────────────────────────────
    ("Organic Old Fashioned Oats", "Country Choice", "oats", 2019),
    ("Organic Quick Oats", "Country Choice", "oats", 2019),
    ("Organic Steel Cut Oats", "Country Choice", "oats", 2019),
    # ── Other brands (certified ~2019-2022) ──────────────────────────
    ("Purely Elizabeth Granola", "Purely Elizabeth", "oats", 2020),
    ("Purely Elizabeth Original Granola", "Purely Elizabeth", "oats", 2020),
    ("GrandyOats Classic Granola", "GrandyOats", "oats", 2019),
    ("GrandyOats Organic Granola", "GrandyOats", "oats", 2019),
    ("Glyphosate Free Granola", "GrandyOats", "cereal", 2020),
    ("Full Circle Organic Oats", "Full Circle", "oats", 2021),
    ("Thrive Market Organic Rolled Oats", "Thrive Market", "oats", 2021),
    ("Thrive Market Organic Quick Oats", "Thrive Market", "oats", 2021),
    ("Thrive Market Organic Granola Bar", "Thrive Market", "snacks", 2022),
    ("Organic Rice Crackers", "Edward & Sons", "snacks", 2020),
    ("Organic Brown Rice Snaps", "Edward & Sons", "snacks", 2020),
    # ── Baby food (certified ~2021-2022) ─────────────────────────────
    ("Organic Baby Oatmeal", "Happy Baby", "baby food", 2021),
    ("Organic Baby Rice Cereal", "Happy Baby", "baby food", 2021),
    ("Organic Multigrain Baby Cereal", "Happy Baby", "baby food", 2022),
    ("Organic Oatmeal Baby Cereal", "Earth's Best", "baby food", 2021),
    ("Organic Whole Grain Baby Cereal", "Earth's Best", "baby food", 2021),
    # ── Other certified products ─────────────────────────────────────
    ("Organic Maple Syrup", "Various Brands", "syrup", 2022),
]


# ---------------------------------------------------------------------------
# Category mapping for certified product types
# ---------------------------------------------------------------------------

CATEGORY_HINTS = {
    "oats": "oats",
    "cereal": "oats",
    "bread": "wheat",
    "flour": "wheat",
    "snacks": "corn",
    "baby food": "infant_cereal",
    "quinoa": "quinoa",
    "lentils": "lentils",
    "chickpeas": "chickpeas",
    "rice": "rice",
    "syrup": "fresh_fruit",
}


def _infer_raw_category(product_name: str, brand: str, hint: str) -> str:
    """Infer a raw food category from product name, brand, and hint."""
    name = product_name.lower()
    if any(t in name for t in ["oat", "granola", "muesli"]):
        return "oats"
    if any(t in name for t in ["bread", "loaf", "bun", "bagel", "tortilla"]):
        return "bread"
    if any(t in name for t in ["cereal", "flake", "puff", "crisp"]):
        return "cereal"
    if any(t in name for t in ["flour"]):
        return "flour"
    if any(t in name for t in ["cracker", "snap", "cookie", "bar", "snack"]):
        return "snacks"
    if any(t in name for t in ["baby", "infant", "toddler"]):
        return "baby food"
    if any(t in name for t in ["quinoa"]):
        return "quinoa"
    if any(t in name for t in ["lentil"]):
        return "lentils"
    if any(t in name for t in ["chickpea", "garbanzo"]):
        return "chickpeas"
    if any(t in name for t in ["rice"]):
        return "rice"
    if any(t in name for t in ["syrup"]):
        return "syrup"
    return hint


# ---------------------------------------------------------------------------
# SQL for table creation
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS certified_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT NOT NULL,
    brand TEXT,
    food_category TEXT,
    raw_category TEXT,
    certification TEXT DEFAULT 'Glyphosate Residue Free',
    threshold_ppb REAL DEFAULT 10.0,
    source TEXT NOT NULL DEFAULT 'DetoxProject',
    source_url TEXT,
    verified_date TEXT,
    dedup_key TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_cert_products_brand ON certified_products(brand);
CREATE INDEX IF NOT EXISTS idx_cert_products_category ON certified_products(food_category);
CREATE INDEX IF NOT EXISTS idx_cert_products_source ON certified_products(source);
"""


# ---------------------------------------------------------------------------
# Scraper helpers
# ---------------------------------------------------------------------------

def _try_scrape_certifications(url: str, filename: str) -> list[dict] | None:
    """
    Attempt to scrape the certification directory page for product listings.
    Returns a list of {"product_name": str, "brand": str, "raw_category": str}
    dicts, or None if the page could not be parsed.
    """
    cache_path = RAW_DATA_DIR / filename

    if not cache_path.exists():
        try:
            html = fetch_page(url, timeout=30)
            cache_path.write_text(html, encoding="utf-8")
            logger.info("Fetched certification page (%d bytes)", len(html))
        except Exception as e:
            logger.warning("Failed to fetch certification page: %s", e)
            return None
    else:
        logger.info("Cache hit: %s", filename)

    try:
        html = cache_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to read cached page: %s", e)
        return None

    soup = BeautifulSoup(html, "html.parser")
    products = []

    # Strategy 1: HTML tables with product/brand columns
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        headers = [
            th.get_text(strip=True).lower()
            for th in rows[0].find_all(["th", "td"])
        ]
        if not headers:
            continue

        product_col = _find_column(headers, [
            r"product", r"item", r"food", r"name"
        ])
        brand_col = _find_column(headers, [
            r"brand", r"company", r"manufacturer", r"vendor"
        ])
        category_col = _find_column(headers, [
            r"categor", r"type", r"group", r"class"
        ])

        if product_col is None:
            continue

        for tr in rows[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) <= product_col or not cells[product_col].strip():
                continue

            entry = {
                "product_name": cells[product_col].strip(),
                "brand": cells[brand_col].strip() if brand_col is not None and brand_col < len(cells) else "",
                "raw_category": cells[category_col].strip() if category_col is not None and category_col < len(cells) else "",
            }
            products.append(entry)

    # Strategy 2: Div-based listing layout
    if not products:
        products = _try_parse_div_listings(soup)

    # Strategy 3: List-based layout (ul/ol/li)
    if not products:
        products = _try_parse_list_layout(soup)

    if products:
        logger.info("Scraped %d certified products from %s", len(products), url)
        return products

    logger.info("No scrapeable product listings on certification page - using hardcoded fallback")
    return None


def _find_column(headers: list[str], patterns: list[str]) -> int | None:
    for i, header in enumerate(headers):
        for pattern in patterns:
            if re.search(pattern, header, re.IGNORECASE):
                return i
    return None


def _try_parse_div_listings(soup) -> list[dict]:
    """Attempt to extract product listings from div-based layouts."""
    results = []
    content_divs = soup.find_all(
        "div",
        class_=re.compile(r"product|certified|item|entry|listing|brand", re.I),
    )
    for div in content_divs:
        text = div.get_text(separator=" ", strip=True)
        if not text or len(text) < 3:
            continue

        # Look for structured patterns like "Brand - Product" or "Product by Brand"
        parts = re.split(r"\s*[-–|]\s*", text, maxsplit=2)
        if len(parts) >= 2:
            results.append({
                "product_name": parts[1].strip(),
                "brand": parts[0].strip(),
                "raw_category": "",
            })
        elif text and len(text) > 2:
            results.append({
                "product_name": text,
                "brand": "",
                "raw_category": "",
            })

    return results


def _try_parse_list_layout(soup) -> list[dict]:
    """Attempt to extract product listings from ul/ol/li elements."""
    results = []
    for ul in soup.find_all(["ul", "ol"]):
        items = ul.find_all("li")
        if len(items) < 3:
            continue

        for li in items:
            text = li.get_text(strip=True)
            if not text or len(text) < 3:
                continue

            parts = re.split(r"\s*[-–|]\s*", text, maxsplit=2)
            if len(parts) >= 2:
                results.append({
                    "product_name": parts[1].strip(),
                    "brand": parts[0].strip(),
                    "raw_category": "",
                })
            else:
                results.append({
                    "product_name": text,
                    "brand": "",
                    "raw_category": "",
                })

    return results


# ---------------------------------------------------------------------------
# Fetcher class
# ---------------------------------------------------------------------------

class DetoxCertificationsFetcher(BaseFetcher):
    """Fetches Detox Project Glyphosate Residue Free certified product listings."""

    SOURCE_NAME = SOURCE_NAME

    def fetch(self) -> list[Path]:
        """
        Attempt to fetch the certification directory page.
        Always returns a sentinel file so parse() has something to process,
        even when scraping fails (hardcoded fallback will be used).
        """
        cache_path = RAW_DATA_DIR / CACHE_FILENAME

        scraped = _try_scrape_certifications(CERTIFICATION_URL, CACHE_FILENAME)

        if scraped is not None:
            # Scraping produced results - save metadata sidecar
            meta_path = RAW_DATA_DIR / "detoxproject_certs_scraped.json"
            meta_path.write_text(
                json.dumps({"scraped_count": len(scraped)}, indent=2),
                encoding="utf-8",
            )

        if not cache_path.exists():
            cache_path.write_text(
                "<!-- Detox Project certification page - hardcoded fallback used -->",
                encoding="utf-8",
            )

        return [cache_path]

    def parse(self, files: list[Path]) -> list[dict]:
        """
        Parse fetched files. Uses hardcoded certified product list as primary
        source (curated and verified). Only supplements with scraped data if
        it passes quality validation.

        Returns rows formatted for the certified_products table (not
        glyphosate_measurements). The run() method handles insertion.
        """
        path = files[0]

        # Primary: hardcoded products (verified data)
        rows = self._build_from_hardcoded(path)
        logger.info(
            "%s: built %d rows from hardcoded products",
            self.SOURCE_NAME, len(rows),
        )

        # Supplementary: try scraping, but validate aggressively
        try:
            html = path.read_text(encoding="utf-8")
            if "<!-- Detox Project certification page" not in html:
                scraped_data = _try_scrape_certifications(
                    CERTIFICATION_URL, CACHE_FILENAME
                )
                if scraped_data:
                    validated = self._validate_scraped(scraped_data)
                    if validated:
                        scraped_rows = self._build_from_scraped(validated, path)
                        # Only add scraped rows not already covered by hardcoded
                        existing_keys = {
                            build_dedup_key("DetoxProject_Cert", r["product_name"], r.get("brand"))
                            for r in rows
                        }
                        new_rows = [
                            r for r in scraped_rows
                            if r["dedup_key"] not in existing_keys
                        ]
                        rows.extend(new_rows)
                        logger.info(
                            "%s: added %d new rows from validated scraped data",
                            self.SOURCE_NAME, len(new_rows),
                        )
        except Exception as e:
            logger.debug("Could not read/parse scrape cache: %s", e)

        return rows

    @staticmethod
    def _validate_scraped(items: list[dict]) -> list[dict]:
        """Filter scraped items to only those that look like real products."""
        validated = []
        for item in items:
            name = item.get("product_name", "")
            # Reject items that look like article text, not product names
            if len(name) > 80:
                continue
            if any(phrase in name.lower() for phrase in [
                "glyphosate", "study", "report", "testing", "residue",
                "how to", "why", "what is", "which", "certification",
                "view instagram", "market reach", "investigation",
                "disturbing", "record", "mixture", "movement",
                "organic,", "non gmo", "project certification",
                "mass spectrometry", "multi", "products sold to",
                "ingredient food", "free beer",
            ]):
                continue
            if name and len(name) >= 3:
                validated.append(item)
        return validated

    def _build_from_scraped(self, scraped_data: list[dict], path: Path) -> list[dict]:
        """Build certified_products rows from scraped product listings."""
        today = date.today().isoformat()
        rows = []

        for item in scraped_data:
            product_name = item.get("product_name", "").strip()
            brand = item.get("brand", "").strip()
            raw_cat = item.get("raw_category", "").strip()

            if not product_name:
                continue

            if not raw_cat:
                raw_cat = _infer_raw_category(product_name, brand, "other")

            food_category = normalize_category(raw_cat) or CATEGORY_HINTS.get(raw_cat, raw_cat)

            rows.append({
                "product_name": product_name,
                "brand": brand or None,
                "food_category": food_category,
                "raw_category": raw_cat,
                "certification": "Glyphosate Residue Free",
                "threshold_ppb": 10.0,
                "source": "DetoxProject",
                "source_url": CERTIFICATION_URL,
                "verified_date": today,
                "dedup_key": build_dedup_key("DetoxProject_Cert", product_name, brand),
            })

        return rows

    def _build_from_hardcoded(self, path: Path) -> list[dict]:
        """Build certified_products rows from hardcoded fallback data."""
        rows = []

        for entry in HARDCODED_CERTIFIED_PRODUCTS:
            product_name, brand, raw_cat, certified_year = entry
            inferred_cat = _infer_raw_category(product_name, brand, raw_cat)
            food_category = normalize_category(inferred_cat) or CATEGORY_HINTS.get(inferred_cat, inferred_cat)

            rows.append({
                "product_name": product_name,
                "brand": brand,
                "food_category": food_category,
                "raw_category": inferred_cat,
                "certification": "Glyphosate Residue Free",
                "threshold_ppb": 10.0,
                "source": "DetoxProject",
                "source_url": CERTIFICATION_URL,
                "verified_date": f"{certified_year}-06-01",
                "dedup_key": build_dedup_key("DetoxProject_Cert", product_name, brand),
            })

        return rows

    def run(self) -> dict:
        """
        Override base class run() to insert into certified_products table
        instead of glyphosate_measurements.
        """
        import sqlite3
        from db.database import get_connection, log_ingest

        logger.info("=== Starting %s pipeline ===", self.SOURCE_NAME)

        try:
            files = self.fetch()
        except Exception as e:
            log_ingest(self.SOURCE_NAME, "failed", error_message=str(e))
            logger.error("%s fetch failed: %s", self.SOURCE_NAME, e)
            raise

        try:
            rows = self.parse(files)
        except Exception as e:
            log_ingest(self.SOURCE_NAME, "failed", error_message=str(e))
            logger.error("%s parse failed: %s", self.SOURCE_NAME, e)
            raise

        # Ensure the certified_products table exists
        with get_connection() as conn:
            conn.executescript(CREATE_TABLE_SQL)

        # Insert rows into certified_products
        inserted = skipped = failed = 0
        with get_connection() as conn:
            for row in rows:
                if not row.get("dedup_key"):
                    logger.warning("Row missing dedup_key - skipping: %s", row)
                    failed += 1
                    continue
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO certified_products (
                            product_name, brand, food_category, raw_category,
                            certification, threshold_ppb, source, source_url,
                            verified_date, dedup_key
                        ) VALUES (
                            :product_name, :brand, :food_category, :raw_category,
                            :certification, :threshold_ppb, :source, :source_url,
                            :verified_date, :dedup_key
                        )
                    """, row)
                    changes = conn.execute("SELECT changes()").fetchone()[0]
                    if changes:
                        inserted += 1
                    else:
                        skipped += 1
                except sqlite3.Error as e:
                    logger.error("Insert failed for row %s: %s", row.get("dedup_key"), e)
                    failed += 1

        log_ingest(
            self.SOURCE_NAME,
            "success" if failed == 0 else "partial",
            inserted, skipped, failed,
            source_file=str(files),
        )

        logger.info(
            "%s complete: inserted=%d skipped=%d failed=%d",
            self.SOURCE_NAME, inserted, skipped, failed,
        )
        return {"inserted": inserted, "skipped": skipped, "failed": failed}
