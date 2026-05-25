# Data Expansion — Batch 1 & 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand 4 existing sources (FDA, EFSA, CFIA, Florida HFF) with multi-year data to grow from 126 records to thousands.

**Architecture:** Extend existing `*_REPORTS` registries with additional year entries. Each fetcher already loops over its report list, so adding entries = adding data. New parser branches needed for EFSA 2016-2017 visualisation format and CFIA NCRMP multi-pesticide filtering. Florida HFF gets a new candy page entry.

**Tech Stack:** Python 3, pandas, requests, BeautifulSoup, pdfplumber, SQLite

---

## File Structure

| File | Responsibility |
|------|---------------|
| `data/fetchers/sources.py` | FDA, EFSA, CFIA fetcher classes + report registries |
| `data/fetchers/florida_hff.py` | Florida HFF fetcher + report registry |
| `data/db/database.py` | New category aliases for PDP/UK/CA commodities |
| `data/run_pipeline.py` | Source registration for new fetcher classes |
| `data/db/schema.sql` | No changes needed |

---

## Task 1: Expand FDA Registry (FY2014-2022)

**Files:**
- Modify: `data/fetchers/sources.py` — `FDA_REPORTS` list (line ~370)

This is a pure configuration change. The existing `_parse_fda()` method already handles the tab-delimited format generically — it just needs more entries in `FDA_REPORTS`.

- [ ] **Step 1: Add FY2018-2022 entries to FDA_REPORTS**

Add these entries to the `FDA_REPORTS` list in `data/fetchers/sources.py`, before the closing `]`:

```python
FDA_REPORTS = [
    {
        "label": "FDA Pesticide Monitoring FY2023",
        "year": 2023,
        "data_zip": "https://www.fda.gov/media/190132/download?attachment",
        "data_file": "CountryProductResidueData2023.txt",
        "source_url": "https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-report-and-data-fy-2023",
        "published_date": "2025-01-01",
        "data_year": 2023,
    },
    {
        "label": "FDA Pesticide Monitoring FY2022",
        "year": 2022,
        "data_zip": "https://www.fda.gov/media/173001/download?attachment",
        "data_file": "CountryProductResidueData2022.txt",
        "source_url": "https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-report-and-data-fy-2022",
        "published_date": "2024-01-01",
        "data_year": 2022,
    },
    {
        "label": "FDA Pesticide Monitoring FY2021",
        "year": 2021,
        "data_zip": "https://www.fda.gov/media/154646/download?attachment",
        "data_file": "CountryProductResidueData2021.txt",
        "source_url": "https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-report-and-data-fy-2021",
        "published_date": "2023-01-01",
        "data_year": 2021,
    },
    {
        "label": "FDA Pesticide Monitoring FY2020",
        "year": 2020,
        "data_zip": "https://www.fda.gov/media/146495/download?attachment",
        "data_file": "CountryProductResidueData2020.txt",
        "source_url": "https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-report-and-data-fy-2020",
        "published_date": "2022-01-01",
        "data_year": 2020,
    },
    {
        "label": "FDA Pesticide Monitoring FY2019",
        "year": 2019,
        "data_zip": "https://www.fda.gov/media/137916/download?attachment",
        "data_file": "CountryProductResidueData2019.txt",
        "source_url": "https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-report-and-data-fy-2019",
        "published_date": "2021-01-01",
        "data_year": 2019,
    },
    {
        "label": "FDA Pesticide Monitoring FY2018",
        "year": 2018,
        "data_zip": "https://www.fda.gov/media/122853/download?attachment",
        "data_file": "CountryProductResidueData2018.txt",
        "source_url": "https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-report-and-data-fy-2018",
        "published_date": "2020-01-01",
        "data_year": 2018,
    },
    {
        "label": "FDA Pesticide Monitoring FY2017",
        "year": 2017,
        "data_zip": "https://www.fda.gov/media/117065/download?attachment",
        "data_file": "CountryProductResidueData2017.txt",
        "source_url": "https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-2017-report-and-data",
        "published_date": "2019-01-01",
        "data_year": 2017,
    },
    {
        "label": "FDA Pesticide Monitoring FY2016",
        "year": 2016,
        "data_zip": "https://www.fda.gov/media/103392/download?attachment",
        "data_file": "CountryProductResidueData2016.txt",
        "source_url": "https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-2016-report-and-data",
        "published_date": "2018-01-01",
        "data_year": 2016,
    },
    {
        "label": "FDA Pesticide Monitoring FY2015",
        "year": 2015,
        "data_zip": "https://www.fda.gov/media/98503/download?attachment",
        "data_file": "CountryProductResidueData2015.txt",
        "source_url": "https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-2015-report-and-data",
        "published_date": "2017-01-01",
        "data_year": 2015,
    },
    {
        "label": "FDA Pesticide Monitoring FY2014",
        "year": 2014,
        "data_zip": "https://www.fda.gov/media/96395/download?attachment",
        "data_file": "CountryProductResidueData2014.txt",
        "source_url": "https://www.fda.gov/food/pesticides/pesticide-residue-monitoring-2014-report-and-data",
        "published_date": "2016-01-01",
        "data_year": 2014,
    },
]
```

