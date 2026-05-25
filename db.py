import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "glyphosate.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS glyphosate_data (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tier              INTEGER NOT NULL,
    source_name       TEXT NOT NULL,
    source_url        TEXT,
    published_date    TEXT,
    data_year         INTEGER,
    product_name      TEXT,
    brand             TEXT,
    barcode           TEXT,
    food_category     TEXT NOT NULL,
    raw_category      TEXT,
    ppb_value         REAL,
    detection_rate    REAL,
    avg_ppb           REAL,
    max_ppb           REAL,
    min_ppb           REAL,
    sample_count      INTEGER,
    confidence        TEXT,
    methodology_note  TEXT,
    is_organic        INTEGER DEFAULT 0,
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_food_category ON glyphosate_data(food_category);
CREATE INDEX IF NOT EXISTS idx_tier ON glyphosate_data(tier);
CREATE INDEX IF NOT EXISTS idx_product_name ON glyphosate_data(product_name);
CREATE INDEX IF NOT EXISTS idx_brand ON glyphosate_data(brand);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.close()
    print(f"Database initialized at {DB_PATH}")


def insert_rows(rows: list[dict]):
    if not rows:
        print("No rows to insert.")
        return

    conn = get_connection()
    cursor = conn.cursor()

    columns = [
        "tier", "source_name", "source_url", "published_date", "data_year",
        "product_name", "brand", "barcode", "food_category", "raw_category",
        "ppb_value", "detection_rate", "avg_ppb", "max_ppb", "min_ppb",
        "sample_count", "confidence", "methodology_note", "is_organic",
    ]

    placeholders = ", ".join(["?"] * len(columns))
    col_str = ", ".join(columns)

    inserted = 0
    for row in rows:
        values = []
        for col in columns:
            v = row.get(col)
            if col == "is_organic" and isinstance(v, bool):
                v = 1 if v else 0
            values.append(v)

        try:
            cursor.execute(
                f"INSERT OR IGNORE INTO glyphosate_data ({col_str}) VALUES ({placeholders})",
                values,
            )
            inserted += cursor.rowcount
        except Exception as e:
            print(f"  Skipping row due to error: {e}")
            print(f"  Row data: {row.get('product_name', row.get('food_category', 'unknown'))}")

    conn.commit()
    conn.close()
    print(f"  Inserted {inserted} new rows ({len(rows) - inserted} duplicates skipped)")
