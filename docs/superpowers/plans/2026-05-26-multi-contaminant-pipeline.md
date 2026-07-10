# Multi-Contaminant Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the data pipeline from glyphosate-only to support glyphosate, lead, and atrazine across food, water, regulatory, and biomonitoring data.

**Architecture:** Add a `contaminant` column (default `'glyphosate'`) to all core tables. Create a contaminant registry module. Refactor multi-chemical fetchers (USGS WQP, USDA PDP) to run once per contaminant. Keep existing views backward-compatible via `WHERE contaminant = 'glyphosate'`.

**Tech Stack:** Python 3, SQLite, pandas, requests

---

### Task 1: Contaminant Registry

**Files:**
- Create: `data/contaminants.py`

- [ ] **Step 1: Create `data/contaminants.py`**

```python
"""
contaminants.py
Registry of supported contaminants with source-specific lookup keys.
"""

CONTAMINANTS = {
    "glyphosate": {
        "type": "pesticide",
        "cas_number": "1071-83-6",
        "wqp_characteristic": "Glyphosate",
        "pdp_codes": [653],
        "pdp_exclude_codes": [957],  # AMPA metabolite
        "fda_resname": "GLYPHOSATE",
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "water_standards": [
            {
                "source": "EPA_MCL",
                "tolerance_ppm": 0.7,
                "tolerance_ppb": 700.0,
                "regulation_reference": "40 CFR 141.60 — National Primary Drinking Water Regulation",
            },
            {
                "source": "EU_DWD",
                "tolerance_ppm": 0.0001,
                "tolerance_ppb": 0.1,
                "regulation_reference": "EU Drinking Water Directive 2020/2184 — individual pesticide limit",
            },
            {
                "source": "Health_Canada",
                "tolerance_ppm": 0.28,
                "tolerance_ppb": 280.0,
                "regulation_reference": "Health Canada Guidelines for Canadian Drinking Water Quality",
            },
        ],
    },
    "lead": {
        "type": "heavy_metal",
        "cas_number": "7439-92-1",
        "wqp_characteristic": "Lead",
        "pdp_codes": [],
        "fda_search": "Lead",
        "units": "ppb",
        "risk_thresholds": {"high": 15, "medium": 5, "low": 0},
        "water_standards": [
            {
                "source": "EPA_MCL",
                "tolerance_ppm": 0.015,
                "tolerance_ppb": 15.0,
                "regulation_reference": "40 CFR 141.80 — Lead and Copper Rule, action level",
            },
            {
                "source": "EU_DWD",
                "tolerance_ppm": 0.005,
                "tolerance_ppb": 5.0,
                "regulation_reference": "EU Drinking Water Directive 2020/2184 — lead limit",
            },
            {
                "source": "Health_Canada",
                "tolerance_ppm": 0.01,
                "tolerance_ppb": 10.0,
                "regulation_reference": "Health Canada Guidelines for Canadian Drinking Water Quality — lead MAC",
            },
        ],
    },
    "atrazine": {
        "type": "pesticide",
        "cas_number": "1912-24-9",
        "wqp_characteristic": "Atrazine",
        "pdp_codes": [],
        "fda_resname": "ATRAZINE",
        "units": "ppb",
        "risk_thresholds": {"high": 3, "medium": 1, "low": 0},
        "water_standards": [
            {
                "source": "EPA_MCL",
                "tolerance_ppm": 0.003,
                "tolerance_ppb": 3.0,
                "regulation_reference": "40 CFR 141.61 — National Primary Drinking Water Regulation, atrazine",
            },
            {
                "source": "EU_DWD",
                "tolerance_ppm": 0.0001,
                "tolerance_ppb": 0.1,
                "regulation_reference": "EU Drinking Water Directive 2020/2184 — individual pesticide limit",
            },
            {
                "source": "Health_Canada",
                "tolerance_ppm": 0.005,
                "tolerance_ppb": 5.0,
                "regulation_reference": "Health Canada Guidelines for Canadian Drinking Water Quality — atrazine MAC",
            },
        ],
    },
}

# All contaminant keys in canonical order
CONTAMINANT_KEYS = list(CONTAMINANTS.keys())


def get_contaminant_config(key: str) -> dict:
    """Get config dict for a contaminant. Raises KeyError if unknown."""
    return CONTAMINANTS[key]


def get_risk_level(contaminant: str, ppb: float) -> str:
    """Classify a measurement into risk level based on contaminant thresholds."""
    if ppb is None or ppb <= 0:
        return "none"
    thresholds = CONTAMINANTS[contaminant]["risk_thresholds"]
    if ppb >= thresholds["high"]:
        return "high"
    if ppb >= thresholds["medium"]:
        return "medium"
    return "low"
```