**Note:** The `data_zip` media IDs are best-effort based on FDA's URL patterns. If a specific year's download URL 404s, visit the corresponding `source_url` page to find the correct media link. The fetcher will log a clear error with the failing URL.

- [ ] **Step 2: Update FDA parse to use report-level data_year**

The existing `_parse_fda` method already reads `report["data_year"]` from the report dict and uses it for both the row and the dedup_key. No code change needed — the method already handles multiple years correctly since it loops `for path, report in zip(files, FDA_REPORTS)`.

Verify by reading lines ~425-502 of `sources.py` to confirm the `parse()` method iterates over all report entries.

- [ ] **Step 3: Test FDA expansion**

Run: `cd data && python -c "from fetchers.sources import FDA_REPORTS; print(f'{len(FDA_REPORTS)} FDA report entries'); [print(f'  {r[\"label\"]}') for r in FDA_REPORTS]"`

Expected: `10 FDA report entries` listing FY2014-FY2023.

- [ ] **Step 4: Commit**

```bash
git add data/fetchers/sources.py
git commit -m "feat: expand FDA registry to FY2014-2023 (9 additional years)"
```

---

## Task 2: Expand EFSA Registry (2020-2024 + 2016-2017)

**Files:**
- Modify: `data/fetchers/sources.py` — `EFSA_REPORTS` list and `EFSAFetcher._parse_enforcement()`

- [ ] **Step 1: Add 2020-2024 entries to EFSA_REPORTS**

Add these entries to the `EFSA_REPORTS` list in `data/fetchers/sources.py`:

```python
EFSA_REPORTS = [
    {
        "label": "EFSA EU Pesticide Residue Monitoring 2023",
        "zenodo_record": "14765085",
        "filename": "efsa_2023_enforcement.xlsx",
        "published_date": "2025-01-01",
        "data_year": 2023,
        "source_url": "https://zenodo.org/records/14765085",
        "format": "enforcement",
    },
    {
        "label": "EFSA EU Pesticide Residue Monitoring 2024",
        "zenodo_record": "18327007",
        "filename": "efsa_2024_enforcement.xlsx",
        "published_date": "2026-05-01",
        "data_year": 2024,
        "source_url": "https://zenodo.org/records/18327007",
        "format": "enforcement",
    },
    {
        "label": "EFSA EU Pesticide Residue Monitoring 2022",
        "zenodo_record": "10853986",
        "filename": "efsa_2022_enforcement.xlsx",
        "published_date": "2024-04-01",
        "data_year": 2022,
        "source_url": "https://zenodo.org/records/10853986",
        "format": "enforcement",
    },
    {
        "label": "EFSA EU Pesticide Residue Monitoring 2021",
        "zenodo_record": "7767236",
        "filename": "efsa_2021_enforcement.xlsx",
        "published_date": "2023-04-01",
        "data_year": 2021,
        "source_url": "https://zenodo.org/records/7767236",
        "format": "enforcement",
    },
    {
        "label": "EFSA EU Pesticide Residue Monitoring 2020",
        "zenodo_record": "6410774",
        "filename": "efsa_2020_enforcement.xlsx",
        "published_date": "2022-03-01",
        "data_year": 2020,
        "source_url": "https://zenodo.org/records/6410774",
        "format": "enforcement",
    },
    {
        "label": "EFSA EU Pesticide Monitoring 2017",
        "zenodo_record": "3254912",
        "filename": "efsa_2017_visualisation.xlsx",
        "published_date": "2019-06-01",
        "data_year": 2017,
        "source_url": "https://zenodo.org/records/3254912",
        "format": "visualisation",
    },
    {
        "label": "EFSA EU Pesticide Monitoring 2016",
        "zenodo_record": "1320312",
        "filename": "efsa_2016_visualisation.xlsx",
        "published_date": "2018-07-01",
        "data_year": 2016,
        "source_url": "https://zenodo.org/records/1320312",
        "format": "visualisation",
    },
]
```

- [ ] **Step 2: Update EFSA fetch() to handle visualisation format files**

The existing `_fetch_enforcement()` method searches for XLSX files with "enforcement" in the filename. For visualisation format records, the file name contains "visualisation" or "monitoring" instead. Update the method to handle both:

In `EFSAFetcher._fetch_enforcement()`, replace the xlsx_files search logic (around line ~290) with:

```python
def _fetch_enforcement(self, report: dict) -> Path:
    """Download enforcement or visualisation data XLSX from Zenodo."""
    cache_path = Path(__file__).parent.parent / "raw_data" / report["filename"]

    if cache_path.exists():
        logger.info("Cache hit: %s", cache_path.name)
        return cache_path

    record_id = report["zenodo_record"]
    api_url = EFSA_ZENODO_API.format(record_id=record_id)
    resp = SESSION.get(api_url, timeout=30)
    resp.raise_for_status()
    record_data = resp.json()

    files = record_data.get("files", [])
    fmt = report.get("format", "enforcement")

    if fmt == "enforcement":
        # Find enforcement XLSX files
        xlsx_files = [
            f for f in files
            if f.get("key", "").lower().endswith(".xlsx")
            and "enforcement" in f.get("key", "").lower()
        ]
        if not xlsx_files:
            xlsx_files = [f for f in files if f.get("key", "").lower().endswith(".xlsx")]
    else:
        # Visualisation format: look for the main monitoring XLSX
        xlsx_files = [
            f for f in files
            if f.get("key", "").lower().endswith(".xlsx")
            and "monitoring" in f.get("key", "").lower()
        ]
        if not xlsx_files:
            xlsx_files = [f for f in files if f.get("key", "").lower().endswith(".xlsx")]

    if not xlsx_files:
        raise RuntimeError(f"No XLSX files found in Zenodo record {record_id}")

    # Pick the smallest XLSX for enforcement, largest for visualisation
    if fmt == "enforcement":
        data_file = min(xlsx_files, key=lambda f: f.get("size", 0))
    else:
        data_file = max(xlsx_files, key=lambda f: f.get("size", 0))

    download_url = data_file.get("links", {}).get("self")
    if not download_url:
        raise RuntimeError(f"No download URL for {data_file.get('key','')}")

    return download_file(download_url, report["filename"])
```

- [ ] **Step 3: Add visualisation format parser branch to EFSA**

The visualisation XLSX (2016-2017) has a different structure than the enforcement annex. Add a new method `_parse_visualisation()` and update `parse()` to route based on format.

In `EFSAFetcher.parse()`, replace the current implementation with:

```python
def parse(self, files: list[Path]) -> list[dict]:
    all_rows = []
    for path, report in zip(files, EFSA_REPORTS):
        fmt = report.get("format", "enforcement")
        if fmt == "visualisation":
            rows = self._parse_visualisation(path, report)
        else:
            rows = self._parse_enforcement(path, report)
        all_rows.extend(rows)
    return all_rows
```

Add the new `_parse_visualisation()` method to `EFSAFetcher`:

```python
def _parse_visualisation(self, xlsx_path: Path, report: dict) -> list[dict]:
    """
    Parse EFSA visualisation XLSX (2016-2017 format).
    These files contain per-country per-commodity residue statistics
    in a different layout than the enforcement annexes.
    Structure varies by sheet — we look for sheets with glyphosate data.
    """
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    all_rows = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows_iter = ws.iter_rows(values_only=True)

        # Find header row
        headers = None
        for row in rows_iter:
            row_str = [str(c).lower() if c else "" for c in row]
            if any("glyphosate" in s for s in row_str):
                headers = [str(c).strip() if c else "" for c in row]
                break
            if any("substance" in s for s in row_str) and any("commodity" in s or "product" in s or "matrix" in s for s in row_str):
                headers = [str(c).strip() if c else "" for c in row]
                break

        if not headers:
            continue

        headers_lower = [h.lower() for h in headers]

        # Find relevant columns
        substance_col = next((i for i, h in enumerate(headers_lower) if "substance" in h), None)
        commodity_col = next((i for i, h in enumerate(headers_lower) if any(t in h for t in ["commodity", "matrix", "product", "food"])), None)
        result_col = next((i for i, h in enumerate(headers_lower) if any(t in h for t in ["result", "value", "concentration", "mean", "level"])), None)
        samples_col = next((i for i, h in enumerate(headers_lower) if any(t in h for t in ["sample", "number", "total", "analysed"])), None)

        if substance_col is None or commodity_col is None:
            continue

        for row in rows_iter:
            if row[commodity_col] is None:
                continue
            substance = str(row[substance_col] or "").lower()
            if "glyphosate" not in substance or "ampa" in substance.split():
                continue

            raw_cat = str(row[commodity_col]).strip()
            food_category = normalize_category(raw_cat)
            if not food_category:
                continue

            total = int(row[samples_col]) if samples_col is not None and row[samples_col] else None
            result_val = None
            if result_col is not None and row[result_col] is not None:
                try:
                    result_val = float(row[result_col])
                except (ValueError, TypeError):
                    pass

            # Visualisation data may use mg/kg
            avg_ppb = round(result_val * 1000, 2) if result_val else None
            max_ppb = avg_ppb  # Only one value available in visualisation

            all_rows.append({
                "tier": 2,
                "source_name": "EFSA",
                "source_url": report["source_url"],
                "report_label": report["label"],
                "published_date": report["published_date"],
                "data_year": report["data_year"],
                "food_category": food_category,
                "raw_category": raw_cat,
                "samples_total": total or 1,
                "samples_detected": 1,
                "detection_rate": None,
                "avg_ppb": avg_ppb,
                "max_ppb": max_ppb,
                "original_unit": "mg/kg",
                "unit_conversion": 1000.0,
                "methodology_note": (
                    f"EFSA visualisation data ({report['data_year']}). "
                    "Aggregated statistics per commodity. "
                    "Detection rate not available in this format."
                ),
                "confidence": "low",
                "raw_file_path": str(xlsx_path),
                "dedup_key": build_dedup_key("EFSA", food_category, report["data_year"]),
            })

    wb.close()
    logger.info("EFSA visualisation: parsed %d rows from %s", len(all_rows), xlsx_path.name)
    return all_rows
```

- [ ] **Step 4: Install openpyxl if needed**

