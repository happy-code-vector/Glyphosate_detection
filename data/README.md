# ResidueIQ Data Pipeline

## What this is
A complete Python pipeline that fetches contaminant detection data from 30+
public sources, normalizes it into a unified schema, and writes it to SQLite
(ready for Firestore migration).

No brand matching. No mock data. Pure category-based detection rates + named
product results where they actually exist.

## Files
| File | Purpose |
|---|---|
| `db/schema.sql` | Full SQLite schema: 12 tables, 11+ views |
| `db/database.py` | Core DB operations, migrations, inserts |
| `db/category_aliases.csv` | ~206 ingredient strings → canonical categories |
| `contaminants.py` | Contaminant registry (glyphosate, lead, atrazine, + more) |
| `run_pipeline.py` | Master runner — run this |
| `migrate_to_firestore.py` | SQLite → Firestore migration script |
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

# Migrate to Firestore
python migrate_to_firestore.py
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

## Important notes for developer

### EFSA
Downloads a large ZIP from Zenodo (~100MB). Must verify column names
against actual CSV before assuming EFSA_KNOWN_COLUMNS is correct.
Print `df.columns` on first run to confirm.

### FDA
Verify column names in SampleData2023.txt by checking FDA's User Manual PDF
at the report page before running. Column names change between fiscal years.

### Source priority at query time
When the same food_category has rows from multiple sources, use this priority:
1. FDA (US regulatory)
2. CFIA (Canadian, comparable)
3. EFSA (EU, least relevant for US app)

## Re-running when new data drops
Set up monitoring for source URLs. When new data drops:
```bash
python run_pipeline.py --source [source_name]
```
Pipeline upserts — it will not create duplicates (idempotent via dedup_key).