- [ ] **Step 2: Verify the module loads**

Run: `cd "F:\Projects\Arasheed\Glyphosate Detection\data" && python -c "from contaminants import CONTAMINANTS, CONTAMINANT_KEYS; print('Contaminants:', CONTAMINANT_KEYS)"`

Expected: `Contaminants: ['glyphosate', 'lead', 'atrazine']`

- [ ] **Step 3: Commit**

```bash
git add data/contaminants.py
git commit -m "feat: add contaminant registry for glyphosate, lead, atrazine"
```

---

### Task 2: Schema — Add `contaminant` Column + Update Views

**Files:**
- Modify: `data/db/schema.sql`

This is the foundation. The schema must add the `contaminant` column to all data tables, update every existing view to filter `WHERE contaminant = 'glyphosate'`, and add new multi-contaminant views.

- [ ] **Step 1: Add `contaminant` column to `product_tests` table**

In `data/db/schema.sql`, inside the `CREATE TABLE IF NOT EXISTS product_tests` block, add after the `raw_category` line (line 23):

```sql
    contaminant        TEXT    NOT NULL DEFAULT 'glyphosate',
```

Add index after the existing product_tests indexes (after line 54):

```sql
CREATE INDEX IF NOT EXISTS idx_pt_contaminant  ON product_tests(contaminant);
```

- [ ] **Step 2: Add `contaminant` column to `category_summaries` table**

In `category_summaries` CREATE TABLE, add after the `raw_category` line:

```sql
    contaminant        TEXT    NOT NULL DEFAULT 'glyphosate',
```

Add index:

```sql
CREATE INDEX IF NOT EXISTS idx_cs_contaminant  ON category_summaries(contaminant);
```

- [ ] **Step 3: Add `contaminant` column to `water_tests` table**

In `water_tests` CREATE TABLE, add after `water_type TEXT NOT NULL`:

```sql
    contaminant        TEXT    NOT NULL DEFAULT 'glyphosate',
```

Add index:

```sql
CREATE INDEX IF NOT EXISTS idx_wt_contaminant  ON water_tests(contaminant);
```

- [ ] **Step 4: Add `contaminant` column to `tolerance_limits` table**

In `tolerance_limits` CREATE TABLE, add after `tolerance_ppb REAL NOT NULL`:

```sql
    contaminant        TEXT    NOT NULL DEFAULT 'glyphosate',
```

Add index:

```sql
CREATE INDEX IF NOT EXISTS idx_tl_contaminant  ON tolerance_limits(contaminant);
```

- [ ] **Step 5: Update the backward-compat `glyphosate_measurements` view**

Replace the existing view (lines 112-133) to add `contaminant` and the filter:

```sql
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
```

- [ ] **Step 6: Update `category_risk` view**

Add `WHERE cs.contaminant = 'glyphosate'` to the outer query:

```sql
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
    SELECT cs2.food_category FROM category_summaries cs2
    WHERE cs2.contaminant = 'glyphosate'
    GROUP BY cs2.food_category
    HAVING MAX(
        CASE cs2.source_name
            WHEN 'consumer_reports' THEN 4
            WHEN 'FDA' THEN 3
            WHEN 'CFIA' THEN 2
            WHEN 'EFSA' THEN 1
            ELSE 0
        END
    )
);
```

- [ ] **Step 7: Update `product_results` view**

```sql
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
```

- [ ] **Step 8: Update `app_food_overview` view**

Add `WHERE cs.contaminant = 'glyphosate'` to the `best_summary` CTE and the final query:

```sql
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
                    WHEN 'consumer_reports' THEN 4
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
```

- [ ] **Step 9: Update `app_product_lookup` view**

```sql
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
```

- [ ] **Step 10: Update `app_regulatory_limits` view**

```sql
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
```

- [ ] **Step 11: Update `app_international_comparison` view**

```sql
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
```

- [ ] **Step 12: Update `app_water_overview` view**

```sql
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
    ON tl.food_category = 'drinking_water'
    AND tl.source = 'EPA_MCL'
    AND tl.contaminant = wt.contaminant
WHERE wt.is_aggregate = 1
  AND wt.contaminant = 'glyphosate'
ORDER BY wt.state, wt.water_type, wt.data_year DESC;
```

- [ ] **Step 13: Add new multi-contaminant views**

Append after `app_water_overview` in `schema.sql`:

```sql
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
                    WHEN 'consumer_reports' THEN 4
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
```

- [ ] **Step 14: Verify schema loads without errors**