Run: `cd "F:\Projects\Arasheed\Glyphosate Detection" && pip install openpyxl`

- [ ] **Step 5: Test EFSA expansion**

Run: `cd data && python -c "from fetchers.sources import EFSA_REPORTS; print(f'{len(EFSA_REPORTS)} EFSA report entries'); [print(f'  {r[\"label\"]} ({r.get(\"format\", \"enforcement\")})') for r in EFSA_REPORTS]"`

Expected: `7 EFSA report entries` listing 2016-2024 with format annotations.

- [ ] **Step 6: Commit**

```bash
git add data/fetchers/sources.py
git commit -m "feat: expand EFSA registry to 2016-2024 with visualisation format support"
```

---

## Task 3: Expand Florida HFF — Candy Category

**Files:**
- Modify: `data/fetchers/florida_hff.py` — `FLORIDA_REPORTS` list (line ~38)

- [ ] **Step 1: Add candy page to FLORIDA_REPORTS**

Add this entry to the `FLORIDA_REPORTS` list in `data/fetchers/florida_hff.py`:

```python
    {
        "label": "Florida HFF Candy Glyphosate 2026",
        "url": "https://web.archive.org/web/20260414123704/https://exposingfoodtoxins.com/candy/",
        "filename": "florida_hff_candy_2026.html",
        "published_date": "2026-02-01",
        "data_year": 2026,
        "category_hint": "corn",
    },
```

**Note:** The `category_hint` is `"corn"` because most candy products (especially gummy candies, candy corn) are corn-syrup-based. The `_infer_raw_category()` method will handle specific product names that match other categories (e.g., "chocolate" → could be added to wheat, "gummy" → corn).

- [ ] **Step 2: Add candy-related category inference rules**

In `FloridaHFFetcher._infer_raw_category()`, add candy-related patterns before the final `return hint` line:

```python
        if any(t in name_lower for t in ["candy", "gummy", "gummies", "licorice", "twizzler"]):
            return "corn"
        if any(t in name_lower for t in ["chocolate", "cocoa"]):
            return "soybeans"
```

- [ ] **Step 3: Test Florida HFF expansion**

Run: `cd data && python -c "from fetchers.florida_hff import FLORIDA_REPORTS; print(f'{len(FLORIDA_REPORTS)} Florida report entries'); [print(f'  {r[\"label\"]}') for r in FLORIDA_REPORTS]"`

Expected: `3 Florida report entries` listing bread, infant formula, candy.

- [ ] **Step 4: Commit**

```bash
git add data/fetchers/florida_hff.py
git commit -m "feat: add Florida HFF candy category to report registry"
```

---

## Task 4: Add New Category Aliases

**Files:**
- Modify: `data/db/database.py` — `_seed_category_aliases()` function (line ~120)

- [ ] **Step 1: Add aliases for new commodities**

Add these aliases to the `aliases` dict in `_seed_category_aliases()`, grouped logically:

```python
        # ── Butter (from USDA PDP) ────────────────────────────────────────
        "butter": "butter", "dairy butter": "butter",
        # ── Blueberries (from USDA PDP) ───────────────────────────────────
        "blueberry": "blueberries", "blueberries": "blueberries",
        "cultivated blueberries": "blueberries", "wild blueberries": "blueberries",
        # ── Canned beets (from USDA PDP) ──────────────────────────────────
        "canned beets": "canned_beets", "beets canned": "canned_beets",
        "beet": "canned_beets", "beets": "canned_beets",
        # ── Candy/snacks ──────────────────────────────────────────────────
        "candy": "corn", "confectionery": "corn",
        # ── Protein products ─────────────────────────────────────────────
        "protein bar": "soybeans", "protein powder": "soybeans",
        "pea protein": "soybeans",
        # ── UK-specific terms ─────────────────────────────────────────────
        "cereals": "wheat", "cereal": "wheat",
        "bread and rolls": "wheat",
        "breakfast cereal": "oats",
        # ── Additional grains ─────────────────────────────────────────────
        "millet": "corn", "sorghum": "corn",
        # ── Additional produce ────────────────────────────────────────────
        "strawberries": "fresh_fruit", "grapes": "fresh_fruit",
        "bananas": "fresh_fruit", "tomatoes": "fresh_vegetables",
        "potatoes": "fresh_vegetables", "carrots": "fresh_vegetables",
        "onions": "fresh_vegetables", "peppers": "fresh_vegetables",
        "cucumbers": "fresh_vegetables", "celery": "fresh_vegetables",
        "broccoli": "fresh_vegetables", "cabbage": "fresh_vegetables",
        "mushrooms": "fresh_vegetables",
        # ── Additional fruit ──────────────────────────────────────────────
        "oranges": "fresh_fruit", "pears": "fresh_fruit",
        "peaches": "fresh_fruit", "cherries": "fresh_fruit",
        "cranberries": "fresh_fruit", "raspberries": "fresh_fruit",
        # ── German terms (for BVL) ────────────────────────────────────────
        "getreide": "wheat", "hafer": "oats", "soja": "soybeans",
        "mais": "corn", "gerste": "barley", "roggen": "rye",
        "reis": "rice", "hülsenfrüchte": "beans",
        # ── General produce groups ────────────────────────────────────────
        "oilseeds": "canola", "nuts": "fresh_fruit",
        "dried fruit": "fresh_fruit", "juice": "fresh_fruit",
        "processed food": "wheat", "snacks": "corn",
        "crackers": "wheat", "chips": "corn",
        "granola": "oats", "muesli": "oats",
```

