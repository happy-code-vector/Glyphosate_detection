# ResidueIQ — Data Fetching & Standardization Guide

Every source is different. This doc tells your developer exactly how to fetch each one,
what format it comes in, how to clean it, and how to write it into one unified Supabase schema.

---

## The Unified Target Schema

Everything from every source gets normalized into this single table before anything touches the app.

```sql
CREATE TABLE glyphosate_data (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Classification
  tier              INT NOT NULL,          -- 1 = named product, 2 = ingredient/category
  source_name       TEXT NOT NULL,         -- 'EWG', 'Florida HFF', 'CFIA', 'EFSA', 'FDA'
  source_url        TEXT,                  -- direct link to the report/page
  published_date    DATE,
  data_year         INT,

  -- Product info (Tier 1 only — null for Tier 2)
  product_name      TEXT,
  brand             TEXT,
  barcode           TEXT,                  -- if known

  -- Category info (used by both tiers)
  food_category     TEXT NOT NULL,         -- standardized key (see category map below)
  raw_category      TEXT,                  -- original string from source before normalization

  -- Measurements
  ppb_value         NUMERIC,               -- single product result (Tier 1)
  detection_rate    NUMERIC,               -- 0.0–1.0, proportion of samples positive (Tier 2)
  avg_ppb           NUMERIC,               -- category average
  max_ppb           NUMERIC,               -- category max
  min_ppb           NUMERIC,
  sample_count      INT,

  -- Confidence & display
  confidence        TEXT,                  -- 'high', 'medium', 'low'
  methodology_note  TEXT,                  -- lab method, caveats
  is_organic        BOOLEAN DEFAULT false,

  -- Housekeeping
  created_at        TIMESTAMPTZ DEFAULT NOW(),
  updated_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_food_category ON glyphosate_data(food_category);
CREATE INDEX idx_tier ON glyphosate_data(tier);
CREATE INDEX idx_product_name ON glyphosate_data(product_name);
CREATE INDEX idx_brand ON glyphosate_data(brand);
```

---

## Standardized Category Keys

Every source uses different names for the same thing.
Always normalize raw category strings to these keys before inserting.

| Canonical Key      | Maps From (examples)                                           |
|--------------------|----------------------------------------------------------------|
| `oats`             | "oat-based", "oat cereal", "rolled oats", "oat flour", "oatmeal" |
| `wheat`            | "wheat grain", "wheat flour", "whole wheat", "bread wheat"    |
| `soybeans`         | "soy", "soya", "soybean", "soy-based products"                |
| `corn`             | "maize", "corn flour", "cornstarch", "sweet corn"             |
| `chickpeas`        | "chickpea", "garbanzo", "hummus", "chickpea products"         |
| `lentils`          | "lentil", "pulse products", "dried lentils"                   |
| `beans`            | "bean", "pinto bean", "kidney bean", "dried beans"            |
| `peas`             | "pea", "dried peas", "green peas", "split peas"               |
| `barley`           | "barley grain", "barley flour", "malted barley"               |
| `canola`           | "rapeseed", "canola oil", "rape", "colza"                     |
| `sugar_beets`      | "sugar beet", "beet sugar", "sugar"                           |
| `buckwheat`        | "buckwheat flour", "buckwheat grain"                          |
| `quinoa`           | "quinoa grain", "quinoa flour"                                |
| `rye`              | "rye grain", "rye flour", "rye bread"                         |
| `rice`             | "rice grain", "white rice", "brown rice", "rice flour"        |
| `infant_cereal`    | "infant food", "baby food cereal", "children's cereal"        |
| `fresh_vegetables` | "fresh vegetables", "lettuce", "spinach", "root vegetables"   |
| `fresh_fruit`      | "fresh fruit", "apples", "citrus", "berries"                  |

---

## Source 1 — EWG (Tier 1 + Tier 2)

### What's available
- Named product results with specific ppb (Tier 1)
- Category-level detection rates in report text (Tier 2)
- 4 test rounds: 2018 Round 1, 2018 Round 2, 2019, 2020 (hummus), 2023