Run: `cd "F:\Projects\Arasheed\Glyphosate Detection\data" && python -c "import sqlite3; conn = sqlite3.connect(':memory:'); conn.executescript(open('db/schema.sql', encoding='utf-8').read()); print('Schema OK')"`

Expected: `Schema OK`

- [ ] **Step 15: Commit**

```bash
git add data/db/schema.sql
git commit -m "feat: add contaminant column to schema, update views for multi-contaminant support"
```

---

### Task 3: Database Module — Migration + Insert Functions

**Files:**
- Modify: `data/db/database.py`

- [ ] **Step 1: Add `_migrate_add_contaminant_column` function**

Add this function before `_migrate_legacy` in `data/db/database.py`:

```python
def _migrate_add_contaminant_column(conn):
    """Add contaminant column to existing tables if missing."""
    tables_to_migrate = [
        "product_tests",
        "category_summaries",
        "water_tests",
        "tolerance_limits",
    ]
    for table in tables_to_migrate:
        # Check if column already exists
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        col_names = [c[1] for c in cols]
        if "contaminant" not in col_names:
            logger.info("Adding contaminant column to %s", table)
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN contaminant TEXT NOT NULL DEFAULT 'glyphosate'"
            )
    # Rebuild views to pick up the new column
    conn.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
    logger.info("Contaminant column migration complete")
```

- [ ] **Step 2: Call the migration from `initialize()`**

Update the `initialize()` function to call the new migration:

```python
def initialize():
    """Create all tables. Safe to call on every run — idempotent."""
    with get_connection() as conn:
        _migrate_legacy(conn)
        conn.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
        _migrate_add_contaminant_column(conn)
        _seed_category_aliases(conn)
    logger.info("Database initialized at %s", DB_PATH)
```

- [ ] **Step 3: Update `_insert_product` to include `contaminant`**

Update the `_insert_product` function. Add `"contaminant": "glyphosate"` to the defaults dict and add `:contaminant` to the SQL:

```python
def _insert_product(conn, row: dict) -> int:
    """Insert a Tier 1 product test row."""
    defaults = {
        "contaminant": "glyphosate",
        "measured_ppb": None, "below_detection": 0, "limit_of_detection": None,
        "original_unit": "ppb", "unit_conversion": 1.0,
        "is_organic": 0, "is_grf_certified": 0,
        "methodology_note": None, "raw_file_path": None,
    }
    r = {**defaults, **row}
    conn.execute("""
        INSERT OR IGNORE INTO product_tests (
            source_name, source_url, report_label, published_date, data_year,
            food_category, raw_category, contaminant, product_name,
            measured_ppb, below_detection, limit_of_detection,
            original_unit, unit_conversion, is_organic, is_grf_certified,
            methodology_note, confidence, dedup_key, raw_file_path
        ) VALUES (
            :source_name, :source_url, :report_label, :published_date, :data_year,
            :food_category, :raw_category, :contaminant, :product_name,
            :measured_ppb, :below_detection, :limit_of_detection,
            :original_unit, :unit_conversion, :is_organic, :is_grf_certified,
            :methodology_note, :confidence, :dedup_key, :raw_file_path
        )
    """, r)
    return conn.execute("SELECT changes()").fetchone()[0]
```

- [ ] **Step 4: Update `_insert_category` to include `contaminant`**

```python
def _insert_category(conn, row: dict) -> int:
    """Insert a Tier 2 category summary row."""
    defaults = {
        "contaminant": "glyphosate",
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
            food_category, raw_category, contaminant,
            samples_total, samples_detected, detection_rate, avg_ppb, max_ppb, p95_ppb,
            median_ppb, min_ppb,
            original_unit, unit_conversion, is_organic,
            methodology_note, confidence, dedup_key, raw_file_path
        ) VALUES (
            :source_name, :source_url, :report_label, :published_date, :data_year,
            :food_category, :raw_category, :contaminant,
            :samples_total, :samples_detected, :detection_rate, :avg_ppb, :max_ppb, :p95_ppb,
            :median_ppb, :min_ppb,
            :original_unit, :unit_conversion, :is_organic,
            :methodology_note, :confidence, :dedup_key, :raw_file_path
        )
    """, r)
    return conn.execute("SELECT changes()").fetchone()[0]
```

- [ ] **Step 5: Update `_insert_water` to include `contaminant`**

