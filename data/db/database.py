"""
db/database.py
Core database operations. All pipeline code imports from here.
"""

import csv
import sqlite3
import hashlib
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "residueiq.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"
ALIASES_PATH = Path(__file__).parent / "category_aliases.csv"


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
        _migrate_legacy(conn)
        conn.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
        _seed_category_aliases(conn)
    logger.info("Database initialized at %s", DB_PATH)


def _migrate_legacy(conn):
    """Migrate data from old glyphosate_measurements table to new split tables."""
    # Check if legacy table exists
    legacy = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='glyphosate_measurements'"
    ).fetchone()
    if not legacy:
        return

    # Check if migration already done (new tables exist with data)
    new_tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('product_tests', 'category_summaries')"
    ).fetchall()
    if len(new_tables) == 2:
        # Check if new tables already have data — if so, migration done
        pt_count = conn.execute("SELECT COUNT(*) FROM product_tests").fetchone()[0]
        cs_count = conn.execute("SELECT COUNT(*) FROM category_summaries").fetchone()[0]
        if pt_count > 0 or cs_count > 0:
            logger.info("Legacy migration already complete (product_tests=%d, category_summaries=%d)",
                        pt_count, cs_count)
            return

    logger.info("Migrating legacy glyphosate_measurements to product_tests + category_summaries...")

    # Create new tables if they don't exist yet
    conn.execute("""
        CREATE TABLE IF NOT EXISTS product_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL, source_url TEXT NOT NULL, report_label TEXT NOT NULL,
            published_date TEXT NOT NULL, data_year INTEGER NOT NULL,
            food_category TEXT NOT NULL, raw_category TEXT NOT NULL,
            product_name TEXT NOT NULL, measured_ppb REAL, below_detection INTEGER DEFAULT 0,
            limit_of_detection REAL,
            original_unit TEXT DEFAULT 'ppb', unit_conversion REAL DEFAULT 1.0,
            is_organic INTEGER DEFAULT 0, is_grf_certified INTEGER DEFAULT 0,
            methodology_note TEXT, confidence TEXT NOT NULL,
            dedup_key TEXT UNIQUE NOT NULL,
            ingested_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')),
            raw_file_path TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS category_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL, source_url TEXT NOT NULL, report_label TEXT NOT NULL,
            published_date TEXT NOT NULL, data_year INTEGER NOT NULL,
            food_category TEXT NOT NULL, raw_category TEXT NOT NULL,
            samples_total INTEGER NOT NULL, samples_detected INTEGER NOT NULL,
            detection_rate REAL NOT NULL, avg_ppb REAL, max_ppb REAL, p95_ppb REAL,
            median_ppb REAL, min_ppb REAL,
            original_unit TEXT DEFAULT 'ppb', unit_conversion REAL DEFAULT 1.0,
            is_organic INTEGER DEFAULT 0, methodology_note TEXT, confidence TEXT NOT NULL,
            dedup_key TEXT UNIQUE NOT NULL,
            ingested_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')),
            raw_file_path TEXT
        )
    """)

    # Migrate Tier 1
    conn.execute("""
        INSERT OR IGNORE INTO product_tests (
            source_name, source_url, report_label, published_date, data_year,
            food_category, raw_category, product_name, measured_ppb, below_detection,
            original_unit, unit_conversion, is_organic, is_grf_certified,
            methodology_note, confidence, dedup_key, ingested_at, raw_file_path
        )
        SELECT
            source_name, source_url, report_label, published_date, data_year,
            food_category, raw_category, product_name, measured_ppb, below_detection,
            original_unit, unit_conversion, is_organic, is_grf_certified,
            methodology_note, confidence, dedup_key, ingested_at, raw_file_path
        FROM glyphosate_measurements
        WHERE tier = 1
    """)
    t1_migrated = conn.execute("SELECT changes()").fetchone()[0]

    # Migrate Tier 2
    conn.execute("""
        INSERT OR IGNORE INTO category_summaries (
            source_name, source_url, report_label, published_date, data_year,
            food_category, raw_category,
            samples_total, samples_detected, detection_rate, avg_ppb, max_ppb, p95_ppb,
            original_unit, unit_conversion, is_organic, methodology_note, confidence,
            dedup_key, ingested_at, raw_file_path
        )
        SELECT
            source_name, source_url, report_label, published_date, data_year,
            food_category, raw_category,
            COALESCE(samples_total, 0), COALESCE(samples_detected, 0),
            COALESCE(detection_rate, 0), avg_ppb, max_ppb, p95_ppb,
            original_unit, unit_conversion, is_organic, methodology_note, confidence,
            dedup_key, ingested_at, raw_file_path
        FROM glyphosate_measurements
        WHERE tier = 2
    """)
    t2_migrated = conn.execute("SELECT changes()").fetchone()[0]

    conn.commit()
    logger.info("Migrated %d Tier 1 rows to product_tests, %d Tier 2 rows to category_summaries",
                t1_migrated, t2_migrated)

    # Drop legacy table — the schema.sql will create the backward-compat view
    conn.execute("DROP TABLE IF EXISTS glyphosate_measurements")
    logger.info("Dropped legacy glyphosate_measurements table")