### How to fetch

**Step 1 — Download the PDFs directly:**

```
2018 Round 1: https://www.ewg.org/sites/default/files/u352/EWG_Glyphosate_BenchmarkTable-2_C02.pdf
2018 Round 2: https://www.ewg.org/sites/default/files/u352/EWG_Glyphosate-2_Table_Full_C02.pdf
2023 results: https://static.ewg.org/upload/pdf/EWG_Glyphosate-Testing_05.23_Table_C01.pdf
```

For hummus/chickpea and other rounds, scrape the results table from the report pages:
```
https://www.ewg.org/childrenshealth/monsanto-weedkiller-still-contaminates-foods-marketed-to-children
https://www.ewg.org/news-insights/news/2023/04/going-going-gone-ewg-finds-glyphosate-levels-drop-oat-based-products
```

**Step 2 — Parse with Python:**

```python
import pdfplumber
import pandas as pd
import re

def parse_ewg_pdf(pdf_path, round_label, published_date):
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue
            for row in table:
                if not row or not row[0]:
                    continue
                product_name = str(row[0]).strip()
                ppb_raw = str(row[1]).strip() if len(row) > 1 else ""
                
                # Handle "<5" or "ND" (not detected)
                if ppb_raw in ["ND", "nd", "<LOQ", ""]:
                    ppb_value = None
                    detected = False
                else:
                    ppb_raw = ppb_raw.replace("<", "").replace(">", "").replace(",", "")
                    try:
                        ppb_value = float(ppb_raw)
                        detected = True
                    except:
                        continue
                
                rows.append({
                    "tier": 1,
                    "source_name": "EWG",
                    "source_url": "https://www.ewg.org",
                    "published_date": published_date,
                    "data_year": int(published_date[:4]),
                    "product_name": product_name,
                    "brand": extract_brand(product_name),  # see helper below
                    "food_category": "oats",  # EWG PDFs are oat-focused
                    "raw_category": "oat-based products",
                    "ppb_value": ppb_value if detected else None,
                    "detection_rate": None,  # not applicable for single product
                    "confidence": "high",
                    "methodology_note": f"EWG commissioned lab test, {round_label}. Lab: Anresco Laboratories.",
                    "is_organic": "organic" in product_name.lower()
                })
    return rows

def extract_brand(product_name):
    brands = ["Quaker", "Cheerios", "General Mills", "Nature Valley", 
              "Kind", "Clif", "Bob's Red Mill", "Nature's Path", "Lucky Charms",
              "Honey Nut Cheerios", "Back to Nature", "Simple Truth"]
    for brand in brands:
        if brand.lower() in product_name.lower():
            return brand
    return None
```

### What the parsed data looks like

```json
{
  "tier": 1,
  "source_name": "EWG",
  "published_date": "2019-06-19",
  "data_year": 2019,
  "product_name": "Honey Nut Cheerios Medley Crunch",
  "brand": "General Mills",
  "food_category": "oats",
  "ppb_value": 833,
  "detection_rate": null,
  "confidence": "high",
  "methodology_note": "EWG commissioned lab test, 2019 Round. Lab: Anresco Laboratories.",
  "is_organic": false
}
```

### Category-level rows from EWG (Tier 2)

Insert these manually as Tier 2 rows sourced from EWG's published detection rates:

```python
EWG_CATEGORY_RATES = [
    {
        "tier": 2, "source_name": "EWG", "published_date": "2023-04-01",
        "food_category": "oats", "detection_rate": 1.0,
        "avg_ppb": 290, "sample_count": 24,
        "methodology_note": "EWG 2023 round: all 24 non-organic samples detected"
    },
    {
        "tier": 2, "source_name": "EWG", "published_date": "2020-07-01",
        "food_category": "chickpeas", "detection_rate": 0.82,
        "avg_ppb": 510, "sample_count": 11,
        "methodology_note": "EWG 2020 hummus/chickpea round"
    },
    {
        "tier": 2, "source_name": "EWG", "published_date": "2020-07-01",
        "food_category": "beans", "detection_rate": 0.60,
        "avg_ppb": 380, "sample_count": 20,
        "methodology_note": "EWG 2020 bean and lentil round"
    },
    {
        "tier": 2, "source_name": "EWG", "published_date": "2020-07-01",
        "food_category": "lentils", "detection_rate": 0.60,
        "avg_ppb": 380, "sample_count": 20,
        "methodology_note": "EWG 2020 bean and lentil round"
    },
]
```

