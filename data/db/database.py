"""
db/database.py
Core database operations. All pipeline code imports from here.
"""

import sqlite3
import hashlib
import logging
import json
from pathlib import Path
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "residueiq.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize():
    """Create all tables. Safe to call on every run — idempotent."""
    with get_connection() as conn:
        conn.executescript(SCHEMA_PATH.read_text())
        _seed_category_aliases(conn)
    logger.info("Database initialized at %s", DB_PATH)


def _seed_category_aliases(conn):
    """
    Load all known aliases into category_aliases table.
    This is the single authoritative mapping — every alias any source
    might produce maps to one canonical key.
    Extend this dict when a new source introduces a new spelling.
    """
    aliases = {
        # ── Oats ──────────────────────────────────────────────────────────
        "oat": "oats", "oats": "oats", "rolled oats": "oats",
        "oat cereal": "oats", "oat-based": "oats", "oat flour": "oats",
        "oat bran": "oats", "oat grain": "oats", "oatmeal": "oats",
        "oat-based products": "oats", "oat based": "oats",
        "oats (avena sativa)": "oats", "whole oats": "oats",
        "quick oats": "oats", "instant oats": "oats",
        # ── Wheat ─────────────────────────────────────────────────────────
        "wheat": "wheat", "wheat grain": "wheat", "wheat flour": "wheat",
        "whole wheat": "wheat", "bread wheat": "wheat", "wheat bran": "wheat",
        "wheat germ": "wheat", "durum wheat": "wheat", "semolina": "wheat",
        "pasta": "wheat", "bread": "wheat", "flour": "wheat",
        "soft wheat": "wheat", "hard wheat": "wheat",
        "triticum aestivum": "wheat",
        # ── Soy ───────────────────────────────────────────────────────────
        "soy": "soybeans", "soya": "soybeans", "soybean": "soybeans",
        "soybeans": "soybeans", "soy-based": "soybeans",
        "soy products": "soybeans", "soy flour": "soybeans",
        "glycine max": "soybeans", "edamame": "soybeans",
        # ── Corn / Maize ───────────────────────────────────────────────────
        "corn": "corn", "maize": "corn", "cornstarch": "corn",
        "corn flour": "corn", "corn grain": "corn", "corn meal": "corn",
        "zea mays": "corn", "hominy": "corn",
        # ── Chickpeas ─────────────────────────────────────────────────────
        "chickpea": "chickpeas", "chickpeas": "chickpeas",
        "garbanzo": "chickpeas", "garbanzo bean": "chickpeas",
        "hummus": "chickpeas", "chickpea products": "chickpeas",
        "cicer arietinum": "chickpeas",
        # ── Lentils ────────────────────────────────────────────────────────
        "lentil": "lentils", "lentils": "lentils",
        "dried lentils": "lentils", "lens culinaris": "lentils",
        "red lentils": "lentils", "green lentils": "lentils",
        # ── Beans ─────────────────────────────────────────────────────────
        "bean": "beans", "beans": "beans", "pinto bean": "beans",
        "kidney bean": "beans", "black bean": "beans",
        "navy bean": "beans", "dried beans": "beans",
        "pulse products": "beans",
        # ── Peas ──────────────────────────────────────────────────────────
        "pea": "peas", "peas": "peas", "dried peas": "peas",
        "split peas": "peas", "pisum sativum": "peas",
        "field peas": "peas",
        # ── Barley ────────────────────────────────────────────────────────
        "barley": "barley", "barley grain": "barley",
        "barley flour": "barley", "malted barley": "barley",
        "hordeum vulgare": "barley",
        # ── Canola / Rapeseed ─────────────────────────────────────────────
        "canola": "canola", "canola oil": "canola",
        "rapeseed": "canola", "rape": "canola",
        "colza": "canola", "brassica napus": "canola",
        # ── Sugar beet ────────────────────────────────────────────────────
        "sugar beet": "sugar_beets", "sugar beets": "sugar_beets",
        "beet sugar": "sugar_beets", "beta vulgaris": "sugar_beets",
        # ── Buckwheat ─────────────────────────────────────────────────────
        "buckwheat": "buckwheat", "buckwheat flour": "buckwheat",
        "buckwheat grain": "buckwheat", "fagopyrum esculentum": "buckwheat",
        # ── Quinoa ────────────────────────────────────────────────────────
        "quinoa": "quinoa", "quinoa grain": "quinoa",
        "chenopodium quinoa": "quinoa",
        # ── Rye ───────────────────────────────────────────────────────────
        "rye": "rye", "rye grain": "rye", "rye flour": "rye",
        "secale cereale": "rye",
        # ── Rice ──────────────────────────────────────────────────────────
        "rice": "rice", "white rice": "rice", "brown rice": "rice",
        "rice flour": "rice", "oryza sativa": "rice", "paddy rice": "rice",
        # ── Infant food ───────────────────────────────────────────────────
        "infant food": "infant_cereal", "baby food": "infant_cereal",
        "infant cereal": "infant_cereal", "children cereal": "infant_cereal",
        "infant formula": "infant_cereal", "toddler food": "infant_cereal",
        # ── Fresh vegetables ──────────────────────────────────────────────
        "fresh vegetables": "fresh_vegetables",
        "vegetables": "fresh_vegetables",
        "lettuce": "fresh_vegetables", "spinach": "fresh_vegetables",
        "root vegetables": "fresh_vegetables",
        "leafy vegetables": "fresh_vegetables",
        # ── Fresh fruit ───────────────────────────────────────────────────
        "fresh fruit": "fresh_fruit", "fruit": "fresh_fruit",
        "apples": "fresh_fruit", "citrus": "fresh_fruit",
        "stone fruit": "fresh_fruit", "berries": "fresh_fruit",
        # ── Sunflower ─────────────────────────────────────────────────────
        "sunflower": "sunflower", "sunflower seed": "sunflower",
        "sunflower oil": "sunflower", "helianthus annuus": "sunflower",
        # ── Butter (from USDA PDP) ────────────────────────────────────────
        "butter": "butter", "dairy butter": "butter",
        # ── Blueberries (from USDA PDP) ───────────────────────────────────
        "blueberry": "blueberries", "blueberries": "blueberries",
        "cultivated blueberries": "blueberries", "wild blueberries": "blueberries",
        # ── Canned beets (from USDA PDP) ──────────────────────────────────
        "canned beets": "canned_beets", "beets canned": "canned_beets",
        # ── Candy/snacks ──────────────────────────────────────────────────
        "candy": "corn", "confectionery": "corn",
        # ── Protein products ─────────────────────────────────────────────
        "protein bar": "soybeans", "protein powder": "soybeans",
        "pea protein": "soybeans",
        # ── UK-specific terms ─────────────────────────────────────────────
        "cereals": "wheat", "cereal": "wheat",
        "bread and rolls": "wheat",
        "breakfast cereal": "oats",
        # ── Additional grains ─────────────────────────────────────────────
        "millet": "corn", "sorghum": "corn",
        # ── Additional produce ────────────────────────────────────────────
        "strawberries": "fresh_fruit", "grapes": "fresh_fruit",
        "bananas": "fresh_fruit", "tomatoes": "fresh_vegetables",
        "potatoes": "fresh_vegetables", "carrots": "fresh_vegetables",
        "onions": "fresh_vegetables", "peppers": "fresh_vegetables",
        "cucumbers": "fresh_vegetables", "celery": "fresh_vegetables",
        "broccoli": "fresh_vegetables", "cabbage": "fresh_vegetables",
        "mushrooms": "fresh_vegetables",
        # ── Additional fruit ──────────────────────────────────────────────
        "oranges": "fresh_fruit", "pears": "fresh_fruit",
        "peaches": "fresh_fruit", "cherries": "fresh_fruit",
        "cranberries": "fresh_fruit", "raspberries": "fresh_fruit",
        # ── German terms (for BVL) ────────────────────────────────────────
        "getreide": "wheat", "hafer": "oats", "soja": "soybeans",
        "mais": "corn", "gerste": "barley", "roggen": "rye",
        "reis": "rice", "hülsenfrüchte": "beans",
        # ── General produce groups ────────────────────────────────────────
        "oilseeds": "canola", "nuts": "fresh_fruit",
        "dried fruit": "fresh_fruit", "juice": "fresh_fruit",
        "processed food": "wheat", "snacks": "corn",
        "crackers": "wheat", "chips": "corn",
        "granola": "oats", "muesli": "oats",
    }

    conn.executemany(
        "INSERT OR IGNORE INTO category_aliases (alias, canonical_key) VALUES (?, ?)",
        aliases.items()
    )
    logger.info("Seeded %d category aliases", len(aliases))