```python
def _insert_water(conn, row: dict) -> int:
    """Insert a water_tests row."""
    defaults = {
        "contaminant": "glyphosate",
        "state": None, "county": None, "site_type": None, "site_id": None,
        "latitude": None, "longitude": None,
        "measured_ppb": None, "below_detection": 0, "detection_limit_ppb": None,
        "analytical_method": None, "sample_date": None,
        "is_aggregate": 0, "samples_total": None, "samples_detected": None,
        "detection_rate": None, "avg_ppb": None, "max_ppb": None,
        "methodology_note": None, "confidence": None,
    }
    r = {**defaults, **row}
    conn.execute("""
        INSERT OR IGNORE INTO water_tests (
            source_name, source_url, report_label, data_year,
            contaminant,
            state, county, site_type, site_id, latitude, longitude,
            water_type, measured_ppb, below_detection, detection_limit_ppb,
            analytical_method, sample_date, is_aggregate,
            samples_total, samples_detected, detection_rate, avg_ppb, max_ppb,
            methodology_note, confidence, dedup_key
        ) VALUES (
            :source_name, :source_url, :report_label, :data_year,
            :contaminant,
            :state, :county, :site_type, :site_id, :latitude, :longitude,
            :water_type, :measured_ppb, :below_detection, :detection_limit_ppb,
            :analytical_method, :sample_date, :is_aggregate,
            :samples_total, :samples_detected, :detection_rate, :avg_ppb, :max_ppb,
            :methodology_note, :confidence, :dedup_key
        )
    """, r)
    return conn.execute("SELECT changes()").fetchone()[0]
```

- [ ] **Step 6: Verify database module loads and initializes**

Run: `cd "F:\Projects\Arasheed\Glyphosate Detection\data" && python -c "from db.database import initialize; initialize(); print('DB initialized OK')"`

Expected: `DB initialized OK` with no errors.

- [ ] **Step 7: Commit**

```bash
git add data/db/database.py
git commit -m "feat: add contaminant column to database insert functions and migration"
```

---

### Task 4: Water Quality Fetcher — Multi-Contaminant Refactor

**Files:**
- Modify: `data/fetchers/water_quality.py`

This is the key fetcher. It needs to accept a contaminant parameter, build dynamic WQP queries, and store per-contaminant regulatory standards.

- [ ] **Step 1: Rewrite `water_quality.py`**

Replace the entire file with:

