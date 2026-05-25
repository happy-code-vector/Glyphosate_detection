# ResidueIQ Data Pipeline

## What this is
A complete Python pipeline that fetches glyphosate detection data from four
public sources, normalizes it into a unified schema, and writes it to Supabase.

No brand matching. No mock data. Pure category-based detection rates + named
product results where they actually exist.

## Files
| File | Purpose |
|---|---|
| `schema.sql` | Run this in Supabase SQL editor first |
| `category_map.py` | 206 ingredient strings → 19 canonical categories |
| `fetch_cfia.py` | Canada CFIA: 12 category rows |
| `fetch_efsa.py` | EFSA EU: ~35 category rows (downloads Zenodo ZIP) |
| `fetch_fda.py` | FDA FY2023: ~40 category rows |
| `fetch_ewg.py` | EWG PDFs: ~100 named product rows + 4 category rows |
| `fetch_florida.py` | Florida HFF: 6 named product rows (seeded, scrape future) |
| `build_ingredient_map.py` | Converts category_map.py → DB rows |
| `upsert_supabase.py` | Writes all rows to Supabase |
| `run_pipeline.py` | Master runner — run this |

## Setup
```bash
pip install -r requirements.txt
export SUPABASE_URL=your_url
export SUPABASE_SERVICE_KEY=your_service_key
```

## Run
```bash
# Full pipeline
python run_pipeline.py

# Dry run (writes JSON, no DB)
python run_pipeline.py --dry-run

# Single source
python run_pipeline.py --source ewg
python run_pipeline.py --source cfia
python run_pipeline.py --source efsa
python run_pipeline.py --source fda
python run_pipeline.py --source florida
```

## Tables written to
- `ingredient_category_map` — 206 rows (run first, used by app)
- `glyphosate_categories` — ~100 rows from all sources
- `glyphosate_named_products` — ~120 rows (EWG + Florida only)

## Important notes for developer

### EFSA
Downloads a large ZIP from Zenodo (~100MB). Must verify column names
against actual CSV before assuming EFSA_KNOWN_COLUMNS is correct.
Print `df.columns` on first run to confirm.

### FDA
Verify column names in SampleData2023.txt by checking FDA's User Manual PDF
at the report page before running. Column names change between fiscal years.

### EWG
PDF parsing is fragile. Run `python fetch_ewg.py` first and inspect output.
If rows come back empty, the PDF table structure changed — use pdfplumber
to inspect the page manually.

### Category priority at query time
When the same food_category has rows from multiple sources, use this priority:
1. EWG (most US-specific)
2. FDA (US regulatory)
3. CFIA (Canadian, comparable)
4. EFSA (EU, least relevant for US app)

Query pattern:
```sql
SELECT * FROM glyphosate_categories
WHERE food_category = 'oats'
ORDER BY
  CASE source_name
    WHEN 'EWG'  THEN 1
    WHEN 'FDA'  THEN 2
    WHEN 'CFIA' THEN 3
    WHEN 'EFSA' THEN 4
  END,
  data_year DESC
LIMIT 1;
```

## Re-running when new data drops
Set Make.com to monitor the five source URLs.
When alert fires for a source:
```bash
python run_pipeline.py --source [source_name]
```
Pipeline upserts — it will not create duplicates.
