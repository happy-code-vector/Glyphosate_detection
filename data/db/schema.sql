-- ResidueIQ SQLite Schema
-- Run once to initialize. Idempotent (safe to re-run).
-- Mirrors Firestore collections for local dev/testing.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ═════════════════════════════════════════════
-- MEASUREMENT TABLES (pipeline-fed)
-- ═════════════════════════════════════════════

-- ─────────────────────────────────────────────
-- Tier 1: Individual product test results
-- Every row is one measurement of one named product.
-- Maps to Firestore: products/{upc} (partial — residue_data array)
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
CREATE INDEX IF NOT EXISTS idx_pt_contaminant     ON product_tests(contaminant);

-- ─────────────────────────────────────────────
-- Tier 2: Category-level aggregate summaries
-- Every row is one aggregate statistic per food category per source.
-- Maps to Firestore: commodities/{slug} (partial — residues array)
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
CREATE INDEX IF NOT EXISTS idx_cs_contaminant     ON category_summaries(contaminant);

-- ─────────────────────────────────────────────
-- Water test results (individual and aggregate)
-- Maps to Firestore: app_water_overview collection
-- ─────────────────────────────────────────────
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

-- ═════════════════════════════════════════════
-- REFERENCE TABLES (pipeline-fed)
-- ═════════════════════════════════════════════

