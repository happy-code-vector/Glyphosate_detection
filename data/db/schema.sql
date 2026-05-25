-- ResidueIQ SQLite Schema
-- Run once to initialize. Idempotent (safe to re-run).

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ─────────────────────────────────────────────
-- Core data table
-- Every row is one measurement from one source.
-- Tier 1 = named product with measured ppb.
-- Tier 2 = food category with detection rate.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS glyphosate_measurements (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Classification
    tier                INTEGER NOT NULL CHECK (tier IN (1, 2)),
    source_name         TEXT    NOT NULL,   -- 'EWG' | 'FloridaHFF' | 'CFIA' | 'EFSA' | 'FDA'
    source_url          TEXT    NOT NULL,
    report_label        TEXT    NOT NULL,   -- e.g. 'EWG Oat Test 2023', 'CFIA 2015-2016'
    published_date      TEXT    NOT NULL,   -- ISO date: '2023-04-01'
    data_year           INTEGER NOT NULL,

    -- Food classification
    food_category       TEXT    NOT NULL,   -- canonical key from category map
    raw_category        TEXT    NOT NULL,   -- original string from source, never modified

    -- Tier 1 fields (product-specific measurements)
    -- NULL for Tier 2 rows
    product_name        TEXT,
    measured_ppb        REAL,               -- actual measured value
    below_detection     INTEGER DEFAULT 0,  -- 1 if result was <LOD (not zero, just undetected)

    -- Tier 2 fields (category aggregate statistics)
    -- NULL for Tier 1 rows
    samples_total       INTEGER,
    samples_detected    INTEGER,
    detection_rate      REAL,               -- 0.0–1.0, computed from samples_detected/samples_total
    avg_ppb             REAL,               -- mean across detected samples only
    max_ppb             REAL,
    p95_ppb             REAL,               -- 95th percentile if source provides it

    -- Units (always stored internally as ppb / µg/kg)
    -- Source values are converted on ingest. Conversion factor stored for audit.
    original_unit       TEXT,               -- e.g. 'mg/kg', 'ppb', 'µg/kg'
    unit_conversion     REAL DEFAULT 1.0,   -- multiplier applied to get ppb

    -- Quality flags
    is_organic          INTEGER DEFAULT 0,  -- 1 if product/category is organic
    is_grf_certified    INTEGER DEFAULT 0,  -- 1 if Glyphosate Residue Free certified
    methodology_note    TEXT,               -- lab method, caveats, limitations
    confidence          TEXT NOT NULL       -- 'high' | 'medium' | 'low'
                        CHECK (confidence IN ('high', 'medium', 'low')),

    -- Deduplication key — prevents re-inserting same data on re-runs
    dedup_key           TEXT UNIQUE NOT NULL,

    -- Housekeeping
    ingested_at         TEXT DEFAULT (datetime('now')),
    raw_file_path       TEXT                -- path to source file used for this row
);

CREATE INDEX IF NOT EXISTS idx_food_category  ON glyphosate_measurements(food_category);
CREATE INDEX IF NOT EXISTS idx_tier           ON glyphosate_measurements(tier);
CREATE INDEX IF NOT EXISTS idx_source         ON glyphosate_measurements(source_name);
CREATE INDEX IF NOT EXISTS idx_data_year      ON glyphosate_measurements(data_year);
CREATE INDEX IF NOT EXISTS idx_product_name   ON glyphosate_measurements(product_name);

-- ─────────────────────────────────────────────
-- Category map — authoritative list of canonical keys
-- and every known alias that maps to them
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS category_aliases (
    alias               TEXT PRIMARY KEY,   -- lowercased raw string from any source
    canonical_key       TEXT NOT NULL       -- key used in glyphosate_measurements.food_category
);

CREATE INDEX IF NOT EXISTS idx_canonical ON category_aliases(canonical_key);

-- ─────────────────────────────────────────────
-- Ingest log — one row per pipeline run per source
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ingest_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name         TEXT NOT NULL,
    run_at              TEXT DEFAULT (datetime('now')),
    status              TEXT NOT NULL CHECK (status IN ('success', 'failed', 'partial')),
    rows_inserted       INTEGER DEFAULT 0,
    rows_skipped        INTEGER DEFAULT 0,   -- dedup hits
    rows_failed         INTEGER DEFAULT 0,
    error_message       TEXT,
    source_file         TEXT                 -- path or URL fetched
);

-- ─────────────────────────────────────────────
-- App-facing view: best available data per category
-- Resolves conflicts when multiple sources cover same category.
-- Source priority: EWG > FDA > CFIA > EFSA
-- Within same source: most recent data_year wins.
-- ─────────────────────────────────────────────
CREATE VIEW IF NOT EXISTS category_risk AS
SELECT
    food_category,
    source_name,
    report_label,
    published_date,
    data_year,
    samples_total,
    samples_detected,
    detection_rate,
    avg_ppb,
    max_ppb,
    confidence,
    methodology_note,
    CASE
        WHEN detection_rate >= 0.66 THEN 'high'
        WHEN detection_rate >= 0.31 THEN 'medium'
        WHEN detection_rate >  0.0  THEN 'low'
        ELSE 'none'
    END AS risk_level
FROM glyphosate_measurements
WHERE tier = 2
  AND food_category IN (
      SELECT food_category FROM glyphosate_measurements
      WHERE tier = 2
      GROUP BY food_category
      HAVING MAX(
          CASE source_name
              WHEN 'EWG' THEN 4
              WHEN 'FDA' THEN 3
              WHEN 'CFIA' THEN 2
              WHEN 'EFSA' THEN 1
              ELSE 0
          END
      )
  );

-- ─────────────────────────────────────────────
-- App-facing view: Tier 1 product results
-- ─────────────────────────────────────────────
CREATE VIEW IF NOT EXISTS product_results AS
SELECT
    product_name,
    food_category,
    source_name,
    report_label,
    published_date,
    data_year,
    measured_ppb,
    below_detection,
    is_organic,
    confidence,
    methodology_note,
    source_url,
    CASE
        WHEN below_detection = 1 THEN 'none'
        WHEN measured_ppb >= 500  THEN 'high'
        WHEN measured_ppb >= 100  THEN 'medium'
        WHEN measured_ppb >  0    THEN 'low'
        ELSE 'unknown'
    END AS risk_level
FROM glyphosate_measurements
WHERE tier = 1;