---

## Source 2 — Florida Healthy Florida First (Tier 1)

### What's available
Named brand products with specific ppb. Most current data (2026).
Bread (Feb 2026), infant formula (Jan 2026), candy (Mar 2026).

### How to fetch

**Scrape the results table from:**
```
https://www.floridahealth.gov/newsroom/2026/02/bread-glyphosate-testing.pr.html
https://exposingfoodtoxins.com
```

**Python scraper:**

```python
import requests
from bs4 import BeautifulSoup

def scrape_florida_hff(url, category, published_date):
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(resp.text, "html.parser")
    rows = []
    
    # Find the results table — look for <table> containing ppb values
    tables = soup.find_all("table")
    for table in tables:
        for tr in table.find_all("tr")[1:]:  # skip header
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            product_name = cells[0]
            ppb_raw = cells[-1]  # last column is usually ppb or result
            
            try:
                ppb_value = float(ppb_raw.replace("ppb", "").replace("<", "").strip())
            except:
                ppb_value = None
            
            rows.append({
                "tier": 1,
                "source_name": "Florida Healthy Florida First",
                "source_url": url,
                "published_date": published_date,
                "data_year": int(published_date[:4]),
                "product_name": product_name,
                "brand": extract_brand(product_name),
                "food_category": category,
                "raw_category": category,
                "ppb_value": ppb_value,
                "confidence": "high",
                "methodology_note": "Florida Dept of Health lab test. Note: full methodology not publicly disclosed.",
                "is_organic": "organic" in product_name.lower()
            })
    return rows
```

**Seed these manually** — they won't change often and there are only ~20 products so far:

```python
FLORIDA_SEED_DATA = [
    {"product_name": "Nature's Own Butter Bread", "brand": "Nature's Own",
     "food_category": "wheat", "ppb_value": 190.23, "published_date": "2026-02-01"},
    {"product_name": "Nature's Own Perfectly Crafted White", "brand": "Nature's Own",
     "food_category": "wheat", "ppb_value": 132.34, "published_date": "2026-02-01"},
    {"product_name": "Wonder Bread Classic White", "brand": "Wonder",
     "food_category": "wheat", "ppb_value": 45.0, "published_date": "2026-02-01"},
    {"product_name": "Sara Lee Honey Wheat", "brand": "Sara Lee",
     "food_category": "wheat", "ppb_value": 38.0, "published_date": "2026-02-01"},
    # Add Dave's Killer Bread varieties when confirmed
]
```

---

## Source 3 — Canada CFIA (Tier 2)

### What's available
7,955 samples across grains, pulses, fruits/vegetables, infant food.
**No brand names** — category-level detection rates and compliance data only.
Available as a CSV on Canada's Open Government Portal.

### How to fetch

