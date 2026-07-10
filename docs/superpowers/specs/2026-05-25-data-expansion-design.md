---
title: ResidueIQ Data Expansion Design
date: 2026-05-25
status: approved
---

# ResidueIQ Data Expansion Design

Expand the ResidueIQ glyphosate detection pipeline from 5 sources (126 records) to 9+ sources with multi-year coverage across government monitoring, NGO testing, academic research, and regulatory reference data.

## Goals

- Broader coverage: more years, more food categories, more countries
- Deeper coverage: more records per category, more product-level (Tier 1) data
- Reference data: EPA tolerance limits as benchmarks for detected residue levels

## Phase 1: Existing Source Expansions

### FDA — 9 Additional Years (FY2014-2022)

**Current state:** FY2023 only (16 Tier 2 records)

**Expansion:** Add FY2014 through FY2022. Each year has a ZIP file containing `CountryProductResidueData{YEAR}.txt` with per-product per-chemical residue statistics.

**URL patterns:**
- FY2018-2022: `https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-report-and-data-fy-{YEAR}`
- FY2014-2017: `https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-{YEAR}-report-and-data`

**Implementation:** Extend `FDA_REPORTS` registry in the existing `FDA` fetcher class. Add glyphosate filter (pesticide code or name match). Same `parse()` logic applies — filter rows for glyphosate, aggregate by food category.

**Expected output:** ~200K+ total samples across all years, filtered to glyphosate-positive rows. Tier 2 category aggregates per year.

**Effort:** Low. Configuration change only — no new parser logic.

---

### EFSA — 7 Additional Years (2016-2024)

**Current state:** 2023 enforcement data only (4 Tier 2 records)

**Expansion:** Add 2016, 2017, 2020, 2021, 2022, 2024 enforcement data.

**Data formats (2 variants):**
- **2020-2024:** Enforcement annex XLSX files from Zenodo. Same structure as current 2023 data.
  - 2024: Zenodo record 18327007
  - 2022: Zenodo record 10853986
  - 2021: Zenodo record 7767236
  - 2020: Zenodo record 6410774
- **2016-2017:** Visualisation XLSX files from Zenodo. Different table structure — needs a separate parser branch.
  - 2017: Zenodo record 3254912
  - 2016: Zenodo record 1320312

**Implementation:**
1. Extend `EFSA_REPORTS` with new Zenodo record entries
2. Add a `format` field to distinguish enforcement vs. visualisation XLSX
3. Add a parser branch in `parse()` for the visualisation format

**Expected output:** Dozens of additional Tier 2 category rows across EU member states.

**Effort:** Medium. New parser branch for 2016-2017 format.

---

### CFIA — NCRMP + Targeted Surveys (2016-2022)

**Current state:** 2015-2017 glyphosate-specific dataset (17 Tier 2 records)

**Expansion:** Add NCRMP annual reports and targeted pesticide surveys that include glyphosate.

**Datasets:**
- NCRMP 2016-2017: `https://open.canada.ca/data/en/dataset/95a14ca0-706c-4422-ad42-b9e86998efbe`
- NCRMP 2017-2018: `https://open.canada.ca/data/en/dataset/c87af563-b3f3-4048-96af-a5d39723ea6b`
- NCRMP 2018-2019: `https://open.canada.ca/data/en/dataset/a2ea8989-2211-4d19-bc54-199dbd4c78ca`
- NCRMP 2019-2020: `https://open.canada.ca/data/en/dataset/9e5211c8-c11f-4ebe-a7b2-65a6799a6032`
- NCRMP 2020-2021: `https://open.canada.ca/data/en/dataset/a5cb7c3c-0371-4a20-ac9a-98fc4c3536bb`
- NCRMP 2021-2022: `https://open.canada.ca/data/en/dataset/6567ac46-558e-4c95-ab93-e8326ddf8f90`
- Grain Products 2016-17: `https://open.canada.ca/data/en/dataset/21429139-d023-4090-b5de-50384cda44c8`
- Children's Food 2017: `https://open.canada.ca/data/en/dataset/61a82716-e863-4c20-b1a7-c8e05e70e72d`
- Selected Foods 2018-19: `https://open.canada.ca/data/en/dataset/e4194282-102a-40ec-ac4c-0ce20e9a33cf`