-- ─────────────────────────────────────────────
-- Category map — raw ingredient string → canonical key
-- Maps to Firestore: category_aliases collection
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS category_aliases (
    alias               TEXT PRIMARY KEY,
    canonical_key       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_canonical ON category_aliases(canonical_key);

-- ─────────────────────────────────────────────
-- Unresolved commodity triage log
-- Raw commodity strings the shared resolver could not map to a canonical
-- key. Precision-first: ingest writes 'unknown' + a row here (never the raw
-- string), so taxonomy gaps stay visible and shrinkable instead of silent.
-- Maps to Firestore: unresolved_commodities collection
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS unresolved_commodities (
    raw_category TEXT NOT NULL,
    source       TEXT,
    first_seen   TEXT DEFAULT (datetime('now')),
    hit_count    INTEGER DEFAULT 1,
    PRIMARY KEY (raw_category, source)
);

-- ─────────────────────────────────────────────
-- Regulatory tolerance limits
-- Maps to Firestore: tolerance_limits collection
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
CREATE INDEX IF NOT EXISTS idx_tl_food_category_contaminant ON tolerance_limits(food_category, contaminant);

-- ─────────────────────────────────────────────
-- Biomonitoring data (CDC NHANES)
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
-- Certified products (e.g. Glyphosate Residue Free)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS certified_products (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name        TEXT NOT NULL,
    brand               TEXT,
    food_category       TEXT,
    raw_category        TEXT,
    certification       TEXT DEFAULT 'Glyphosate Residue Free',
    contaminant         TEXT,                           -- 'glyphosate' for GRF, NULL for practice-based certs
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
-- Maps to Firestore: international_mrls collection
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

CREATE INDEX IF NOT EXISTS idx_imrl_food_category ON international_mrls(food_category);
CREATE INDEX IF NOT EXISTS idx_imrl_pesticide ON international_mrls(pesticide);
CREATE INDEX IF NOT EXISTS idx_imrl_pesticide_food_category ON international_mrls(pesticide, food_category);

-- ═════════════════════════════════════════════
-- REGULATORY TABLES (seed data)
-- Maps to Firestore: ingredients, regulatory_flags, commodities, alternatives
-- ═════════════════════════════════════════════

-- ─────────────────────────────────────────────
-- Ingredients: master reference for flagged ingredients
-- Maps to Firestore: ingredients/{ingredient_id}
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ingredients (
    ingredient_id       TEXT PRIMARY KEY,           -- slug: 'red_40', 'potassium_bromate'
    display_name        TEXT NOT NULL,              -- 'Red 40 (Allura Red)'
    contaminant_type    TEXT,                       -- 'pesticide', 'heavy_metal', 'food_dye', 'additive'
    aliases             TEXT,                       -- JSON array of name variants
    flag_types          TEXT,                       -- JSON array of flag_type values
    flags               TEXT,                       -- JSON array of flag detail objects
    ntp_classification  TEXT,                       -- e.g. 'NTP 15th RoC — listed'
    iarc_classification TEXT,                       -- e.g. 'Group 2B' per Addendum A
    fda_status          TEXT,                       -- 'permitted_gras', 'banned_final_rule', 'under_review'
    fda_cfr_citation    TEXT,                       -- e.g. '21 CFR 73.1'
    verified_date       TEXT,                       -- ISO date
    verified_by         TEXT DEFAULT 'AR_Company_internal'
);

-- ─────────────────────────────────────────────
-- Regulatory flags: jurisdiction-specific flag records
-- Maps to Firestore: regulatory_flags/{flag_id}
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS regulatory_flags (
    flag_id             TEXT PRIMARY KEY,
    ingredient_id       TEXT NOT NULL,              -- FK to ingredients.ingredient_id
    contaminant_type    TEXT,                       -- 'pesticide', 'heavy_metal', 'food_dye', 'additive' (denormalized)
    jurisdiction        TEXT NOT NULL,              -- 'EU', 'Canada', 'California', 'US_Federal', 'Japan'
    flag_type           TEXT NOT NULL,              -- 'us_banned', 'eu_banned', 'eu_warning_label', etc.
    regulatory_body     TEXT NOT NULL,              -- 'European Commission', 'FDA', 'OEHHA'
    regulation_citation TEXT,                       -- 'Regulation (EC) No 1333/2008'
    source_url          TEXT NOT NULL,              -- government domain URL
    effective_date      TEXT,
    compliance_date     TEXT,
    notes               TEXT                        -- human-readable for app display
);

CREATE INDEX IF NOT EXISTS idx_rf_ingredient ON regulatory_flags(ingredient_id);
CREATE INDEX IF NOT EXISTS idx_rf_jurisdiction ON regulatory_flags(jurisdiction);
CREATE INDEX IF NOT EXISTS idx_rf_flag_type ON regulatory_flags(flag_type);

-- ─────────────────────────────────────────────
-- Commodities: USDA PDP commodity data + ingredient aliases
-- Maps to Firestore: commodities/{commodity_slug}
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS commodities (
    commodity_slug      TEXT PRIMARY KEY,           -- 'strawberry', 'wheat'
    display_name        TEXT NOT NULL,              -- 'Strawberry'
    ingredient_aliases  TEXT,                       -- JSON array of all alias variants
    pdp_commodity_code  TEXT,                       -- USDA PDP internal code
    pdp_year_latest     INTEGER,
    residues            TEXT,                       -- JSON array of residue data
    dirty_dozen         INTEGER DEFAULT 0,          -- boolean
    pdp_covered         INTEGER DEFAULT 0,          -- boolean: USDA PDP currently tests this commodity (current cycle). Per Addendum B 2.2, grains are NOT in the 2024 PDP rotation.
    last_pdp_update     TEXT,
    consumption_tier    TEXT DEFAULT 'occasional'    -- 'daily', 'weekly', 'occasional', 'rare'
);

-- ─────────────────────────────────────────────
-- plu_codes: IFPS Price Look-Up codes for bulk produce.
-- Produce has no UPC barcode; PLU codes resolve a produce item to a
-- commodity slug -> Layer 2 (USDA PDP) residue data.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS plu_codes (
    plu                 TEXT PRIMARY KEY,           -- '3000' (4-5 digit IFPS code)
    commodity_slug      TEXT,                       -- FK commodities.commodity_slug; NULL for unmapped exotic produce
    commodity_display   TEXT NOT NULL,              -- 'Apples'
    variety             TEXT,                       -- 'Alkmene', 'All Sizes'
    size                TEXT,                       -- 'Small', 'Large', 'All Sizes'
    category            TEXT,                       -- 'Fruits' / 'Vegetables' / 'Herbs' / 'Nuts'
    botanical           TEXT,                       -- 'Malus domestica'
    aka                 TEXT,
    restrictions        TEXT,
    notes               TEXT,
    status              TEXT DEFAULT 'Approved',
    source_file         TEXT,                       -- provenance: 'commodities.csv' | 'NRS' | '2011_innvista'
    dedup_key           TEXT UNIQUE NOT NULL,       -- build_dedup_key('PLU', plu) for idempotent upserts
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_plu_commodity ON plu_codes(commodity_slug);

-- ─────────────────────────────────────────────
-- Alternatives: replacement product suggestions
-- Maps to Firestore: alternatives/{lookup_key}
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alternatives (
    lookup_key          TEXT PRIMARY KEY,           -- UPC or category slug
    lookup_type         TEXT NOT NULL,              -- 'upc' or 'category_slug'
    flagged_product_name TEXT,
    flagged_brand       TEXT,                       -- Brand of the flagged product
    risk_label          TEXT,                       -- 'AVOID', 'CAUTION', 'USE WITH CAUTION'
    flag_summary        TEXT,
    alternatives        TEXT,                       -- JSON array of alternative products
    last_updated        TEXT
);

-- ═════════════════════════════════════════════
-- INFRASTRUCTURE TABLES
-- ═════════════════════════════════════════════

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

-- ═════════════════════════════════════════════
-- APP-FACING VIEWS (multi-contaminant)
-- All views support filtering by contaminant column.
-- ═════════════════════════════════════════════

-- ─────────────────────────────────────────────
-- app_food_overview: One row per food category per contaminant
-- Best-available stats with source priority resolution.
--
-- Two risk signals:
--   risk_level: ppb-vs-tolerance (primary, regulatory-based)
--   detection_frequency: how often detected (secondary, prevalence)
-- ─────────────────────────────────────────────
DROP VIEW IF EXISTS app_food_overview;
CREATE VIEW app_food_overview AS
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
        END AS detection_frequency,
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
        COUNT(DISTINCT pt.product_name) AS total_products_tested,
        COUNT(DISTINCT CASE WHEN pt.below_detection = 0 THEN pt.product_name END) AS products_with_detection,
        ROUND(AVG(pt.measured_ppb), 1) AS avg_product_ppb,
        MAX(pt.measured_ppb) AS max_product_ppb
    FROM product_tests pt
    GROUP BY pt.food_category, pt.contaminant
),
cert_count AS (
    -- Practice-based certs (contaminant IS NULL) apply to all contaminants
    -- Contaminant-specific certs apply only to their contaminant
    SELECT food_category, contaminant, SUM(certified_product_count) AS certified_product_count
    FROM (
        -- Practice-based certs: count once per food_category, join to contaminants later
        SELECT cp.food_category, cs.contaminant, COUNT(*) AS certified_product_count
        FROM certified_products cp
        INNER JOIN (SELECT DISTINCT contaminant FROM category_summaries) cs
        WHERE cp.contaminant IS NULL
        GROUP BY cp.food_category, cs.contaminant
        UNION ALL
        -- Contaminant-specific certs: direct match
        SELECT food_category, contaminant, COUNT(*) AS certified_product_count
        FROM certified_products
        WHERE contaminant IS NOT NULL
        GROUP BY food_category, contaminant
    )
    GROUP BY food_category, contaminant
),
tolerance_data AS (
    SELECT
        food_category,
        contaminant,
        MIN(tolerance_ppb) AS min_tolerance_ppb,
        MIN(source)        AS tolerance_source
    FROM tolerance_limits
    WHERE tolerance_ppb > 0
    GROUP BY food_category, contaminant
),
mrl_data AS (
    SELECT
        food_category,
        pesticide           AS contaminant,
        MIN(mrl_ppb)        AS min_mrl_ppb,
        MIN(regulatory_body) AS mrl_source
    FROM international_mrls
    WHERE mrl_ppb > 0
    GROUP BY food_category, pesticide
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
    -- Primary risk: ppb-vs-tolerance (EPA first, then EFSA MRL fallback)
    CASE
        WHEN bs.max_ppb IS NULL OR bs.max_ppb <= 0 THEN 'none'
        WHEN td.min_tolerance_ppb IS NOT NULL AND td.min_tolerance_ppb > 0 THEN
            CASE
                WHEN bs.max_ppb / td.min_tolerance_ppb >= 2.0 THEN 'high'
                WHEN bs.max_ppb / td.min_tolerance_ppb >= 1.0 THEN 'medium'
                ELSE 'low'
            END
        WHEN md.min_mrl_ppb IS NOT NULL AND md.min_mrl_ppb > 0 THEN
            CASE
                WHEN bs.max_ppb / md.min_mrl_ppb >= 2.0 THEN 'high'
                WHEN bs.max_ppb / md.min_mrl_ppb >= 1.0 THEN 'medium'
                ELSE 'low'
            END
        ELSE 'unknown'
    END AS risk_level,
    bs.detection_frequency,
    bs.confidence,
    COALESCE(ps.total_products_tested, 0)    AS total_products_tested,
    COALESCE(ps.products_with_detection, 0)  AS products_with_detection,
    COALESCE(ps.avg_product_ppb, 0)          AS avg_product_ppb,
    COALESCE(ps.max_product_ppb, 0)          AS max_product_ppb,
    COALESCE(cc.certified_product_count, 0)  AS certified_products_available,
    COALESCE(td.min_tolerance_ppb, md.min_mrl_ppb) AS tolerance_ppb,
    COALESCE(td.tolerance_source, md.mrl_source)   AS tolerance_source
FROM best_summary bs
LEFT JOIN product_stats ps
    ON bs.food_category = ps.food_category
    AND bs.contaminant = ps.contaminant
LEFT JOIN cert_count cc
    ON bs.food_category = cc.food_category
    AND bs.contaminant = cc.contaminant
LEFT JOIN tolerance_data td
    ON bs.food_category = td.food_category
    AND bs.contaminant = td.contaminant
LEFT JOIN mrl_data md
    ON bs.food_category = md.food_category
    AND bs.contaminant = md.contaminant
WHERE bs.rn = 1;

-- ─────────────────────────────────────────────
-- app_product_lookup: Optimized for barcode/name search
-- All individual product results with category context.
-- Uses tolerance_limits for risk_level when available.
-- ─────────────────────────────────────────────
DROP VIEW IF EXISTS app_product_lookup;
CREATE VIEW app_product_lookup AS
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
    pt.updated_at,
    CASE
        WHEN pt.is_grf_certified = 1 THEN 'certified_grf'
        WHEN pt.is_organic = 1 AND pt.below_detection = 1 THEN 'organic_clean'
        WHEN pt.is_organic = 1 THEN 'organic_detected'
        WHEN pt.below_detection = 1 THEN 'none'
        WHEN pt.measured_ppb IS NULL OR pt.measured_ppb <= 0 THEN 'none'
        WHEN td.min_tolerance_ppb IS NOT NULL AND td.min_tolerance_ppb > 0 THEN
            CASE
                WHEN pt.measured_ppb / td.min_tolerance_ppb >= 2.0 THEN 'high'
                WHEN pt.measured_ppb / td.min_tolerance_ppb >= 1.0 THEN 'medium'
                ELSE 'low'
            END
        ELSE 'unknown'
    END AS risk_level
FROM product_tests pt
LEFT JOIN (
    SELECT food_category, contaminant, MIN(tolerance_ppb) AS min_tolerance_ppb
    FROM tolerance_limits WHERE tolerance_ppb > 0
    GROUP BY food_category, contaminant
) td ON pt.food_category = td.food_category AND pt.contaminant = td.contaminant
ORDER BY pt.contaminant, pt.food_category, pt.product_name;

-- ─────────────────────────────────────────────
-- app_regulatory_limits: Detection vs. legal limits
-- Shows how detection levels compare to legal limits.
-- ─────────────────────────────────────────────
DROP VIEW IF EXISTS app_regulatory_limits;
CREATE VIEW app_regulatory_limits AS
SELECT
    cs.contaminant,
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
ORDER BY cs.contaminant, cs.food_category, cs.data_year DESC;

-- ─────────────────────────────────────────────
-- app_international_comparison: Side-by-side MRL comparison
-- Compare regulatory limits across countries.
-- ─────────────────────────────────────────────
DROP VIEW IF EXISTS app_international_comparison;
CREATE VIEW app_international_comparison AS
SELECT
    im.pesticide            AS contaminant,
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
    AND cs.contaminant = im.pesticide
ORDER BY im.pesticide, im.food_category, im.mrl_ppb ASC;

-- ─────────────────────────────────────────────
-- app_water_overview: Aggregated water stats by state
-- ─────────────────────────────────────────────
DROP VIEW IF EXISTS app_water_overview;
CREATE VIEW app_water_overview AS
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