```python
import pandas as pd
import requests

# Direct CSV download
CFIA_CSV_URL = "https://open.canada.ca/data/en/dataset/906cd35c-d396-4999-9a9f-f5351796661f"

# NOTE: The portal page has the CSV linked as a resource.
# Your dev should visit the URL, find the CSV resource link, 
# and use the direct file URL. It typically looks like:
# https://open.canada.ca/data/dataset/.../resource/.../download/glyphosate_data.csv

def parse_cfia_csv(filepath):
    df = pd.read_csv(filepath)
    # CFIA CSV columns vary — common ones:
    # 'Food Category', 'Total Samples', 'Samples with Detectable Residues',
    # 'Detection Rate (%)', 'Mean Concentration (mg/kg)', 'Max Concentration (mg/kg)'
    
    rows = []
    for _, row in df.iterrows():
        raw_cat = str(row.get("Food Category", "")).strip()
        canonical = normalize_category(raw_cat)  # see normalization function below
        if not canonical:
            continue
        
        total = int(row.get("Total Samples", 0))
        detected = int(row.get("Samples with Detectable Residues", 0))
        
        rows.append({
            "tier": 2,
            "source_name": "CFIA",
            "source_url": "https://inspection.canada.ca/en/food-safety-industry/food-chemistry-and-microbiology/food-safety-testing-reports-and-journal-articles/executive-summary",
            "published_date": "2017-04-01",
            "data_year": 2017,
            "food_category": canonical,
            "raw_category": raw_cat,
            "detection_rate": round(detected / total, 4) if total > 0 else None,
            "avg_ppb": float(row.get("Mean Concentration (mg/kg)", 0)) * 1000,  # mg/kg → ppb
            "max_ppb": float(row.get("Max Concentration (mg/kg)", 0)) * 1000,
            "sample_count": total,
            "confidence": "medium",
            "methodology_note": "CFIA Safeguarding with Science: Glyphosate Testing 2015-2016. LC-MS/MS method. No brand names disclosed.",
        })
    return rows
```

**Known CFIA detection rates to hardcode as fallback** (from published executive summary):

```python
CFIA_KNOWN_RATES = {
    "grains":     {"detection_rate": 0.366, "sample_count": 869},
    "beans":      {"detection_rate": 0.474, "sample_count": 869},
    "peas":       {"detection_rate": 0.474, "sample_count": 869},
    "lentils":    {"detection_rate": 0.474, "sample_count": 869},
    "chickpeas":  {"detection_rate": 0.474, "sample_count": 869},
    "soybeans":   {"detection_rate": 0.474, "sample_count": 869},
    "infant_cereal": {"detection_rate": 0.32, "sample_count": 82},
    "fresh_vegetables": {"detection_rate": 0.05, "sample_count": 482},
    "fresh_fruit": {"detection_rate": 0.05, "sample_count": 482},
}
```

---

## Source 4 — EFSA (Tier 2)

### What's available
Largest dataset. EU member state monitoring, 9,842+ samples (2024 report).
Raw data on Zenodo as ZIP → CSV inside. No brand names.

### How to fetch

```python
import requests, zipfile, io
import pandas as pd

# 2022 report raw data (most complete glyphosate coverage):
EFSA_ZENODO_URL = "https://zenodo.org/records/10853986/files/AppendixD_2022.zip"

# 2023 appendix:
# https://zenodo.org/records/14765085

def fetch_efsa_zenodo(zip_url):
    resp = requests.get(zip_url, stream=True)
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    
    # Find the main data CSV inside the ZIP
    csv_file = [f for f in z.namelist() if f.endswith(".csv") and "occurrence" in f.lower()]
    if not csv_file:
        csv_file = [f for f in z.namelist() if f.endswith(".csv")][0]
    
    df = pd.read_csv(z.open(csv_file[0]), low_memory=False)
    return df

def parse_efsa_data(df):
    # Filter to glyphosate only
    # EFSA uses pesticide codes — glyphosate is typically 'GLY' or substance name
    gly = df[
        df.apply(lambda r: "glyphosate" in str(r).lower(), axis=1)
    ]
    
    rows = []
    for category, group in gly.groupby("matrix_EN"):  # or similar column name
        canonical = normalize_category(category)
        if not canonical:
            continue
        
        total = len(group)
        detected = len(group[group["result_value"] > 0])
        
        rows.append({
            "tier": 2,
            "source_name": "EFSA",
            "source_url": "https://zenodo.org/records/10853986",
            "published_date": "2024-04-01",
            "data_year": 2024,
            "food_category": canonical,
            "raw_category": category,
            "detection_rate": round(detected / total, 4) if total > 0 else None,
            "avg_ppb": group["result_value"].mean() * 1000,  # mg/kg → ppb
            "max_ppb": group["result_value"].max() * 1000,
            "sample_count": total,
            "confidence": "medium",
            "methodology_note": "EFSA EU coordinated control programme. Note: glyphosate requires SRM method — not all member states report it.",
        })
    return rows
```