**Implementation:**
1. Extend `CFIA_REPORTS` with new dataset entries
2. NCRMP datasets are multi-pesticide — add glyphosate-specific row filtering (match on pesticide name column)
3. May need new parser branches for different CSV column layouts

**Expected output:** Additional Tier 2 records across Canadian food categories. Volume depends on glyphosate presence in multi-pesticide datasets.

**Effort:** Medium. New CSV structure parsing + glyphosate filtering.

---

### Florida HFF — Candy Category

**Current state:** Bread and infant formula (6 Tier 1 records)

**Expansion:** Add candy testing data.

**Datasets:**
- Candy page: `https://exposingfoodtoxins.com/candy/`
- Candy PDF: `https://exposingfoodtoxins.com/wp-content/uploads/2026/02/Candy.pdf`
- Also fetch additional PDFs for more detail:
  - Bread PDF: `https://exposingfoodtoxins.com/wp-content/uploads/2026/02/Bread-Testing-Details-FINAL.pdf`
  - Formula PDF: `https://exposingfoodtoxins.com/wp-content/uploads/2026/01/Infant-Formula-Testing-Details.pdf`

**Implementation:**
1. Add candy page to `FLORIDA_REPORTS`
2. Same HTML table parser as existing pages
3. Add PDF fetcher for the candy PDF (pdfplumber extraction, consistent with existing PDF fetchers)

**Expected output:** ~10-20 additional Tier 1 product records.

**Effort:** Low. Same parser, new URL entries.

---

## Phase 2: New Platforms

### USDA PDP — Limited Glyphosate Data (2011, 2021, 2022)

**Data type:** Government monitoring

**Scope:** Glyphosate was tested in only 3 of 34 PDP years on 5 commodities: soybeans (90%+ detection), corn, canned beets, blueberries, butter.

**Format:** ZIP files containing pipe-delimited text files from `https://www.ams.usda.gov/datasets/pdp/pdpdata`

**Implementation:**
- New fetcher class: `USDA_PDP(Fetcher)`
- Download ZIP files for 2011, 2021, 2022
- Parse pipe-delimited text, filter for pesticide code 653 (glyphosate) and 957 (AMPA)
- Aggregate by commodity → food category mapping
- Tier 2 output (detection rates, avg/max ppb per category)

**Expected output:** ~2,269 records filtered to glyphosate. Tier 2 aggregates for soybeans, corn, canned beets, blueberries, butter.

**Effort:** Medium. New fetcher class + new file format parser.

---

### UK FSA/PRiF — Pesticide Monitoring (2015-2025)

**Data type:** Government monitoring

**Scope:** UK quarterly pesticide residue monitoring results. Glyphosate routinely tested across cereals, bread, grain products, fruits, vegetables.

**Format:** CSV downloads from data.gov.uk. Entry point: `https://www.gov.uk/government/collections/pesticide-residues-in-food-results-of-monitoring-programme`

**Implementation:**
- New fetcher class: `UK_FSA(Fetcher)`
- Scrape the collection page for quarterly data download links
- Parse CSV files, filter for glyphosate
- Map UK commodity names to canonical categories
- Tier 1 (product-level) and Tier 2 (category aggregates) output

**Expected output:** Hundreds of records across 10+ years of quarterly monitoring.

**Effort:** Medium. New fetcher + new category alias mappings for UK terminology.

---

### CA DPR — Residue Monitoring (2020-2023)

**Data type:** Government monitoring

**Scope:** California marketplace surveillance of fresh produce and other commodities. Includes glyphosate in testing panel.

**Format:** Annual data files from `https://www.cdpr.ca.gov/reports-directory/` (filter: Residue)

**Implementation:**
- New fetcher class: `CA_DPR(Fetcher)`
- Download annual data files (2020-2023)
- Filter for glyphosate
- Map CA commodity codes to canonical categories
- Tier 2 output