- [ ] **Step 2: Test aliases load correctly**

Run: `cd data && python -c "from db.database import initialize; initialize(); print('Aliases seeded OK')"`

Expected: `Aliases seeded OK` with no errors.

- [ ] **Step 3: Commit**

```bash
git add data/db/database.py
git commit -m "feat: add category aliases for PDP, UK, CA, German, and candy commodities"
```

---

## Task 5: Expand CFIA — NCRMP + Targeted Surveys

**Files:**
- Modify: `data/fetchers/sources.py` — Add `CFIA_REPORTS` registry and update `CFIAFetcher`

- [ ] **Step 1: Add CFIA_REPORTS registry and convert CFIA to multi-report**

The current `CFIAFetcher` fetches a single hardcoded CSV. Convert it to use a report registry like FDA and EFSA, while keeping backward compatibility with the original dataset.

Add this registry before `class CFIAFetcher`:

```python
CFIA_REPORTS = [
    {
        "label": "CFIA Glyphosate Testing 2015-2017",
        "type": "glyphosate_csv",
        "csv_url": (
            "https://open.canada.ca/data/dataset/"
            "906cd35c-d396-4999-9a9f-f5351796661f/resource/"
            "glyphosate_food_residues_2015_2017.csv"
        ),
        "portal_url": (
            "https://open.canada.ca/data/en/dataset/"
            "906cd35c-d396-4999-9a9f-f5351796661f"
        ),
        "filename": "cfia_glyphosate_2015_2017.csv",
        "published_date": "2019-04-01",
        "data_year": 2017,
    },
    {
        "label": "CFIA NCRMP 2021-2022",
        "type": "ncrmp_csv",
        "portal_url": "https://open.canada.ca/data/en/dataset/6567ac46-558e-4c95-ab93-e8326ddf8f90",
        "filename": "cfia_ncrmp_2021_2022.csv",
        "published_date": "2023-01-01",
        "data_year": 2022,
    },
    {
        "label": "CFIA NCRMP 2020-2021",
        "type": "ncrmp_csv",
        "portal_url": "https://open.canada.ca/data/en/dataset/a5cb7c3c-0371-4a20-ac9a-98fc4c3536bb",
        "filename": "cfia_ncrmp_2020_2021.csv",
        "published_date": "2022-01-01",
        "data_year": 2021,
    },
    {
        "label": "CFIA NCRMP 2019-2020",
        "type": "ncrmp_csv",
        "portal_url": "https://open.canada.ca/data/en/dataset/9e5211c8-c11f-4ebe-a7b2-65a6799a6032",
        "filename": "cfia_ncrmp_2019_2020.csv",
        "published_date": "2021-01-01",
        "data_year": 2020,
    },
    {
        "label": "CFIA NCRMP 2018-2019",
        "type": "ncrmp_csv",
        "portal_url": "https://open.canada.ca/data/en/dataset/a2ea8989-2211-4d19-bc54-199dbd4c78ca",
        "filename": "cfia_ncrmp_2018_2019.csv",
        "published_date": "2020-01-01",
        "data_year": 2019,
    },
    {
        "label": "CFIA NCRMP 2017-2018",
        "type": "ncrmp_csv",
        "portal_url": "https://open.canada.ca/data/en/dataset/c87af563-b3f3-4048-96af-a5d39723ea6b",
        "filename": "cfia_ncrmp_2017_2018.csv",
        "published_date": "2019-01-01",
        "data_year": 2018,
    },
    {
        "label": "CFIA NCRMP 2016-2017",
        "type": "ncrmp_csv",
        "portal_url": "https://open.canada.ca/data/en/dataset/95a14ca0-706c-4422-ad42-b9e86998efbe",
        "filename": "cfia_ncrmp_2016_2017.csv",
        "published_date": "2018-01-01",
        "data_year": 2017,
    },
    {
        "label": "CFIA Grain Products Survey 2016-2017",
        "type": "targeted_csv",
        "portal_url": "https://open.canada.ca/data/en/dataset/21429139-d023-4090-b5de-50384cda44c8",
        "filename": "cfia_grain_2016_2017.csv",
        "published_date": "2018-01-01",
        "data_year": 2017,
    },
    {
        "label": "CFIA Children's Food Project 2017",
        "type": "targeted_csv",
        "portal_url": "https://open.canada.ca/data/en/dataset/61a82716-e863-4c20-b1a7-c8e05e70e72d",
        "filename": "cfia_children_2017.csv",
        "published_date": "2018-01-01",
        "data_year": 2017,
    },
    {
        "label": "CFIA Selected Foods Survey 2018-2019",
        "type": "targeted_csv",
        "portal_url": "https://open.canada.ca/data/en/dataset/e4194282-102a-40ec-ac4c-0ce20e9a33cf",
        "filename": "cfia_selected_2018_2019.csv",
        "published_date": "2020-01-01",
        "data_year": 2019,
    },
]
```

