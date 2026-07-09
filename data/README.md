# ResidueIQ Data Pipeline

## What this is
A complete Python pipeline that fetches contaminant detection data from 30+
public sources, normalizes it into a unified schema, and writes it to SQLite.

No brand matching. No mock data. Pure category-based detection rates + named
product results where they actually exist.

## Files
| File | Purpose |
|---|---|
| `db/schema.sql` | Full SQLite schema: 14 tables, 5 views |
| `db/database.py` | Core DB operations, migrations, inserts |
| `db/category_aliases.csv` | 712 ingredient strings → canonical categories |
| `contaminants.py` | Contaminant registry (43 contaminants across 6 types) |
| `run_pipeline.py` | Master runner — run this |
| `seed_ingredients.py` | Seed regulatory data (ingredients, flags, commodities) |

## Setup
```bash
pip install -r requirements.txt
```

## Run
```bash
# Full pipeline
python run_pipeline.py

# Single source
python run_pipeline.py --source fda
python run_pipeline.py --source cfia
python run_pipeline.py --source efsa
python run_pipeline.py --source usda_pdp

# Validate DB after run
python run_pipeline.py --validate

# Seed regulatory data
python seed_ingredients.py
```

## Data Sources (30+)

### Government (public domain)
CFIA, EFSA, FDA, USDA PDP, UK FSA, CA DPR, Germany BVL, EPA Tolerances,
EPA Full Tolerances, Australia FSANZ, Codex MRLs, Japan/Brazil MRLs,
USDA FAS MRLs, CDC NHANES

### Independent testing
Detox Project, Clean Label Project, Consumer Reports, HRI Labs,
Florida Healthy Foods First, Academic Papers, Moms Across America,
Food Democracy Now, Soil Association

### Certification registries
GRF (Glyphosate Residue Free), USDA Organic, EU Organic,
Canada Organic, Non-GMO Project, Clean Label Certified

### Water quality
USGS Water Quality Portal (glyphosate, lead, atrazine)

## Architecture

### DataStore Abstraction
The project uses a `DataStore` Protocol (`data/datastore.py`) backed by SQLite:
- `sqlite_store.py` — SQLite (the sole backend, used by the pipeline + detection engine)

Factory: `create_datastore(db_path)`

### Detection Engine
`detect/engine.py` exposes 15 public methods via `DetectionEngine`:
- Food risk, product lookup, water quality, international MRL comparison
- Barcode scanning (Open Food Facts API), multi-contaminant scanning
- Ingredient risk scoring (three-tier: product → ingredient → category)
- Regulatory flags, commodity residues, alternatives, biomonitoring

See `docs/DATABASE_AND_ENGINE_STATUS.md` for full details.

### Contaminants
43 contaminants across 6 types: pesticides (14), heavy metals (4), food dyes (7), additives (7), environmental (9), other (2). Defined in `data/contaminants.py`.

### Regulatory Coverage Gaps
Three V1 regulatory sources are not built or incomplete:
- **Codex Alimentarius**: Fetcher deleted, 0 rows in `international_mrls`
- **Health Canada / PMRA**: Seed data only (3 water limits, 1 ban flag), no food MRL fetcher
- **FSANZ**: 10 rows from 2019 Australian diet study, no food MRL data

90 of 158 food categories lack an EPA glyphosate tolerance — affects grains (oats, wheat), legumes (lentils, chickpeas), infant food, and dairy. See `docs/DATABASE_AND_ENGINE_STATUS.md` for full details.

## Important notes for developer

### EFSA
Downloads a large ZIP from Zenodo (~100MB). Must verify column names
against actual CSV before assuming EFSA_KNOWN_COLUMNS is correct.
Print `df.columns` on first run to confirm.

### FDA
Verify column names in SampleData2023.txt by checking FDA's User Manual PDF
at the report page before running. Column names change between fiscal years.

### Source priority at query time
When the same food_category has rows from multiple sources, priority depends on product origin:

**US products (default):**
1. FDA (US regulatory)
2. CFIA (Canadian, comparable)
3. EFSA (EU, least relevant for US app)

**EU products (detected from Open Food Facts countries_tags):**
1. EFSA (EU regulatory)
2. Germany BVL
3. UK FSA
4. CFIA
5. FDA

### Category mapping
All fetchers use `normalize_category()` from `db/database.py` to map raw food names to specific canonical keys (e.g., `apple`, `strawberry`, `wheat`). No broad categories like `fresh_fruit` or `fresh_vegetables` are used. 712 aliases map to ~158 unique canonical keys.

## Re-running when new data drops
Set up monitoring for source URLs. When new data drops:
```bash
python run_pipeline.py --source [source_name]
```
Pipeline upserts — it will not create duplicates (idempotent via dedup_key).
