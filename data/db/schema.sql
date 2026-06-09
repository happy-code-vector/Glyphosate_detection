-- ResidueIQ SQLite Schema
-- Run once to initialize. Idempotent (safe to re-run).

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ─────────────────────────────────────────────
-- Tier 1: Individual product test results
-- Every row is one measurement of one named product.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS product_tests (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Source metadata
    source_name         TEXT    NOT NULL,
    source_url          TEXT    NOT NULL,
    report_label        TEXT    NOT NULL,
    published_date      TEXT    NOT NULL,
    data_year           INTEGER NOT NULL,

    -- Food classification
    food_category       TEXT    NOT NULL,
    raw_category        TEXT    NOT NULL,
    contaminant         TEXT    NOT NULL DEFAULT 'glyphosate',

    -- Product-specific measurement
    product_name        TEXT    NOT NULL,
    measured_ppb        REAL,
    below_detection     INTEGER DEFAULT 0,
    limit_of_detection  REAL,               -- LOD in ppb if reported

    -- Units (always stored internally as ppb)
    original_unit       TEXT    DEFAULT 'ppb',
    unit_conversion     REAL    DEFAULT 1.0,

    -- Quality flags
    is_organic          INTEGER DEFAULT 0,
    is_grf_certified    INTEGER DEFAULT 0,
    methodology_note    TEXT,
    confidence          TEXT    NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),

    -- Deduplication
    dedup_key           TEXT UNIQUE NOT NULL,

    -- Housekeeping
    ingested_at         TEXT    DEFAULT (datetime('now')),
    updated_at          TEXT    DEFAULT (datetime('now')),
    raw_file_path       TEXT
);

CREATE INDEX IF NOT EXISTS idx_pt_food_category   ON product_tests(food_category);
CREATE INDEX IF NOT EXISTS idx_pt_source          ON product_tests(source_name);
CREATE INDEX IF NOT EXISTS idx_pt_data_year       ON product_tests(data_year);
CREATE INDEX IF NOT EXISTS idx_pt_product_name    ON product_tests(product_name);
CREATE INDEX IF NOT EXISTS idx_pt_organic         ON product_tests(is_organic);
CREATE INDEX IF NOT EXISTS idx_pt_contaminant    ON product_tests(contaminant);

-- ─────────────────────────────────────────────
-- Tier 2: Category-level aggregate summaries
-- Every row is one aggregate statistic per food category per source.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS category_summaries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Source metadata
    source_name         TEXT    NOT NULL,
    source_url          TEXT    NOT NULL,
    report_label        TEXT    NOT NULL,
    published_date      TEXT    NOT NULL,
    data_year           INTEGER NOT NULL,

    -- Food classification
    food_category       TEXT    NOT NULL,
    raw_category        TEXT    NOT NULL,
    contaminant         TEXT    NOT NULL DEFAULT 'glyphosate',

    -- Aggregate statistics
    samples_total       INTEGER NOT NULL,
    samples_detected    INTEGER NOT NULL,
    detection_rate      REAL    NOT NULL,   -- 0.0–1.0
    avg_ppb             REAL,
    max_ppb             REAL,
    p95_ppb             REAL,
    median_ppb          REAL,
    min_ppb             REAL,

    -- Units
    original_unit       TEXT    DEFAULT 'ppb',
    unit_conversion     REAL    DEFAULT 1.0,

    -- Quality flags
    is_organic          INTEGER DEFAULT 0,
    methodology_note    TEXT,
    confidence          TEXT    NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),

    -- Deduplication
    dedup_key           TEXT UNIQUE NOT NULL,

    -- Housekeeping
    ingested_at         TEXT    DEFAULT (datetime('now')),
    updated_at          TEXT    DEFAULT (datetime('now')),
    raw_file_path       TEXT
);

CREATE INDEX IF NOT EXISTS idx_cs_food_category   ON category_summaries(food_category);
CREATE INDEX IF NOT EXISTS idx_cs_source          ON category_summaries(source_name);
CREATE INDEX IF NOT EXISTS idx_cs_data_year       ON category_summaries(data_year);
CREATE INDEX IF NOT EXISTS idx_cs_detection_rate  ON category_summaries(detection_rate);
CREATE INDEX IF NOT EXISTS idx_cs_contaminant    ON category_summaries(contaminant);