- [ ] **Step 2: Rewrite CFIA fetch() to use the registry**

Replace the existing `CFIAFetcher.fetch()` method with:

```python
class CFIAFetcher(BaseFetcher):
    SOURCE_NAME = "CFIA"

    def fetch(self) -> list[Path]:
        paths = []
        for report in CFIA_REPORTS:
            rtype = report["type"]
            if rtype == "glyphosate_csv":
                path = self._fetch_glyphosate_csv(report)
            else:
                path = self._fetch_portal_csv(report)
            if path:
                paths.append(path)
        return paths

    def _fetch_glyphosate_csv(self, report: dict) -> Path:
        """Download the original glyphosate-specific CSV."""
        try:
            return download_file(report["csv_url"], report["filename"])
        except Exception as e:
            logger.warning("Direct CSV URL failed: %s — trying portal page", e)
            return self._fetch_via_portal(report)

    def _fetch_portal_csv(self, report: dict) -> Path | None:
        """Scrape Open Government Portal to find CSV download link."""
        cache_path = RAW_DATA_DIR / report["filename"]
        if cache_path.exists():
            logger.info("Cache hit: %s", report["filename"])
            return cache_path

        try:
            from bs4 import BeautifulSoup
            html = fetch_page(report["portal_url"])
            soup = BeautifulSoup(html, "html.parser")

            csv_links = [
                a["href"] for a in soup.find_all("a", href=True)
                if a["href"].endswith(".csv")
            ]
            if not csv_links:
                logger.warning("No CSV found on portal for %s", report["label"])
                return None

            csv_url = csv_links[0]
            if not csv_url.startswith("http"):
                csv_url = "https://open.canada.ca" + csv_url

            return download_file(csv_url, report["filename"])
        except Exception as e:
            logger.error("Failed to fetch %s: %s", report["label"], e)
            return None
```

- [ ] **Step 3: Rewrite CFIA parse() to handle multiple report types**

Replace the existing `CFIAFetcher.parse()` and add NCRMP/targeted parsing:

```python
    def parse(self, files: list[Path]) -> list[dict]:
        all_rows = []
        for path, report in zip(files, CFIA_REPORTS):
            if path is None:
                continue
            rtype = report["type"]
            if rtype == "glyphosate_csv":
                rows = self._parse_glyphosate_csv(path, report)
            elif rtype in ("ncrmp_csv", "targeted_csv"):
                rows = self._parse_multi_pesticide_csv(path, report)
            else:
                logger.warning("Unknown CFIA report type: %s", rtype)
                continue
            all_rows.extend(rows)
        return all_rows
```

Keep the existing `parse()` logic as `_parse_glyphosate_csv()` (rename the current method). Add a new method for multi-pesticide files:

```python
    def _parse_glyphosate_csv(self, csv_path: Path, report: dict) -> list[dict]:
        """Parse the original glyphosate-specific CSV (2015-2017)."""
        # Same logic as the existing parse() method, but using report dict
        # for metadata instead of module-level constants.
        df = pd.read_csv(csv_path, low_memory=False)
        df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]
        logger.info("CFIA columns: %s", list(df.columns))

        product_col   = self._find_col(df, ["product", "produit", "commodity", "food_category"])
        component_col = self._find_col(df, ["component", "composant", "pesticide", "substance"])
        result_col    = self._find_col(df, ["result", "r_sultat", "concentration", "value"])
        if not result_col:
            result_col = next((c for c in df.columns if "result" in c or "rsultat" in c), None)
        unit_col = self._find_col(df, ["reportunit", "unit"])

        if not product_col or not component_col or not result_col:
            raise ValueError(
                f"Required columns not found in CFIA CSV. "
                f"Available: {list(df.columns)}."
            )

        gly_df = df[df[component_col].str.lower().str.contains("glyphosate", na=False)].copy()
        if gly_df.empty:
            raise ValueError("No glyphosate rows found in CFIA CSV")

        logger.info("CFIA: %d glyphosate sample rows", len(gly_df))

        conversion = 1.0
        original_unit = "µg/g"
        if unit_col:
            unit_val = str(gly_df[unit_col].iloc[0]).lower()
            if "mg/kg" in unit_val or "µg/g" in unit_val or "ug/g" in unit_val:
                conversion = 1000.0
                original_unit = unit_val

        rows = []
        product_stats = []
        for product, group in gly_df.groupby(product_col):
            raw_cat = str(product).strip()
            if not raw_cat or raw_cat.lower() in ("nan", "total", "all"):
                continue
            food_category = normalize_category(raw_cat)
            if not food_category:
                continue
            values = pd.to_numeric(group[result_col], errors="coerce").fillna(0)
            product_stats.append({
                "food_category": food_category,
                "raw_cat": raw_cat,
                "total": len(group),
                "detected_values": values[values > 0].tolist(),
            })

        from collections import defaultdict
        by_category = defaultdict(lambda: {"total": 0, "detected": [], "raw_cats": []})
        for ps in product_stats:
            cat = ps["food_category"]
            by_category[cat]["total"] += ps["total"]
            by_category[cat]["detected"].extend(ps["detected_values"])
            by_category[cat]["raw_cats"].append(ps["raw_cat"])

        for food_category, stats in by_category.items():
            total = stats["total"]
            n_detected = len(stats["detected"])
            detection_rate = round(n_detected / total, 4) if total > 0 else None
            avg_ppb = round(sum(stats["detected"]) / n_detected * conversion, 2) if n_detected > 0 else None
            max_ppb = round(max(stats["detected"]) * conversion, 2) if stats["detected"] else None
            raw_cat = ", ".join(sorted(set(stats["raw_cats"])))

            rows.append({
                "tier": 2,
                "source_name": "CFIA",
                "source_url": CFIA_SOURCE_URL,
                "report_label": report["label"],
                "published_date": report["published_date"],
                "data_year": report["data_year"],
                "food_category": food_category,
                "raw_category": raw_cat,
                "samples_total": total,
                "samples_detected": n_detected,
                "detection_rate": detection_rate,
                "avg_ppb": avg_ppb,
                "max_ppb": max_ppb,
                "original_unit": original_unit,
                "unit_conversion": conversion,
                "methodology_note": (
                    f"{report['label']}. Individual sample results aggregated by "
                    "canonical food category. LC-MS/MS method."
                ),
                "confidence": "medium",
                "raw_file_path": str(csv_path),
                "dedup_key": build_dedup_key("CFIA", food_category, report["data_year"]),
            })

        logger.info("CFIA: parsed %d category rows from %s", len(rows), report["label"])
        return rows

    def _parse_multi_pesticide_csv(self, csv_path: Path, report: dict) -> list[dict]:
        """
        Parse NCRMP or targeted survey CSVs that contain multiple pesticides.
        Filters for glyphosate rows only, then aggregates by food category.
        Column names may vary between datasets.
        """
        df = pd.read_csv(csv_path, low_memory=False)
        df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]
        logger.info("CFIA %s columns: %s", report["type"], list(df.columns))

        # Find the pesticide/substance column
        pest_col = self._find_col(df, [
            "pesticide", "substance", "param_name", "analyte",
            "chemical", "compound", "pesticide_name", "active_substance",
        ])
        if not pest_col:
            logger.warning("CFIA: no pesticide column found in %s — skipping", report["label"])
            return []

        # Filter for glyphosate
        gly_df = df[df[pest_col].str.lower().str.contains("glyphosate", na=False)].copy()
        if gly_df.empty:
            logger.info("CFIA: no glyphosate rows in %s", report["label"])
            return []

        # Also filter OUT AMPA if it appears as a separate row
        gly_df = gly_df[~gly_df[pest_col].str.lower().str.contains("ampa", na=False)]
        if gly_df.empty:
            logger.info("CFIA: no glyphosate rows (only AMPA) in %s", report["label"])
            return []

        logger.info("CFIA: %d glyphosate rows in %s", len(gly_df), report["label"])

        # Find product/commodity column
        product_col = self._find_col(df, [
            "product", "commodity", "food", "matrix", "product_name",
            "commodity_name", "food_product", "sample_type",
        ])
        if not product_col:
            logger.warning("CFIA: no product column found in %s — skipping", report["label"])
            return []

        # Find result/value column
        result_col = self._find_col(df, [
            "result", "value", "concentration", "level", "residue",
            "detected_concentration", "measured_value",
        ])
        if not result_col:
            result_col = next((c for c in df.columns if "result" in c or "value" in c), None)

        # Find unit column
        unit_col = self._find_col(df, ["unit", "units", "result_unit"])

        # Determine conversion factor
        conversion = 1000.0  # default: assume mg/kg → ppb
        original_unit = "mg/kg"
        if unit_col:
            unit_val = str(gly_df[unit_col].iloc[0]).lower()
            if "ppb" in unit_val or "µg/kg" in unit_val or "ug/kg" in unit_val:
                conversion = 1.0
                original_unit = unit_val
            elif "ppm" in unit_val or "mg/kg" in unit_val:
                conversion = 1000.0
                original_unit = unit_val

        # Aggregate by canonical category
        from collections import defaultdict
        by_category = defaultdict(lambda: {"total": 0, "detected": [], "raw_cats": []})

        for product, group in gly_df.groupby(product_col):
            raw_cat = str(product).strip()
            if not raw_cat or raw_cat.lower() in ("nan", "total", "all"):
                continue
            food_category = normalize_category(raw_cat)
            if not food_category:
                continue

            total = len(group)
            if result_col:
                values = pd.to_numeric(group[result_col], errors="coerce").fillna(0)
                detected = values[values > 0].tolist()
            else:
                detected = []

            by_category[food_category]["total"] += total
            by_category[food_category]["detected"].extend(detected)
            by_category[food_category]["raw_cats"].append(raw_cat)

        rows = []
        for food_category, stats in by_category.items():
            total = stats["total"]
            n_detected = len(stats["detected"])
            detection_rate = round(n_detected / total, 4) if total > 0 else None
            avg_ppb = round(sum(stats["detected"]) / n_detected * conversion, 2) if n_detected > 0 else None
            max_ppb = round(max(stats["detected"]) * conversion, 2) if stats["detected"] else None
            raw_cat = ", ".join(sorted(set(stats["raw_cats"])))

            rows.append({
                "tier": 2,
                "source_name": "CFIA",
                "source_url": report["portal_url"],
                "report_label": report["label"],
                "published_date": report["published_date"],
                "data_year": report["data_year"],
                "food_category": food_category,
                "raw_category": raw_cat,
                "samples_total": total,
                "samples_detected": n_detected,
                "detection_rate": detection_rate,
                "avg_ppb": avg_ppb,
                "max_ppb": max_ppb,
                "original_unit": original_unit,
                "unit_conversion": conversion,
                "methodology_note": (
                    f"{report['label']}. Multi-pesticide dataset filtered for glyphosate. "
                    "Individual sample results aggregated by canonical food category."
                ),
                "confidence": "medium",
                "raw_file_path": str(csv_path),
                "dedup_key": build_dedup_key("CFIA", food_category, report["data_year"]),
            })

        logger.info("CFIA: parsed %d category rows from %s", len(rows), report["label"])
        return rows
```