**Important:** EFSA column names vary by year and member state file.
Your developer must open the CSV first and confirm exact column names before running the parser.

---

## Source 5 — FDA 2023 Monitoring Program (Tier 2)

### What's available
The FDA publishes annual pesticide residue monitoring data as `.txt` files.
**Glyphosate is included** in the 2023 dataset (unlike USDA PDP).
~21,000 analytical samples across hundreds of food products.

### How to fetch

```
Report page: https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-report-and-data-fy-2023
Files to download:
  SampleData2023.zip    → SampleData2023.txt (21,462 rows — all individual sample results)
  Chemical2023.zip      → Chemical2023.txt   (which chemicals are in scope)
  ProdCode.txt          → maps product codes to food names
```

```python
import pandas as pd

def parse_fda_monitoring(sample_file, prodcode_file, chemical_file):
    # Load files — tab-delimited
    samples = pd.read_csv(sample_file, sep="\t", low_memory=False)
    products = pd.read_csv(prodcode_file, sep="\t")
    chemicals = pd.read_csv(chemical_file, sep="\t")
    
    # Find glyphosate chemical code
    gly_codes = chemicals[
        chemicals.apply(lambda r: "glyphosate" in str(r).lower(), axis=1)
    ]["CHEM_CODE"].tolist()
    
    # Filter samples to glyphosate only
    gly_samples = samples[samples["CHEM_CODE"].isin(gly_codes)]
    
    # Merge with product names
    gly_samples = gly_samples.merge(products, on="PROD_CODE", how="left")
    
    rows = []
    for prod_code, group in gly_samples.groupby("PROD_CODE"):
        product_name = group["PRODUCT"].iloc[0] if "PRODUCT" in group.columns else prod_code
        canonical = normalize_category(product_name)
        
        total = len(group)
        detected = len(group[group["CONCEN"] > 0])
        
        rows.append({
            "tier": 2,
            "source_name": "FDA",
            "source_url": "https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-report-and-data-fy-2023",
            "published_date": "2025-01-01",
            "data_year": 2023,
            "food_category": canonical or "unknown",
            "raw_category": product_name,
            "detection_rate": round(detected / total, 4) if total > 0 else None,
            "avg_ppb": group[group["CONCEN"] > 0]["CONCEN"].mean() if detected else None,
            "max_ppb": group["CONCEN"].max() if detected else None,
            "sample_count": total,
            "confidence": "high",
            "methodology_note": "FDA Pesticide Residue Monitoring Program FY 2023. US regulatory monitoring data.",
        })
    return rows
```

---

## Category Normalization Function

Every source uses different terms. This function maps them all to canonical keys.

```python
CATEGORY_MAP = {
    # Oats
    "oat": "oats", "oats": "oats", "oat cereal": "oats",
    "oat-based": "oats", "oatmeal": "oats", "oat flour": "oats",
    "rolled oats": "oats", "oat bran": "oats", "oat grain": "oats",
    # Wheat
    "wheat": "wheat", "wheat grain": "wheat", "wheat flour": "wheat",
    "whole wheat": "wheat", "bread wheat": "wheat", "wheat bran": "wheat",
    "pasta": "wheat", "bread": "wheat", "flour": "wheat",
    # Soy
    "soy": "soybeans", "soya": "soybeans", "soybean": "soybeans",
    "soy-based": "soybeans", "soy products": "soybeans", "tofu": "soybeans",
    # Corn
    "corn": "corn", "maize": "corn", "cornstarch": "corn",
    "corn flour": "corn", "corn grain": "corn",
    # Legumes
    "chickpea": "chickpeas", "garbanzo": "chickpeas", "hummus": "chickpeas",
    "lentil": "lentils", "dried lentils": "lentils",
    "bean": "beans", "pinto bean": "beans", "kidney bean": "beans",
    "pea": "peas", "dried peas": "peas", "split peas": "peas",
    # Grains
    "barley": "barley", "barley grain": "barley",
    "canola": "canola", "rapeseed": "canola", "rape": "canola",
    "buckwheat": "buckwheat",
    "quinoa": "quinoa",
    "rye": "rye", "rye grain": "rye",
    "rice": "rice", "white rice": "rice", "brown rice": "rice",
    # Produce
    "fresh vegetables": "fresh_vegetables", "vegetables": "fresh_vegetables",
    "lettuce": "fresh_vegetables", "spinach": "fresh_vegetables",
    "fresh fruit": "fresh_fruit", "fruit": "fresh_fruit", "apple": "fresh_fruit",
    # Infant
    "infant food": "infant_cereal", "baby food": "infant_cereal",
    "infant cereal": "infant_cereal", "children cereal": "infant_cereal",
    # Sugar
    "sugar beet": "sugar_beets", "beet sugar": "sugar_beets", "sugar": "sugar_beets",
}

def normalize_category(raw: str) -> str | None:
    if not raw:
        return None
    raw_lower = raw.lower().strip()
    # Exact match
    if raw_lower in CATEGORY_MAP:
        return CATEGORY_MAP[raw_lower]
    # Partial match
    for key, val in CATEGORY_MAP.items():
        if key in raw_lower:
            return val
    return None
```