**Expected output:** Category-level residue statistics for California-tested commodities.

**Effort:** Medium. New fetcher + commodity code mapping.

---

### EPA Tolerances — Reference Data

**Data type:** Regulatory limits (not monitoring)

**Scope:** Legal maximum residue limits for glyphosate on 150+ commodities per 40 CFR 180.364.

**Format:** HTML table on `https://www.ecfr.gov/current/title-40/chapter-I/subchapter-E/part-180/subpart-C/section-180.364`

**Implementation:**
- New fetcher class: `EPA_Tolerances(Fetcher)`
- Scrape eCFR HTML table
- Parse commodity name + tolerance ppm value pairs
- Map to canonical food categories
- Insert into new `tolerance_limits` table

**Database change:** New table:
```sql
CREATE TABLE IF NOT EXISTS tolerance_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    food_category TEXT NOT NULL,
    raw_commodity TEXT,
    tolerance_ppm REAL NOT NULL,
    tolerance_ppb REAL NOT NULL,
    source TEXT DEFAULT 'EPA_40CFR180.364',
    regulation_reference TEXT,
    dedup_key TEXT UNIQUE
);
```

**Expected output:** 150+ tolerance limit records as reference benchmarks.

**Effort:** Low. Simple HTML scraping, no complex parsing.

---

### Academic Papers — Primary Research Data

**Data type:** Peer-reviewed studies

**Priority papers:**
1. **Kolakowski et al. (2020)** — J Agric Food Chem, DOI: 10.1021/acs.jafc.9b07819
   - 7,955 Canadian retail samples (2015-2017). 42.3% glyphosate detection rate.
   - High value: large sample size, same commodities as CFIA data.
2. **Vicini et al. (2021)** — Compr Rev Food Sci Food Saf, DOI: 10.1111/1541-4337.12822
   - Comprehensive review aggregating regulatory data from EPA, EU, Canada.
   - Compiled comparison tables useful as cross-reference.
3. **Zoller et al. (2018)** — Food Addit Contam Part B, PMID: 29284371
   - Swiss retail food monitoring data. Adds a non-North-American/EU perspective.

**Implementation:**
- New fetcher class: `AcademicPapers(Fetcher)`
- Manual data entry from PDF tables (pdfplumber or manual transcription)
- Each paper's data hardcoded as structured records
- Tier 1 and Tier 2 output depending on paper's reporting level

**Expected output:** Hundreds of additional records from primary research.

**Effort:** High. Manual extraction from academic PDFs.

---

### Australia FSANZ — Total Diet Study (2019)

**Data type:** Government summary statistics

**Scope:** 25th Australian Total Diet Study. Glyphosate tested across food groups. Summary stats only (no raw data).

**Format:** Web page at `https://www.foodstandards.gov.au/consumer/chemicals/glyphosate`

**Implementation:**
- Hardcode summary statistics as data entries (no download needed)
- Small dataset — manual entry in the fetcher
- Tier 2 output only (category-level detection rates and max values)

**Expected output:** ~5-10 Tier 2 records for Australian food categories.

**Effort:** Low. Manual data entry.

---

### Brazil/Japan — MRLs and Reports (Reference Only)

**Data type:** Regulatory limits and PDF reports

**Scope:**
- Japan: MRL database at `https://www.m5.ws001.squarestart.ne.jp/foundation/search.html`
- Brazil: ANVISA PARA program reports (PDF only)

**Implementation:**
- MRL data as reference entries in `tolerance_limits` table (like EPA)
- PDF reports as future Tier 2 extraction targets
- Low priority — defer full implementation if time-constrained

**Effort:** Low for MRLs, High for PDF extraction.

---

### Codex Alimentarius MRLs — International Reference Limits

**Data type:** Regulatory limits (not monitoring)

**Scope:** FAO/WHO international maximum residue limits for glyphosate across 100+ commodities. The global standard that many countries adopt.