-- ─────────────────────────────────────────────
-- Backward-compat view: glyphosate_measurements
-- Unions both tables so existing queries still work during migration.
-- ─────────────────────────────────────────────
DROP VIEW IF EXISTS glyphosate_measurements;
CREATE VIEW glyphosate_measurements AS
SELECT
    id, 1 AS tier, source_name, source_url, report_label, published_date, data_year,
    food_category, raw_category, contaminant,
    product_name, measured_ppb, below_detection,
    NULL AS samples_total, NULL AS samples_detected, NULL AS detection_rate,
    NULL AS avg_ppb, NULL AS max_ppb, NULL AS p95_ppb,
    original_unit, unit_conversion,
    is_organic, is_grf_certified, methodology_note, confidence,
    dedup_key, ingested_at, raw_file_path
FROM product_tests
WHERE contaminant = 'glyphosate'
UNION ALL
SELECT
    id, 2 AS tier, source_name, source_url, report_label, published_date, data_year,
    food_category, raw_category, contaminant,
    NULL AS product_name, NULL AS measured_ppb, 0 AS below_detection,
    samples_total, samples_detected, detection_rate,
    avg_ppb, max_ppb, p95_ppb,
    original_unit, unit_conversion,
    is_organic, 0 AS is_grf_certified, methodology_note, confidence,
    dedup_key, ingested_at, raw_file_path
FROM category_summaries
WHERE contaminant = 'glyphosate';

-- ─────────────────────────────────────────────
-- Category map — authoritative list of canonical keys
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS category_aliases (
    alias               TEXT PRIMARY KEY,
    canonical_key       TEXT NOT NULL
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
    rows_skipped        INTEGER DEFAULT 0,
    rows_failed         INTEGER DEFAULT 0,
    error_message       TEXT,
    source_file         TEXT
);

-- ─────────────────────────────────────────────
-- Data versioning — track what changed and when
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS data_versions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name          TEXT NOT NULL,
    row_id              INTEGER NOT NULL,
    field_name          TEXT NOT NULL,
    old_value           TEXT,
    new_value           TEXT,
    changed_at          TEXT DEFAULT (datetime('now')),
    changed_by          TEXT DEFAULT 'pipeline',
    dedup_key           TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_dv_table_row ON data_versions(table_name, row_id);