```python
"""
fetchers/water_quality.py

Multi-contaminant water monitoring data from USGS Water Quality Portal and EPA UCMR.

Supported contaminants: glyphosate, lead, atrazine.
Each is queried separately from USGS WQP with contaminant-specific parameters.

Sources:
  1. USGS WQP — surface water + groundwater detections nationwide
     API: https://waterqualitydata.us/data/Result/search
  2. EPA UCMR 3 — drinking water data (2013-2015)
     URL: https://www.epa.gov/dwucmr/occurrence-data-unregulated-contaminant-monitoring-rule
  3. Drinking water regulatory standards (EPA MCL, EU DWD, Health Canada)

All values stored as ppb (ug/L).
"""

import logging
from pathlib import Path

import pandas as pd

from fetchers.base import BaseFetcher, SESSION, RAW_DATA_DIR
from db.database import build_dedup_key, get_connection
from contaminants import get_contaminant_config, CONTAMINANTS

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# USGS Water Quality Portal
# ─────────────────────────────────────────────────────────────────────
WQP_BASE_URL = "https://www.waterqualitydata.us/data/Result/search"

# Site type → water_type mapping
_SITE_TYPE_MAP = {
    "Stream": "surface",
    "River/Stream": "surface",
    "Lake": "surface",
    "Reservoir": "surface",
    "Estuary": "surface",
    "Ocean": "surface",
    "Well": "groundwater",
    "Spring": "groundwater",
    "Land": "groundwater",
    "Atmosphere": "surface",
}

# UCMR 3 ZIP (only contains lead-relevant data for our purposes)
UCMR3_ZIP_URL = (
    "https://www.epa.gov/system/files/documents/2024-02/"
    "ucmr-3-occurrence-data.zip"
)
UCMR3_ZIP_FILENAME = "ucmr3_occurrence_data.zip"
UCMR3_FILENAME = "ucmr3_all.txt"


def _map_site_type(raw: str) -> str:
    """Map WQP site type to our water_type."""
    if not raw or raw.lower() == "nan":
        return "surface"
    for key, mapped in _SITE_TYPE_MAP.items():
        if key.lower() in raw.lower():
            return mapped
    return "surface"


class WaterQualityFetcher(BaseFetcher):
    SOURCE_NAME = "Water_Quality"

    def __init__(self, contaminant: str = "glyphosate"):
        if contaminant not in CONTAMINANTS:
            raise ValueError(f"Unknown contaminant: {contaminant}")
        self.contaminant = contaminant
        self.config = get_contaminant_config(contaminant)
        self.wqp_filename = f"wqp_{contaminant}_water.csv"

    def run(self) -> dict:
        """Fetch + parse + insert. Also seeds drinking water standards."""
        from db.database import insert_rows, log_ingest
        logger.info("=== Starting %s pipeline (contaminant=%s) ===",
                     self.SOURCE_NAME, self.contaminant)

        self._seed_standards_direct()

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

        logger.info("%s (%s) parsed %d rows, inserting...",
                     self.SOURCE_NAME, self.contaminant, len(rows))
        counts = insert_rows(rows, f"{self.SOURCE_NAME}_{self.contaminant}", str(files))
        logger.info(
            "%s (%s) complete: inserted=%d skipped=%d failed=%d",
            self.SOURCE_NAME, self.contaminant,
            counts["inserted"], counts["skipped"], counts["failed"]
        )
        return counts

    def _seed_standards_direct(self):
        """Insert drinking water regulatory standards into tolerance_limits."""
        with get_connection() as conn:
            for std in self.config["water_standards"]:
                dedup = build_dedup_key(
                    self.contaminant, std["source"], "drinking_water"
                )
                conn.execute("""
                    INSERT OR IGNORE INTO tolerance_limits (
                        food_category, raw_commodity, tolerance_ppm, tolerance_ppb,
                        source, regulation_reference, contaminant, dedup_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    "drinking_water", "drinking_water",
                    std["tolerance_ppm"], std["tolerance_ppb"],
                    std["source"], std["regulation_reference"],
                    self.contaminant, dedup,
                ))
        logger.info("Seeded %s drinking water standards", self.contaminant)

    def fetch(self) -> list[Path]:
        paths = []
        wqp_path = self._fetch_wqp()
        if wqp_path:
            paths.append(wqp_path)
        return paths

    def _fetch_wqp(self) -> Path | None:
        """Download water data from Water Quality Portal for this contaminant."""
        cache_path = RAW_DATA_DIR / self.wqp_filename
        if cache_path.exists():
            logger.info("Cache hit: %s", self.wqp_filename)
            return cache_path

        params = {
            "characteristicName": self.config["wqp_characteristic"],
            "sampleMedia": "Water",
            "mimeType": "csv",
            "sorted": "no",
            "providers": "STORET,NWIS",
        }

        try:
            logger.info("Downloading USGS WQP %s water data...", self.contaminant)
            resp = SESSION.get(WQP_BASE_URL, params=params, timeout=300)
            resp.raise_for_status()

            if len(resp.content) < 100:
                logger.warning("WQP returned very little data for %s", self.contaminant)
                return None

            cache_path.write_bytes(resp.content)
            logger.info("WQP %s download: %d bytes", self.contaminant, len(resp.content))
            return cache_path
        except Exception as e:
            logger.error("WQP %s download failed: %s", self.contaminant, e)
            return None

    def parse(self, files: list[Path]) -> list[dict]:
        all_rows = []
        file_map = {f.name: f for f in files}
        wqp_path = file_map.get(self.wqp_filename)
        if wqp_path:
            all_rows.extend(self._parse_wqp(wqp_path))
        return all_rows

    def _parse_wqp(self, csv_path: Path) -> list[dict]:
        """Parse WQP CSV water data for this contaminant."""
        try:
            df = pd.read_csv(csv_path, low_memory=False)
        except Exception as e:
            logger.error("WQP CSV parse failed for %s: %s", self.contaminant, e)
            return []

        logger.info("WQP %s: %d rows, columns: %s",
                     self.contaminant, len(df), list(df.columns)[:15])

        df.columns = [c.strip() for c in df.columns]

        # Find key columns
        result_col = next(
            (c for c in df.columns if c.lower() in ("resultmeasurevalue", "resultmeasure/value")),
            None,
        )
        unit_col = next(
            (c for c in df.columns if "measureunitcode" in c.lower() or "measure/unitcode" in c.lower()),
            None,
        )
        date_col = next(
            (c for c in df.columns if "activitystartdate" in c.lower()),
            None,
        )
        site_type_col = next(
            (c for c in df.columns if "sitetype" in c.lower() or "ActivityMediaName" in c),
            None,
        )
        lat_col = next((c for c in df.columns if c.lower() == "latitudemeasure"), None)
        lon_col = next((c for c in df.columns if c.lower() == "longitudemeasure"), None)
        site_id_col = next(
            (c for c in df.columns if "monitoringlocationidentifier" in c.lower()), None,
        )
        char_col = next(
            (c for c in df.columns if "characteristicname" in c.lower()), None,
        )
        detection_col = next(
            (c for c in df.columns if "resultdetectioncondition" in c.lower()),
            None,
        )
        method_col = next(
            (c for c in df.columns if "resultanalyticalmethod/methodname" in c.lower()),
            None,
        )
        provider_col = next(
            (c for c in df.columns if "providername" in c.lower()), None,
        )

        if not result_col:
            logger.error("WQP %s: no result column found", self.contaminant)
            return []

        # Filter for this contaminant only (exclude metabolites)
        data = df.copy()
        if char_col:
            contam_name = self.config["wqp_characteristic"].lower()
            data = data[
                data[char_col].str.lower().str.contains(contam_name, na=False)
            ].copy()

        if data.empty:
            logger.warning("WQP %s: no rows found", self.contaminant)
            return []

        logger.info("WQP %s: %d result rows", self.contaminant, len(data))

        # Determine year
        if date_col:
            data["_year"] = pd.to_datetime(data[date_col], errors="coerce").dt.year
            data = data[data["_year"].notna() & (data["_year"] >= 1970)].copy()
        else:
            data["_year"] = None

        # Parse result values
        data["_ppb"] = pd.to_numeric(data[result_col], errors="coerce")

        # Unit conversion: mg/L → ppb (× 1000), ug/L → ppb (× 1)
        if unit_col:
            data["_unit"] = data[unit_col].fillna("").astype(str).str.lower().str.strip()
        else:
            data["_unit"] = "ug/l"
        data["_conversion"] = data["_unit"].apply(
            lambda u: 1000.0 if "mg/l" in str(u) else 1.0
        )
        data["_ppb"] = data["_ppb"] * data["_conversion"]

        # Detect below-detection
        data["_below_det"] = False
        if detection_col:
            data["_below_det"] = data[detection_col].astype(str).str.lower().str.contains(
                "below|not detected|nd|non-detect", na=False
            )

        # Map water type
        if site_type_col:
            data["_water_type"] = data[site_type_col].apply(_map_site_type)
        else:
            data["_water_type"] = "surface"

        # ── Build rows ──────────────────────────────────────────────
        rows = []
        agg_groups = data.groupby(["_water_type", "_year"], dropna=False)

        for (wtype, year), group in agg_groups:
            year_clean = int(year) if pd.notna(year) else 0
            wtype_clean = str(wtype)

            detected = group[~group["_below_det"] & group["_ppb"].notna()]
            total = len(group)
            n_detected = len(detected)
            detection_rate = round(n_detected / total, 4) if total > 0 else 0
            avg_ppb = round(detected["_ppb"].mean(), 2) if len(detected) > 0 else None
            max_ppb = round(detected["_ppb"].max(), 2) if len(detected) > 0 else None

            rows.append({
                "table": "water",
                "contaminant": self.contaminant,
                "source_name": "USGS_WQP",
                "source_url": "https://waterqualitydata.us",
                "report_label": f"USGS WQP {self.contaminant.title()} Water {year_clean}",
                "data_year": year_clean,
                "state": "National",
                "water_type": wtype_clean,
                "is_aggregate": 1,
                "samples_total": total,
                "samples_detected": n_detected,
                "detection_rate": detection_rate,
                "avg_ppb": avg_ppb,
                "max_ppb": max_ppb,
                "methodology_note": (
                    f"USGS Water Quality Portal aggregate. "
                    f"{total} water samples for {self.contaminant} "
                    f"({wtype_clean}), {year_clean}. Units: ug/L (ppb)."
                ),
                "confidence": "high",
                "dedup_key": build_dedup_key(
                    self.contaminant, "USGS_WQP", wtype_clean, year_clean
                ),
            })

        logger.info("WQP %s: parsed %d aggregate rows", self.contaminant, len(rows))
        return rows
```