**Format:** Web database at `https://www.fao.org/fao-who-codexalimentarius/codex-texts/dbs/pestres/` — search by pesticide name "glyphosate" (ID 158). No bulk CSV download. Requires scraping search results or reverse-engineering the API.

**Implementation:**
- New fetcher class: `Codex_MRLs(Fetcher)`
- Scrape the Codex pesticide residue database for glyphosate entries
- Parse commodity + MRL value pairs
- Insert into `tolerance_limits` table alongside EPA tolerances
- Adds international perspective to the US-focused EPA limits

**Expected output:** 100+ tolerance limit records as international reference benchmarks.

**Effort:** Medium. Web scraping of database interface.

---

### Germany BVL — National Pesticide Monitoring (2011-2022)

**Data type:** Government monitoring

**Scope:** Germany's national pesticide residue monitoring reports. Unlike the current EFSA enforcement-only data (which shows only MRL exceedances), BVL provides the full picture: all samples including compliant detections, detection rates, and average levels for glyphosate across food categories.

**Format:** Excel/CSV table downloads ("Tabellen zur Nationalen Berichterstattung") for years 2011-2022. Available at `https://www.bvl.bund.de/` under pesticide residue reporting.

**Implementation:**
- New fetcher class: `Germany_BVL(Fetcher)`
- Download annual table files
- Filter for glyphosate rows (German-language column headers need mapping)
- Map German commodity names to English canonical categories
- Tier 2 output (detection rates, avg/max ppb per category)
- This is a better EU data source than the current EFSA enforcement-only fetcher

**Expected output:** Tier 2 category-level residue statistics across 10+ years of German monitoring. Provides detection rates (not just exceedances).

**Effort:** Medium-High. German-language data parsing + commodity name translation.

---

### The Detox Project — Independent Food Testing

**Data type:** Independent laboratory testing (Tier 1 product data)

**Scope:** Non-profit organization that commissions glyphosate testing on popular grocery products. Broader food category coverage than other consumer-advocacy testing (includes crackers, chips, protein powders, pulses, cereals, bread).

**Key reports:**
- "Glyphosate: Unsafe On Any Plate" (2016) — ~30 popular American food products tested by Anresco Laboratories. Products include Cheerios (1,125 ppb), crackers, chips, etc.
- "The Poison in Our Daily Bread" (2022) — comprehensive testing of bread, pulses, grains, protein bars from major retailers. Found glyphosate in 18 of 26 Non-GMO labeled products.
- Protein powder testing (2021) — pea protein supplements.

**Format:** Web reports at `https://detoxproject.org/reports/` and `https://detoxproject.org/glyphosate-in-food-water/`. No structured data downloads. Requires web scraping.

**Implementation:**
- New fetcher class: `DetoxProject(Fetcher)`
- Scrape report pages for product names and ppb values
- Parse product-level data (Tier 1)
- Map product categories to canonical food categories
- Derive Tier 2 aggregates from Tier 1 data

**Expected output:** ~50-80 additional Tier 1 product records across broader food categories than other consumer-advocacy testing.

**Effort:** Medium. Web scraping of report pages.

---

### CDC NHANES — Biomonitoring Data (2013-2016)

**Data type:** Human biomonitoring (urine glyphosate levels)

**Scope:** Nationally representative population-level exposure data. Measures glyphosate and AMPA in urine of NHANES participants. Only dataset that answers "how much glyphosate are people actually absorbing?" rather than "how much is in food?"

**Format:** XPT (SAS Transport) files, downloadable from CDC. Readable by pandas (`pd.read_xpt()`).

**Available years:** 2013-2014 (SSGLYP_H, 73.7 KB) and 2015-2016 (SSGLYP_I, 101.4 KB).

**Variables:**
- SSGLYP = glyphosate concentration in ng/mL (= ppb)
- SSGLYPL = below-detection flag (0=detected, 1=below LOD)
- LOD = 0.2 ng/mL
- Sample weights for national representativeness