---

## Supabase Upsert Script

After parsing each source, insert with upsert to avoid duplicates.

```python
from supabase import create_client
import os

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

def upsert_rows(rows: list[dict]):
    if not rows:
        return
    
    # Clean rows — remove None keys for Supabase
    cleaned = []
    for row in rows:
        cleaned.append({k: v for k, v in row.items() if v is not None})
    
    # Upsert in batches of 100
    batch_size = 100
    for i in range(0, len(cleaned), batch_size):
        batch = cleaned[i:i+batch_size]
        result = supabase.table("glyphosate_data").upsert(
            batch,
            on_conflict="source_name,product_name,food_category,data_year"
        ).execute()
        print(f"Inserted batch {i//batch_size + 1}: {len(batch)} rows")
```

---

## Full Pipeline — Run Order

```
Step 1: parse_cfia_csv()         → ~25 category rows (Tier 2 baseline)
Step 2: parse_efsa_data()        → ~35 category rows (Tier 2 EU confirmation)
Step 3: parse_fda_monitoring()   → ~40 category rows (Tier 2 US current)
Step 4: parse_ewg_pdf() x4       → ~100 named product rows (Tier 1)
Step 5: seed FLORIDA_SEED_DATA   → ~20 named product rows (Tier 1)
Step 6: upsert_rows() all batches
```

**Total after full pipeline: ~220 rows.**
- ~120 Tier 1 named product rows
- ~100 Tier 2 category-level rows covering ~40 food categories

---

## Priority Conflict Resolution

When the same food_category has rows from multiple sources, the app query should resolve conflicts like this:

```sql
-- App query: get best available category data
SELECT *
FROM glyphosate_data
WHERE food_category = 'oats'
  AND tier = 2
ORDER BY
  CASE source_name
    WHEN 'EWG' THEN 1          -- most specific to US consumer products
    WHEN 'FDA' THEN 2          -- US regulatory
    WHEN 'CFIA' THEN 3         -- Canadian, comparable
    WHEN 'EFSA' THEN 4         -- EU, less relevant for US app
  END,
  data_year DESC               -- prefer newer data within same source
LIMIT 1;
```

---

## Monitoring for New Data

Set these up in Make.com — HTTP GET on monthly schedule, alert on content change:

| URL to Monitor | Expected update | Alert trigger |
|---|---|---|
| `ewg.org/areas-focus/toxic-chemicals/glyphosate` | 2–3x/year | New report link appears |
| `floridahealth.gov/newsroom` | Monthly | "glyphosate" in new post |
| `inspection.canada.ca/en/food-safety-industry` | Annual | New testing bulletin |
| `efsa.europa.eu/en/publications` | Annual | New pesticide residue report |
| `fda.gov/food/pesticides/pesticide-residue-monitoring-report-and-data` | Annual | New fiscal year data |

When any alert fires → run the relevant parser → upsert new rows → push notification to app users.