- [ ] **Step 2: Verify water quality module loads**

Run: `cd "F:\Projects\Arasheed\Glyphosate Detection\data" && python -c "from fetchers.water_quality import WaterQualityFetcher; f = WaterQualityFetcher('lead'); print('Lead fetcher OK, characteristic:', f.config['wqp_characteristic'])"`

Expected: `Lead fetcher OK, characteristic: Lead`

- [ ] **Step 3: Commit**

```bash
git add data/fetchers/water_quality.py
git commit -m "feat: refactor water quality fetcher for multi-contaminant support"
```

---

### Task 5: Update Existing Fetchers — Pass Contaminant Through

**Files:**
- Modify: `data/fetchers/detox_project.py`
- Modify: `data/fetchers/florida_hff.py`
- Modify: `data/fetchers/sources.py` (CFIA, EFSA, FDA)
- Modify: `data/fetchers/usda_pdp.py`
- Modify: `data/fetchers/uk_fsa.py`
- Modify: `data/fetchers/ca_dpr.py`
- Modify: `data/fetchers/germany_bvl.py`
- Modify: `data/fetchers/epa_tolerances.py`
- Modify: `data/fetchers/australia_fsnz.py`
- Modify: `data/fetchers/codex_mrls.py`
- Modify: `data/fetchers/japan_brazil_mrls.py`
- Modify: `data/fetchers/academic_papers.py`
- Modify: `data/fetchers/detox_project.py`
- Modify: `data/fetchers/cdc_nhanes.py`
- Modify: `data/fetchers/clean_label_project.py`
- Modify: `data/fetchers/consumer_reports.py`
- Modify: `data/fetchers/detox_certifications.py`
- Modify: `data/fetchers/epa_full_tolerances.py`
- Modify: `data/fetchers/usda_fas_mrls.py`