- [ ] **Step 4: Remove old module-level constants that are now in the registry**

Remove or keep as fallbacks: `CFIA_GOV_PORTAL_URL`, `CFIA_CSV_URL`, `CFIA_FILENAME`. The original glyphosate CSV is now the first entry in `CFIA_REPORTS`. Keep `CFIA_SOURCE_URL` as it's used in methodology notes.

- [ ] **Step 5: Test CFIA expansion**

Run: `cd data && python -c "from fetchers.sources import CFIA_REPORTS; print(f'{len(CFIA_REPORTS)} CFIA report entries'); [print(f'  {r[\"label\"]} ({r[\"type\"]})') for r in CFIA_REPORTS]"`

Expected: `10 CFIA report entries` listing original + NCRMP + targeted surveys.

- [ ] **Step 6: Commit**

```bash
git add data/fetchers/sources.py
git commit -m "feat: expand CFIA to NCRMP + targeted surveys with multi-pesticide filtering"
```

---

## Task 6: Run Pipeline and Validate

**Files:** None — execution only

- [ ] **Step 1: Delete existing database for clean run**

Run: `cd "F:\Projects\Arasheed\Glyphosate Detection\data" && del residueiq.db`

This ensures all new registry entries get ingested cleanly.

- [ ] **Step 2: Run the full pipeline**

Run: `cd "F:\Projects\Arasheed\Glyphosate Detection\data" && python run_pipeline.py --validate`

Expected: All sources complete. FDA should show glyphosate rows for each FY that actually contained glyphosate data (not all years will have it). EFSA should parse both enforcement and visualisation formats. CFIA should parse the original glyphosate CSV. Florida should include candy data.

**Note:** NCRMP/targeted CSVs may fail to download if CFIA's portal structure doesn't directly expose CSV download links. The fetcher logs clear warnings for any failures. This is expected — the portal scrape may need manual URL discovery for some datasets.

- [ ] **Step 3: Check record counts**

Run: `cd "F:\Projects\Arasheed\Glyphosate Detection\data" && python -c "
import sqlite3
conn = sqlite3.connect('residueiq.db')
total = conn.execute('SELECT COUNT(*) FROM glyphosate_measurements').fetchone()[0]
t1 = conn.execute('SELECT COUNT(*) FROM glyphosate_measurements WHERE tier=1').fetchone()[0]
t2 = conn.execute('SELECT COUNT(*) FROM glyphosate_measurements WHERE tier=2').fetchone()[0]
sources = conn.execute('SELECT source_name, COUNT(*) FROM glyphosate_measurements GROUP BY source_name').fetchall()
cats = conn.execute('SELECT COUNT(DISTINCT food_category) FROM glyphosate_measurements').fetchone()[0]
years = conn.execute('SELECT MIN(data_year), MAX(data_year) FROM glyphosate_measurements').fetchone()
print(f'Total: {total} (Tier1: {t1}, Tier2: {t2})')
print(f'Categories: {cats}, Years: {years[0]}-{years[1]}')
for name, count in sources:
    print(f'  {name}: {count}')
conn.close()
"`

Expected: Significantly more records than the original 126. Year range should span FY2014-FY2026. More categories covered.

- [ ] **Step 4: Commit final state**

If validation passed and counts look reasonable:

```bash
git add -A
git commit -m "feat: batch 1-2 data expansion complete — FDA, EFSA, CFIA, Florida HFF multi-year"
```

---

## Self-Review Checklist

- [ ] **Spec coverage:** FDA (9 years) → Task 1. EFSA (7 years + visualisation) → Task 2. Florida candy → Task 3. CFIA NCRMP + targeted → Task 5. New aliases → Task 4. Pipeline run → Task 6.
- [ ] **Placeholder scan:** No TBDs, TODOs, or "implement later" patterns. All code shown inline.
- [ ] **Type consistency:** All methods use `report: dict` parameter. All return `list[dict]`. `build_dedup_key()` calls match the existing pattern. Column name lists are explicit.
- [ ] **Missing items:** The FDA media download URLs are best-effort — noted in Step 1. The CFIA NCRMP portal scraping may not find direct CSV links for all datasets — noted in Task 6.
