# Multi-Contaminant Pipeline Design

**Date:** 2026-05-26
**Status:** Approved
**Scope:** Expand the data pipeline from glyphosate-only to support glyphosate, lead, and atrazine across food, water, regulatory, and biomonitoring data.

---

## 1. Schema Changes

### New column: `contaminant TEXT NOT NULL DEFAULT 'glyphosate'`

Applied to:
- `product_tests`
- `category_summaries`
- `water_tests`
- `tolerance_limits`
- `international_mrls` (uses existing `pesticide` column — kept as-is)
- `biomonitoring` (uses existing `analyte` column — kept as-is)

### New indexes

```sql
CREATE INDEX IF NOT EXISTS idx_pt_contaminant ON product_tests(contaminant);
CREATE INDEX IF NOT EXISTS idx_cs_contaminant ON category_summaries(contaminant);
CREATE INDEX IF NOT EXISTS idx_wt_contaminant ON water_tests(contaminant);
CREATE INDEX IF NOT EXISTS idx_tl_contaminant ON tolerance_limits(contaminant);
```

### Dedup key migration

New format: `sha256(contaminant|source|...other_parts)` — contaminant is always the first part. Existing glyphosate rows get new dedup keys computed automatically during migration. Since all existing data is glyphosate, this is deterministic with no collisions.

### Views

**Existing views (backward-compatible):** Add `WHERE contaminant = 'glyphosate'` to all existing views. They produce identical results to today:
- `glyphosate_measurements`
- `category_risk`
- `product_results`
- `app_food_overview`
- `app_product_lookup`
- `app_regulatory_limits`
- `app_water_overview`
- `app_international_comparison`

**New multi-contaminant views:**
- `app_food_overview_all` — same as `app_food_overview` but includes contaminant column, no filter
- `app_product_lookup_all` — same as `app_product_lookup` but includes contaminant column
- `app_water_overview_all` — same as `app_water_overview` but includes contaminant column

---

## 2. Contaminant Registry

New file `data/contaminants.py` with a `CONTAMINANTS` dict:

```python
CONTAMINANTS = {
    "glyphosate": {
        "type": "pesticide",
        "cas_number": "1071-83-6",
        "wqp_characteristic": "Glyphosate",
        "pdp_codes": [653],
        "pdp_exclude_codes": [957],  # AMPA
        "fda_resname": "GLYPHOSATE",
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
    },
    "lead": {
        "type": "heavy_metal",
        "cas_number": "7439-92-1",
        "wqp_characteristic": "Lead",
        "pdp_codes": [],  # TBD — may not be in PDP
        "fda_search": "Lead",
        "units": "ppb",
        "risk_thresholds": {"high": 15, "medium": 5, "low": 0},
    },
    "atrazine": {
        "type": "pesticide",
        "cas_number": "1912-24-9",
        "wqp_characteristic": "Atrazine",
        "pdp_codes": [],  # TBD — need lookup
        "fda_resname": "ATRAZINE",
        "units": "ppb",
        "risk_thresholds": {"high": 3, "medium": 1, "low": 0},
    },
}
```

---

## 3. Fetcher Architecture

### Contaminant parameter

Each fetcher gets a `CONTAMINANT` class attribute (default `'glyphosate'`). This flows into every row's `contaminant` field and dedup key.

### Data sources by contaminant

**Glyphosate (existing — no behavioral change):**
All 22 existing fetchers work identically. Default `'glyphosate'` means zero changes needed.

**Lead — new/expanded sources:**

| Source | Type | Notes |
|--------|------|-------|
| USDA PDP | Food | Check if lead has PDP pesticide codes |
| FDA Total Diet Study | Food | FDA TDS tracks heavy metals in food |
| USGS WQP | Water | Query `characteristicName=Lead` |
| EPA Lead & Copper Rule | Water | Drinking water lead data |
| CDC NHANES | Biomonitoring | Blood lead XPT files |
| EPA Tolerances | Regulatory | No pesticide tolerance, but EPA MCL for water |

**Atrazine — new/expanded sources:**

| Source | Type | Notes |
|--------|------|-------|
| USDA PDP | Food | Atrazine has PDP data (pesticide code lookup needed) |
| FDA | Food | FDA pesticide monitoring includes atrazine |
| USGS WQP | Water | Query `characteristicName=Atrazine` |
| EPA Tolerances | Regulatory | Section 180.344 (rate-limited on eCFR) |
| International MRLs | Regulatory | Atrazine MRLs in Codex, EU, etc. |

### Multi-chemical fetchers

Sources that cover multiple contaminants (USDA PDP, FDA, USGS WQP) get refactored to accept a contaminant config. A single fetcher class runs once per contaminant.

### Pipeline runner

`run_pipeline.py` entries supporting multiple contaminants run the fetcher once per contaminant:
```python
for contam in ["glyphosate", "lead", "atrazine"]:
    WaterQualityFetcher(contaminant=contam).run()
```

---

## 4. Water Quality Redesign

### Dynamic WQP queries

Instead of hardcoded glyphosate params, build queries from the contaminant registry:
```python
def _build_wqp_params(contaminant_key):
    return {
        "characteristicName": CONTAMINANTS[contaminant_key]["wqp_characteristic"],
        "sampleMedia": "Water",
        "mimeType": "csv",
        "sorted": "no",
        "providers": "STORET,NWIS",
    }
```

### Per-contaminant caching

Each contaminant gets its own cache file:
- `wqp_glyphosate_water.csv`
- `wqp_lead_water.csv`
- `wqp_atrazine_water.csv`

### Water regulatory standards expanded

| Contaminant | EPA MCL (ppb) | EU DWD (ppb) | Health Canada (ppb) |
|-------------|---------------|--------------|---------------------|
| Glyphosate  | 700           | 0.1          | 280                 |
| Lead        | 15 (action level) | 5        | 10                  |
| Atrazine    | 3             | 0.1          | 5                   |

### UCMR data

UCMR 3 didn't test glyphosate but DID test lead. UCMR 4 tested atrazine. Add UCMR lead and atrazine parsing.

---

## 5. Migration Strategy

### Steps (safe, additive)

1. **Schema migration** — `ALTER TABLE ... ADD COLUMN contaminant TEXT NOT NULL DEFAULT 'glyphosate'` on all target tables. No data loss.

2. **Dedup key migration** — Recompute dedup keys for existing rows to include `glyphosate` as the first part. Deterministic, no collisions.

3. **Rebuild views** — Updated `schema.sql` handles this via `DROP VIEW IF EXISTS` + `CREATE VIEW` on next `initialize()`.

4. **No data re-fetch** — All existing glyphosate data stays in place. `DEFAULT 'glyphosate'` populates the column automatically.

### Execution order

| Step | What | Risk |
|------|------|------|
| 1 | Add `contaminants.py` registry | None — new file |
| 2 | Update `schema.sql` with new columns + updated views + new `_all` views | Low — additive |
| 3 | Update `database.py` migration + insert functions | Medium — core module |
| 4 | Refactor `water_quality.py` for multi-contaminant | Medium — in-progress |
| 5 | Update existing fetchers to pass contaminant through | Low — default is glyphosate |
| 6 | Add lead-specific data sources (FDA TDS, NHANES blood lead) | Low — new fetchers |
| 7 | Add atrazine-specific data sources | Low — new fetchers |
| 8 | Update `run_pipeline.py` to run multi-contaminant | Low |
| 9 | Test full pipeline re-run | — |

### Existing database

If `residueiq.db` already has data, migration runs automatically on next `initialize()`. Fresh DB works out of the box.