All existing fetchers produce glyphosate data. Since the database defaults `contaminant` to `'glyphosate'`, the minimal change is to ensure every row dict includes `"contaminant": "glyphosate"`. This is already handled by the defaults in `database.py` — no code changes needed in individual fetchers.

However, to be explicit and future-proof, add `CONTAMINANT = "glyphosate"` as a class attribute to `BaseFetcher`.

- [ ] **Step 1: Add `CONTAMINANT` to BaseFetcher in `data/fetchers/base.py`**

Add to the `BaseFetcher` class, after `SOURCE_NAME`:

```python
class BaseFetcher(ABC):
    SOURCE_NAME: str = ""
    CONTAMINANT: str = "glyphosate"
```

- [ ] **Step 2: Verify base class works**

Run: `cd "F:\Projects\Arasheed\Glyphosate Detection\data" && python -c "from fetchers.base import BaseFetcher; print('CONTAMINANT:', BaseFetcher.CONTAMINANT)"`

Expected: `CONTAMINANT: glyphosate`

- [ ] **Step 3: Commit**

```bash
git add data/fetchers/base.py
git commit -m "feat: add CONTAMINANT attribute to BaseFetcher"
```

---

### Task 6: Pipeline Runner — Multi-Contaminant Support

**Files:**
- Modify: `data/run_pipeline.py`

- [ ] **Step 1: Update `run_pipeline.py` to run water quality for all contaminants**

In `run_all()`, change the `sources` list entry for water_quality from a single tuple to a loop. Replace the existing `("water_quality", WaterQualityFetcher)` entry and add logic after the main loop:

Update the `--source` help text to include contaminant variants:

```python
parser.add_argument("--source", help="Run only this source: florida/cfia/efsa/fda/usda_pdp/uk_fsa/ca_dpr/germany_bvl/epa_tolerances/australia_fsnz/codex_mrls/japan_brazil_mrls/academic_papers/detox_project/cdc_nhanes/clean_label_project/consumer_reports/detox_certifications/epa_full_tolerances/usda_fas_mrls/water_quality_glyphosate/water_quality_lead/water_quality_atrazine")
```

Replace the water_quality entry in the `sources` list with three entries:

```python
    sources = [
        ("cfia",                    CFIAFetcher),
        ("efsa",                    EFSAFetcher),
        ("fda",                     FDAFetcher),
        ("florida",                 FloridaHFFFetcher),
        ("usda_pdp",                USDA_PDPFetcher),
        ("uk_fsa",                  UKFSAFetcher),
        ("ca_dpr",                  CADPRFetcher),
        ("germany_bvl",             GermanyBVLFetcher),
        ("epa_tolerances",          EPATolerancesFetcher),
        ("australia_fsnz",          AustraliaFSANZFetcher),
        ("codex_mrls",              CodexMRLsFetcher),
        ("japan_brazil_mrls",       JapanBrazilMRLFetcher),
        ("academic_papers",         AcademicPapersFetcher),
        ("detox_project",           DetoxProjectFetcher),
        ("cdc_nhanes",              CDC_NHANESFetcher),
        ("clean_label_project",     CleanLabelProjectFetcher),
        ("consumer_reports",        ConsumerReportsFetcher),
        ("detox_certifications",    DetoxCertificationsFetcher),
        ("epa_full_tolerances",     EPAFullTolerancesFetcher),
        ("usda_fas_mrls",           USDAFASMRLFetcher),
        ("water_quality_glyphosate", lambda: WaterQualityFetcher("glyphosate")),
        ("water_quality_lead",      lambda: WaterQualityFetcher("lead")),
        ("water_quality_atrazine",  lambda: WaterQualityFetcher("atrazine")),
    ]
```

Update the runner loop to handle both classes and callables (lambdas), and support the generic `--source water_quality` flag:

```python
    for name, FetcherFactory in sources:
        if args.source and args.source != name:
            # Allow "water_quality" to match all three water_quality_* sources
            if args.source == "water_quality" and name.startswith("water_quality_"):
                pass
            else:
                continue
        logger.info("-" * 60)
        try:
            # FetcherFactory is either a class (callable type) or a lambda (callable non-type)
            fetcher = FetcherFactory()
            counts = fetcher.run()
            for k in totals:
                totals[k] += counts.get(k, 0)
        except Exception as e:
            logger.error("Source %s failed: %s", name, e, exc_info=True)
            errors.append((name, str(e)))
```

- [ ] **Step 2: Verify pipeline runner loads**

Run: `cd "F:\Projects\Arasheed\Glyphosate Detection\data" && python run_pipeline.py --help`

Expected: Help text showing all sources including `water_quality_glyphosate`, `water_quality_lead`, `water_quality_atrazine`.

- [ ] **Step 3: Commit**

```bash
git add data/run_pipeline.py
git commit -m "feat: run water quality fetcher for glyphosate, lead, and atrazine"
```

---

### Task 7: End-to-End Validation

**Files:** None (validation only)

- [ ] **Step 1: Delete existing database and run fresh pipeline**

```bash
cd "F:\Projects\Arasheed\Glyphosate Detection\data"
del residueiq.db
python run_pipeline.py
```

Expected: All sources run. Water quality runs 3 times (glyphosate, lead, atrazine). Pipeline completes with no errors.

- [ ] **Step 2: Validate contaminant data is distinct**

Run:
```bash
python -c "
import sqlite3
conn = sqlite3.connect('residueiq.db')
print('=== product_tests by contaminant ===')
for row in conn.execute('SELECT contaminant, COUNT(*) FROM product_tests GROUP BY contaminant'):
    print(f'  {row[0]}: {row[1]} rows')
print()
print('=== category_summaries by contaminant ===')
for row in conn.execute('SELECT contaminant, COUNT(*) FROM category_summaries GROUP BY contaminant'):
    print(f'  {row[0]}: {row[1]} rows')
print()
print('=== water_tests by contaminant ===')
for row in conn.execute('SELECT contaminant, COUNT(*) FROM water_tests GROUP BY contaminant'):
    print(f'  {row[0]}: {row[1]} rows')
print()
print('=== tolerance_limits by contaminant ===')
for row in conn.execute('SELECT contaminant, COUNT(*) FROM tolerance_limits GROUP BY contaminant'):
    print(f'  {row[0]}: {row[1]} rows')
print()
print('=== app_food_overview_all (multi-contaminant) ===')
for row in conn.execute('SELECT contaminant, COUNT(*) FROM app_food_overview_all GROUP BY contaminant'):
    print(f'  {row[0]}: {row[1]} rows')
print()
print('=== app_water_overview_all (multi-contaminant) ===')
for row in conn.execute('SELECT contaminant, COUNT(*) FROM app_water_overview_all GROUP BY contaminant'):
    print(f'  {row[0]}: {row[1]} rows')
"
```

Expected:
- Glyphosate data in all tables (existing sources)
- Lead data in `water_tests` and `tolerance_limits`
- Atrazine data in `water_tests` and `tolerance_limits`
- Legacy views (`app_food_overview`, `app_water_overview`) show glyphosate-only data
- New views (`app_food_overview_all`, `app_water_overview_all`) show multi-contaminant data

- [ ] **Step 3: Validate backward-compatible views are unchanged**

Run:
```bash
python -c "
import sqlite3
conn = sqlite3.connect('residueiq.db')
print('=== glyphosate_measurements (legacy view) ===')
for row in conn.execute('SELECT COUNT(*) FROM glyphosate_measurements'):
    print(f'  {row[0]} rows')
print()
print('=== app_food_overview (glyphosate-only) ===')
for row in conn.execute('SELECT COUNT(*) FROM app_food_overview'):
    print(f'  {row[0]} rows')
print()
print('=== app_water_overview (glyphosate-only) ===')
for row in conn.execute('SELECT COUNT(*) FROM app_water_overview'):
    print(f'  {row[0]} rows')
"
```

Expected: All legacy views return results (glyphosate-only).

- [ ] **Step 4: Commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: any adjustments from end-to-end validation"
```

---

### Task 8: Run Validation Suite

**Files:** None

- [ ] **Step 1: Run the built-in validation**

```bash
cd "F:\Projects\Arasheed\Glyphosate Detection\data"
python run_pipeline.py --validate
```

Expected: `All validation checks passed.`

- [ ] **Step 2: Final commit**

```bash
git add -A
git commit -m "feat: multi-contaminant pipeline — glyphosate, lead, atrazine support"
```