def normalize_category(raw: str, conn=None) -> Optional[str]:
    """
    Map any raw category string to a canonical key.
    Uses the database aliases table. Falls back to substring matching.
    Returns None if no match found — caller must handle this.
    """
    if not raw:
        return None
    cleaned = raw.lower().strip()

    def _lookup(c):
        # 1. Exact match
        row = c.execute(
            "SELECT canonical_key FROM category_aliases WHERE alias = ?", (cleaned,)
        ).fetchone()
        if row:
            return row[0]
        # 2. Substring: find all aliases that appear inside the raw string
        rows = c.execute("SELECT alias, canonical_key FROM category_aliases").fetchall()
        for alias, key in rows:
            if alias in cleaned:
                return key
        return None

    if conn:
        return _lookup(conn)
    with get_connection() as c:
        return _lookup(c)


def build_dedup_key(*parts) -> str:
    """Deterministic key to prevent duplicate rows on re-runs."""
    combined = "|".join(str(p).lower().strip() for p in parts if p is not None)
    return hashlib.sha256(combined.encode()).hexdigest()[:32]


def insert_rows(rows: list[dict], source_name: str, source_file: str = "") -> dict:
    """
    Insert a batch of normalized rows. Skips duplicates via dedup_key.
    Returns counts: {inserted, skipped, failed}
    """
    inserted = skipped = failed = 0
    with get_connection() as conn:
        for row in rows:
            if not row.get("dedup_key"):
                logger.warning("Row missing dedup_key — skipping: %s", row)
                failed += 1
                continue
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO glyphosate_measurements (
                        tier, source_name, source_url, report_label, published_date,
                        data_year, food_category, raw_category, product_name,
                        measured_ppb, below_detection, samples_total, samples_detected,
                        detection_rate, avg_ppb, max_ppb, p95_ppb,
                        original_unit, unit_conversion, is_organic, is_grf_certified,
                        methodology_note, confidence, dedup_key, raw_file_path
                    ) VALUES (
                        :tier, :source_name, :source_url, :report_label, :published_date,
                        :data_year, :food_category, :raw_category, :product_name,
                        :measured_ppb, :below_detection, :samples_total, :samples_detected,
                        :detection_rate, :avg_ppb, :max_ppb, :p95_ppb,
                        :original_unit, :unit_conversion, :is_organic, :is_grf_certified,
                        :methodology_note, :confidence, :dedup_key, :raw_file_path
                    )
                """, {**_defaults(), **row})
                changes = conn.execute("SELECT changes()").fetchone()[0]
                if changes:
                    inserted += 1
                else:
                    skipped += 1
            except sqlite3.Error as e:
                logger.error("Insert failed for row %s: %s", row.get("dedup_key"), e)
                failed += 1

    log_ingest(source_name, "success" if failed == 0 else "partial",
               inserted, skipped, failed, source_file=source_file)
    return {"inserted": inserted, "skipped": skipped, "failed": failed}


def log_ingest(source_name, status, inserted=0, skipped=0, failed=0,
               error_message=None, source_file=""):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO ingest_log
                (source_name, status, rows_inserted, rows_skipped, rows_failed,
                 error_message, source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (source_name, status, inserted, skipped, failed, error_message, source_file))


def _defaults() -> dict:
    return {
        "product_name": None, "measured_ppb": None, "below_detection": 0,
        "samples_total": None, "samples_detected": None, "detection_rate": None,
        "avg_ppb": None, "max_ppb": None, "p95_ppb": None,
        "original_unit": "ppb", "unit_conversion": 1.0,
        "is_organic": 0, "is_grf_certified": 0,
        "methodology_note": None, "raw_file_path": None,
    }