**Implementation:**
- New fetcher class: `CDC_NHANES(Fetcher)`
- Download XPT files from CDC
- Parse with pandas, extract glyphosate variables
- Aggregate by demographics (age group, gender) if available
- Insert into new `biomonitoring` table

**Database change:** New table:
```sql
CREATE TABLE IF NOT EXISTS biomonitoring (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL DEFAULT 'CDC_NHANES',
    cycle TEXT NOT NULL,
    analyte TEXT NOT NULL,
    population_group TEXT,
    sample_size INTEGER,
    detected_count INTEGER,
    detection_rate REAL,
    geometric_mean REAL,
    percentile_50 REAL,
    percentile_75 REAL,
    percentile_90 REAL,
    percentile_95 REAL,
    unit TEXT DEFAULT 'ng/mL',
    lod REAL,
    dedup_key TEXT UNIQUE
);
```

**Expected output:** Population-level exposure statistics by demographic group for 2 NHANES cycles.

**Effort:** Medium. New schema table + XPT file parsing.

---

### Sources Considered and Skipped

**EFSA OpenFoodTox 2.0** — Contains toxicological reference values (ADI, NOAEL, LOAEL) for glyphosate, NOT food residue measurements. Does not fit the pipeline's measurement-focused schema. One row per substance, not per food sample.

---

## Database Changes

### New Table: `tolerance_limits`

Stores regulatory maximum residue limits as reference benchmarks alongside monitoring data.

```sql
CREATE TABLE IF NOT EXISTS tolerance_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    food_category TEXT NOT NULL,
    raw_commodity TEXT,
    tolerance_ppm REAL NOT NULL,
    tolerance_ppb REAL NOT NULL,
    source TEXT NOT NULL,
    regulation_reference TEXT,
    dedup_key TEXT UNIQUE
);
```

### Schema Updates to `glyphosate_measurements`

No structural changes needed. New sources use existing `source_name` field. New food categories added to `category_aliases` table.

### New Canonical Categories

Potential additions depending on data discovered:
- `butter` (USDA PDP)
- `blueberries` (USDA PDP)
- `canned_beets` (USDA PDP)
- Any UK-specific or CA-specific commodity names requiring new aliases

---

## Implementation Order

### Batch 1: Quick Wins (existing fetcher modifications)
1. FDA FY2014-2022 — extend registry
2. Florida HFF candy — extend registry + add PDF
3. EFSA 2020-2022, 2024 — extend registry (same format)
4. EFSA 2016-2017 — add visualisation format parser branch

### Batch 2: CFIA Expansion
5. CFIA NCRMP reports — extend registry + glyphosate filter
6. CFIA targeted surveys — extend registry + new CSV parsing

### Batch 3: New Government Platforms
7. USDA PDP — new fetcher class
8. UK FSA — new fetcher class
9. CA DPR — new fetcher class
10. Germany BVL — new fetcher class (German-language parsing)
11. EPA Tolerances — new fetcher class + tolerance_limits table

### Batch 4: Research, Reference & Biomonitoring
12. Codex Alimentarius MRLs — new fetcher (tolerance_limits table)
13. Academic papers — new fetcher with manual data
14. The Detox Project — new fetcher (web scraping)
15. CDC NHANES — new fetcher + biomonitoring table
16. Australia FSANZ — hardcoded summary data
17. Brazil/Japan MRLs — reference data entries

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| FDA download URLs are JavaScript-rendered | Use known URL patterns; fall back to manual download if needed |
| CFIA NCRMP datasets may have varying column structures | Dynamic column detection (existing pattern in codebase) |
| UK FSA data.gov.uk URLs may change | Scrape collection page for current links |
| EPA eCFR HTML structure may change | Fuzzy column detection + test regularly |
| Academic paper data extraction is error-prone | Manual verification of extracted values |
| Germany BVL tables in German language | Map German commodity/chemical names to English canonical terms |
| Detox Project web reports have no structured data | Careful scraping with fallback to manual entry |
| CDC NHANES only covers 2013-2016 for glyphosate | Limited but nationally representative — still valuable |
| Codex MRL database has no bulk download | Scrape search results or use underlying API |