def _seed_category_aliases(conn):
    """
    Load aliases from category_aliases.csv.
    Extend the CSV when a new source introduces a new spelling — no code change needed.
    """
    if not ALIASES_PATH.exists():
        logger.warning("category_aliases.csv not found at %s", ALIASES_PATH)
        return

    with open(ALIASES_PATH, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        aliases = [(row[0].strip(), row[1].strip()) for row in reader if len(row) >= 2]

    conn.executemany(
        "INSERT OR IGNORE INTO category_aliases (alias, canonical_key) VALUES (?, ?)",
        aliases,
    )
    logger.info("Seeded %d category aliases from CSV", len(aliases))


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
    Insert a batch of normalized rows. Routes to product_tests (Tier 1)
    or category_summaries (Tier 2) based on the 'tier' field.
    Skips duplicates via dedup_key.
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
                tier = row.get("tier", 1)
                if tier == 1:
                    changes = _insert_product(conn, row)
                else:
                    changes = _insert_category(conn, row)

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


def _insert_product(conn, row: dict) -> int:
    """Insert a Tier 1 product test row."""
    defaults = {
        "measured_ppb": None, "below_detection": 0, "limit_of_detection": None,
        "original_unit": "ppb", "unit_conversion": 1.0,
        "is_organic": 0, "is_grf_certified": 0,
        "methodology_note": None, "raw_file_path": None,
    }
    r = {**defaults, **row}
    conn.execute("""
        INSERT OR IGNORE INTO product_tests (
            source_name, source_url, report_label, published_date, data_year,
            food_category, raw_category, product_name,
            measured_ppb, below_detection, limit_of_detection,
            original_unit, unit_conversion, is_organic, is_grf_certified,
            methodology_note, confidence, dedup_key, raw_file_path
        ) VALUES (
            :source_name, :source_url, :report_label, :published_date, :data_year,
            :food_category, :raw_category, :product_name,
            :measured_ppb, :below_detection, :limit_of_detection,
            :original_unit, :unit_conversion, :is_organic, :is_grf_certified,
            :methodology_note, :confidence, :dedup_key, :raw_file_path
        )
    """, r)
    return conn.execute("SELECT changes()").fetchone()[0]


def _insert_category(conn, row: dict) -> int:
    """Insert a Tier 2 category summary row."""
    defaults = {
        "samples_total": 0, "samples_detected": 0, "detection_rate": 0.0,
        "avg_ppb": None, "max_ppb": None, "p95_ppb": None,
        "median_ppb": None, "min_ppb": None,
        "original_unit": "ppb", "unit_conversion": 1.0,
        "is_organic": 0, "methodology_note": None, "raw_file_path": None,
    }
    r = {**defaults, **row}
    conn.execute("""
        INSERT OR IGNORE INTO category_summaries (
            source_name, source_url, report_label, published_date, data_year,
            food_category, raw_category,
            samples_total, samples_detected, detection_rate, avg_ppb, max_ppb, p95_ppb,
            median_ppb, min_ppb,
            original_unit, unit_conversion, is_organic,
            methodology_note, confidence, dedup_key, raw_file_path
        ) VALUES (
            :source_name, :source_url, :report_label, :published_date, :data_year,
            :food_category, :raw_category,
            :samples_total, :samples_detected, :detection_rate, :avg_ppb, :max_ppb, :p95_ppb,
            :median_ppb, :min_ppb,
            :original_unit, :unit_conversion, :is_organic,
            :methodology_note, :confidence, :dedup_key, :raw_file_path
        )
    """, r)
    return conn.execute("SELECT changes()").fetchone()[0]


def log_ingest(source_name, status, inserted=0, skipped=0, failed=0,
               error_message=None, source_file=""):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO ingest_log
                (source_name, status, rows_inserted, rows_skipped, rows_failed,
                 error_message, source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (source_name, status, inserted, skipped, failed, error_message, source_file))