-- ─────────────────────────────────────────────
-- Regulatory tolerance limits
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tolerance_limits (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    food_category       TEXT NOT NULL,
    raw_commodity       TEXT,
    tolerance_ppm       REAL NOT NULL,
    tolerance_ppb       REAL NOT NULL,
    contaminant         TEXT NOT NULL DEFAULT 'glyphosate',
    source              TEXT NOT NULL,
    regulation_reference TEXT,
    updated_at          TEXT DEFAULT (datetime('now')),
    dedup_key           TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_tl_contaminant  ON tolerance_limits(contaminant);

-- ─────────────────────────────────────────────
-- Biomonitoring data
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS biomonitoring (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL DEFAULT 'CDC_NHANES',
    cycle               TEXT NOT NULL,
    analyte             TEXT NOT NULL,
    population_group    TEXT,
    sample_size         INTEGER,
    detected_count      INTEGER,
    detection_rate      REAL,
    geometric_mean      REAL,
    percentile_50       REAL,
    percentile_75       REAL,
    percentile_90       REAL,
    percentile_95       REAL,
    unit                TEXT DEFAULT 'ng/mL',
    lod                 REAL,
    updated_at          TEXT DEFAULT (datetime('now')),
    dedup_key           TEXT UNIQUE
);

-- ─────────────────────────────────────────────
-- Certified products
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS certified_products (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name        TEXT NOT NULL,
    brand               TEXT,
    food_category       TEXT,
    raw_category        TEXT,
    certification       TEXT DEFAULT 'Glyphosate Residue Free',
    threshold_ppb       REAL DEFAULT 10.0,
    source              TEXT NOT NULL DEFAULT 'DetoxProject',
    source_url          TEXT,
    verified_date       TEXT,
    updated_at          TEXT DEFAULT (datetime('now')),
    dedup_key           TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_cert_products_brand ON certified_products(brand);
CREATE INDEX IF NOT EXISTS idx_cert_products_category ON certified_products(food_category);
CREATE INDEX IF NOT EXISTS idx_cert_products_source ON certified_products(source);

-- ─────────────────────────────────────────────
-- International MRLs
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS international_mrls (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    food_category       TEXT NOT NULL,
    raw_commodity       TEXT,
    pesticide           TEXT NOT NULL DEFAULT 'glyphosate',
    country_region      TEXT NOT NULL,
    mrl_ppm             REAL NOT NULL,
    mrl_ppb             REAL NOT NULL,
    regulatory_body     TEXT,
    source_url          TEXT,
    updated_at          TEXT DEFAULT (datetime('now')),
    dedup_key           TEXT UNIQUE
);

-- ═════════════════════════════════════════════
-- APP-FACING VIEWS
-- ═════════════════════════════════════════════

-- ─────────────────────────────────────────────
-- Legacy view: category_risk (updated for new tables)
-- ─────────────────────────────────────────────
DROP VIEW IF EXISTS category_risk;
CREATE VIEW category_risk AS
SELECT
    cs.food_category,
    cs.source_name,
    cs.report_label,
    cs.published_date,
    cs.data_year,
    cs.samples_total,
    cs.samples_detected,
    cs.detection_rate,
    cs.avg_ppb,
    cs.max_ppb,
    cs.confidence,
    cs.methodology_note,
    CASE
        WHEN cs.detection_rate >= 0.66 THEN 'high'
        WHEN cs.detection_rate >= 0.31 THEN 'medium'
        WHEN cs.detection_rate >  0.0  THEN 'low'
        ELSE 'none'
    END AS risk_level
FROM category_summaries cs
WHERE cs.contaminant = 'glyphosate'
AND cs.food_category IN (
    SELECT sub.food_category FROM category_summaries sub
    WHERE sub.contaminant = 'glyphosate'
    GROUP BY sub.food_category
    HAVING MAX(
        CASE sub.source_name
            WHEN 'FDA' THEN 3
            WHEN 'CFIA' THEN 2
            WHEN 'EFSA' THEN 1
            ELSE 0
        END
    )
);

-- ─────────────────────────────────────────────
-- Legacy view: product_results (updated for new tables)
-- ─────────────────────────────────────────────
DROP VIEW IF EXISTS product_results;
CREATE VIEW product_results AS
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
FROM product_tests
WHERE contaminant = 'glyphosate';

-- ─────────────────────────────────────────────
-- app_food_overview: One row per food category
-- Best-available stats with source priority resolution.
-- ─────────────────────────────────────────────
DROP VIEW IF EXISTS app_food_overview;
CREATE VIEW app_food_overview AS
WITH best_summary AS (
    SELECT
        cs.food_category,
        cs.source_name,
        cs.report_label,
        cs.data_year,
        cs.samples_total,
        cs.samples_detected,
        cs.detection_rate,
        cs.avg_ppb,
        cs.max_ppb,
        cs.confidence,
        CASE
            WHEN cs.detection_rate >= 0.66 THEN 'high'
            WHEN cs.detection_rate >= 0.31 THEN 'medium'
            WHEN cs.detection_rate >  0.0  THEN 'low'
            ELSE 'none'
        END AS risk_level,
        ROW_NUMBER() OVER (
            PARTITION BY cs.food_category
            ORDER BY
                CASE cs.source_name
                    WHEN 'FDA' THEN 3
                    WHEN 'CFIA' THEN 2
                    WHEN 'EFSA' THEN 1
                    ELSE 0
                END DESC,
                cs.data_year DESC
        ) AS rn
    FROM category_summaries cs
    WHERE cs.contaminant = 'glyphosate'
),
product_stats AS (
    SELECT
        pt.food_category,
        COUNT(*) AS total_products_tested,
        SUM(CASE WHEN pt.below_detection = 0 THEN 1 ELSE 0 END) AS products_with_detection,
        ROUND(AVG(pt.measured_ppb), 1) AS avg_product_ppb,
        MAX(pt.measured_ppb) AS max_product_ppb
    FROM product_tests pt
    WHERE pt.contaminant = 'glyphosate'
    GROUP BY pt.food_category
),
cert_count AS (
    SELECT
        cp.food_category,
        COUNT(*) AS certified_product_count
    FROM certified_products cp
    GROUP BY cp.food_category
)
SELECT
    bs.food_category,
    bs.source_name          AS best_source,
    bs.data_year            AS best_data_year,
    bs.detection_rate       AS detection_rate,
    bs.avg_ppb              AS avg_ppb,
    bs.max_ppb              AS max_ppb,
    bs.samples_total,
    bs.samples_detected,
    bs.risk_level,
    bs.confidence,
    COALESCE(ps.total_products_tested, 0)    AS total_products_tested,
    COALESCE(ps.products_with_detection, 0)  AS products_with_detection,
    COALESCE(ps.avg_product_ppb, 0)          AS avg_product_ppb,
    COALESCE(ps.max_product_ppb, 0)          AS max_product_ppb,
    COALESCE(cc.certified_product_count, 0)  AS certified_products_available
FROM best_summary bs
LEFT JOIN product_stats ps ON bs.food_category = ps.food_category
LEFT JOIN cert_count cc    ON bs.food_category = cc.food_category
WHERE bs.rn = 1;

-- ─────────────────────────────────────────────
-- app_product_lookup: Optimized for barcode/name search
-- All individual product results with category context.
-- ─────────────────────────────────────────────
DROP VIEW IF EXISTS app_product_lookup;
CREATE VIEW app_product_lookup AS
SELECT
    pt.product_name,
    pt.food_category,
    pt.source_name,
    pt.report_label,
    pt.data_year,
    pt.measured_ppb,
    pt.below_detection,
    pt.limit_of_detection,
    pt.is_organic,
    pt.is_grf_certified,
    pt.confidence,
    pt.methodology_note,
    pt.source_url,
    pt.updated_at,
    CASE
        WHEN pt.is_grf_certified = 1 THEN 'certified_grf'
        WHEN pt.is_organic = 1 AND pt.below_detection = 1 THEN 'organic_clean'
        WHEN pt.is_organic = 1 THEN 'organic_detected'
        WHEN pt.below_detection = 1 THEN 'none'
        WHEN pt.measured_ppb >= 500 THEN 'high'
        WHEN pt.measured_ppb >= 100 THEN 'medium'
        WHEN pt.measured_ppb > 0 THEN 'low'
        ELSE 'unknown'
    END AS risk_level
FROM product_tests pt
WHERE pt.contaminant = 'glyphosate'
ORDER BY pt.food_category, pt.product_name;
-- Shows how detection levels compare to legal limits.
-- ─────────────────────────────────────────────
DROP VIEW IF EXISTS app_regulatory_limits;
CREATE VIEW app_regulatory_limits AS
SELECT
    cs.food_category,
    cs.source_name,
    cs.data_year,
    cs.detection_rate,
    cs.max_ppb              AS measured_max_ppb,
    cs.avg_ppb              AS measured_avg_ppb,
    tl.tolerance_ppb        AS epa_tolerance_ppb,
    tl.tolerance_ppm        AS epa_tolerance_ppm,
    tl.source               AS tolerance_source,
    tl.regulation_reference,
    CASE
        WHEN tl.tolerance_ppb > 0 AND cs.max_ppb IS NOT NULL
        THEN ROUND(cs.max_ppb / tl.tolerance_ppb * 100, 1)
        ELSE NULL
    END AS pct_of_tolerance
FROM category_summaries cs
LEFT JOIN tolerance_limits tl
    ON cs.food_category = tl.food_category
    AND cs.contaminant = tl.contaminant
WHERE cs.detection_rate > 0
AND cs.contaminant = 'glyphosate'
ORDER BY cs.food_category, cs.data_year DESC;

-- ─────────────────────────────────────────────
-- app_international_comparison: Side-by-side MRL comparison
-- Compare regulatory limits across countries.
-- ─────────────────────────────────────────────
DROP VIEW IF EXISTS app_international_comparison;
CREATE VIEW app_international_comparison AS
SELECT
    im.food_category,
    im.raw_commodity,
    im.country_region,
    im.mrl_ppm,
    im.mrl_ppb,
    im.regulatory_body,
    im.source_url,
    cs.detection_rate,
    cs.max_ppb              AS measured_max_ppb,
    CASE
        WHEN im.mrl_ppb > 0 AND cs.max_ppb IS NOT NULL
        THEN ROUND(cs.max_ppb / im.mrl_ppb * 100, 1)
        ELSE NULL
    END AS pct_of_mrl
FROM international_mrls im
LEFT JOIN category_summaries cs
    ON im.food_category = cs.food_category
    AND cs.contaminant = 'glyphosate'
WHERE im.pesticide = 'glyphosate'
ORDER BY im.food_category, im.mrl_ppb ASC;

-- ═════════════════════════════════════════════
-- WATER TESTS
-- ═════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS water_tests (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name         TEXT    NOT NULL,
    source_url          TEXT,
    report_label        TEXT    NOT NULL,
    data_year           INTEGER NOT NULL,

    -- Location
    state               TEXT,
    county              TEXT,
    site_type           TEXT,
    site_id             TEXT,
    latitude            REAL,
    longitude           REAL,

    -- Measurement
    water_type          TEXT    NOT NULL,
    contaminant         TEXT    NOT NULL DEFAULT 'glyphosate',
    measured_ppb        REAL,
    below_detection     INTEGER DEFAULT 0,
    detection_limit_ppb REAL,
    analytical_method   TEXT,

    -- Aggregation
    sample_date         TEXT,
    is_aggregate        INTEGER DEFAULT 0,
    samples_total       INTEGER,
    samples_detected    INTEGER,
    detection_rate      REAL,
    avg_ppb             REAL,
    max_ppb             REAL,

    -- Quality
    methodology_note    TEXT,
    confidence          TEXT    CHECK (confidence IN ('high', 'medium', 'low')),

    -- Dedup / housekeeping
    dedup_key           TEXT UNIQUE NOT NULL,
    ingested_at         TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_wt_state       ON water_tests(state);
CREATE INDEX IF NOT EXISTS idx_wt_water_type  ON water_tests(water_type);
CREATE INDEX IF NOT EXISTS idx_wt_data_year   ON water_tests(data_year);
CREATE INDEX IF NOT EXISTS idx_wt_source      ON water_tests(source_name);
CREATE INDEX IF NOT EXISTS idx_wt_aggregate   ON water_tests(is_aggregate);
CREATE INDEX IF NOT EXISTS idx_wt_contaminant ON water_tests(contaminant);

-- ─────────────────────────────────────────────
-- app_water_overview: Aggregated water stats by state
-- ─────────────────────────────────────────────
DROP VIEW IF EXISTS app_water_overview;
CREATE VIEW app_water_overview AS
SELECT
    wt.state,
    wt.water_type,
    wt.source_name,
    wt.report_label,
    wt.data_year,
    wt.samples_total,
    wt.samples_detected,
    wt.detection_rate,
    wt.avg_ppb,
    wt.max_ppb,
    tl.tolerance_ppb       AS epa_mcl_ppb,
    CASE
        WHEN tl.tolerance_ppb > 0 AND wt.max_ppb IS NOT NULL
        THEN ROUND(wt.max_ppb / tl.tolerance_ppb * 100, 1)
        ELSE NULL
    END AS pct_of_mcl
FROM water_tests wt
LEFT JOIN tolerance_limits tl
    ON tl.food_category = 'drinking_water' AND tl.source = 'EPA_MCL'
    AND tl.contaminant = wt.contaminant
WHERE wt.is_aggregate = 1
AND wt.contaminant = 'glyphosate'
ORDER BY wt.state, wt.water_type, wt.data_year DESC;

-- ═════════════════════════════════════════════
-- MULTI-CONTAMINANT VIEWS (no glyphosate filter)
-- ═════════════════════════════════════════════

DROP VIEW IF EXISTS app_food_overview_all;
CREATE VIEW app_food_overview_all AS
WITH best_summary AS (
    SELECT
        cs.food_category,
        cs.contaminant,
        cs.source_name,
        cs.report_label,
        cs.data_year,
        cs.samples_total,
        cs.samples_detected,
        cs.detection_rate,
        cs.avg_ppb,
        cs.max_ppb,
        cs.confidence,
        CASE
            WHEN cs.detection_rate >= 0.66 THEN 'high'
            WHEN cs.detection_rate >= 0.31 THEN 'medium'
            WHEN cs.detection_rate >  0.0  THEN 'low'
            ELSE 'none'
        END AS risk_level,
        ROW_NUMBER() OVER (
            PARTITION BY cs.food_category, cs.contaminant
            ORDER BY
                CASE cs.source_name
                    WHEN 'FDA' THEN 3
                    WHEN 'CFIA' THEN 2
                    WHEN 'EFSA' THEN 1
                    ELSE 0
                END DESC,
                cs.data_year DESC
        ) AS rn
    FROM category_summaries cs
),
product_stats AS (
    SELECT
        pt.food_category,
        pt.contaminant,
        COUNT(*) AS total_products_tested,
        SUM(CASE WHEN pt.below_detection = 0 THEN 1 ELSE 0 END) AS products_with_detection,
        ROUND(AVG(pt.measured_ppb), 1) AS avg_product_ppb,
        MAX(pt.measured_ppb) AS max_product_ppb
    FROM product_tests pt
    GROUP BY pt.food_category, pt.contaminant
)
SELECT
    bs.contaminant,
    bs.food_category,
    bs.source_name          AS best_source,
    bs.data_year            AS best_data_year,
    bs.detection_rate       AS detection_rate,
    bs.avg_ppb              AS avg_ppb,
    bs.max_ppb              AS max_ppb,
    bs.samples_total,
    bs.samples_detected,
    bs.risk_level,
    bs.confidence,
    COALESCE(ps.total_products_tested, 0)    AS total_products_tested,
    COALESCE(ps.products_with_detection, 0)  AS products_with_detection,
    COALESCE(ps.avg_product_ppb, 0)          AS avg_product_ppb,
    COALESCE(ps.max_product_ppb, 0)          AS max_product_ppb
FROM best_summary bs
LEFT JOIN product_stats ps
    ON bs.food_category = ps.food_category
    AND bs.contaminant = ps.contaminant
WHERE bs.rn = 1;

DROP VIEW IF EXISTS app_product_lookup_all;
CREATE VIEW app_product_lookup_all AS
SELECT
    pt.contaminant,
    pt.product_name,
    pt.food_category,
    pt.source_name,
    pt.report_label,
    pt.data_year,
    pt.measured_ppb,
    pt.below_detection,
    pt.limit_of_detection,
    pt.is_organic,
    pt.is_grf_certified,
    pt.confidence,
    pt.methodology_note,
    pt.source_url,
    pt.updated_at
FROM product_tests pt
ORDER BY pt.contaminant, pt.food_category, pt.product_name;

DROP VIEW IF EXISTS app_water_overview_all;
CREATE VIEW app_water_overview_all AS
SELECT
    wt.contaminant,
    wt.state,
    wt.water_type,
    wt.source_name,
    wt.report_label,
    wt.data_year,
    wt.samples_total,
    wt.samples_detected,
    wt.detection_rate,
    wt.avg_ppb,
    wt.max_ppb,
    tl.tolerance_ppb       AS epa_mcl_ppb,
    CASE
        WHEN tl.tolerance_ppb > 0 AND wt.max_ppb IS NOT NULL
        THEN ROUND(wt.max_ppb / tl.tolerance_ppb * 100, 1)
        ELSE NULL
    END AS pct_of_mcl
FROM water_tests wt
LEFT JOIN tolerance_limits tl
    ON tl.food_category = 'drinking_water'
    AND tl.source = 'EPA_MCL'
    AND tl.contaminant = wt.contaminant
WHERE wt.is_aggregate = 1
ORDER BY wt.contaminant, wt.state, wt.water_type, wt.data_year DESC;
