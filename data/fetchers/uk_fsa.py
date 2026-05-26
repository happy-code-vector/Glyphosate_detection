"""
fetchers/uk_fsa.py

UK FSA / PRiF (Pesticide Residues in Food) Monitoring Programme -- Tier 2 data.

Sources:
  UK PRiF annual monitoring data published as ODS (OpenDocument Spreadsheet)
  files hosted on Defra's S3 bucket:
    https://s3.eu-west-1.amazonaws.com/data.defra.gov.uk/PRIF/

  The collection page at gov.uk describes the programme:
    https://www.gov.uk/government/collections/pesticide-residues-in-food-results-of-monitoring-programme

  Data files are downloaded directly from S3. Each annual ODS file is a
  multi-sheet workbook. Sheets follow the pattern:
    - {Food}_BNA  : Brand Name Annex -- individual sample rows. The pesticide
                    residue column contains free-text like "glyphosate 0.2 (MRL = 1.6)".
    - {Food}_SUM / _ST : Summary tables with per-pesticide rows (pesticide name
                    in column 0, LOD / detection count in columns 1-2).
    - Analyte_Detections (2019-2020): overall totals without food breakdown.
    - Summary : introductory text (0 rows of data).

  Glyphosate data is found by scanning ALL sheets for cells containing
  "glyphosate" (case-insensitive), then parsing the value and aggregating
  by canonical food category derived from the sheet name.

No values are hardcoded. All ppb values come from downloaded data files.
"""

import logging
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

from fetchers.base import BaseFetcher, download_file, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

# Entry-point collection page for UK PRiF monitoring results (used as source_url).
COLLECTION_URL = (
    "https://www.gov.uk/government/collections/"
    "pesticide-residues-in-food-results-of-monitoring-programme"
)

# Direct S3 download URLs for annual PRiF ODS data files.
# Verified 2025-05: all URLs return valid ODS files from Defra's S3 bucket.
UK_FSA_REPORTS = [
    {
        "label": "UK PRiF Monitoring 2016",
        "data_year": 2016,
        "published_date": "2017-06-01",
        "url": "https://s3.eu-west-1.amazonaws.com/data.defra.gov.uk/PRIF/2016_annual_data.ods",
        "filename": "uk_fsa_2016_annual_data.ods",
    },
    {
        "label": "UK PRiF Monitoring 2017",
        "data_year": 2017,
        "published_date": "2018-06-01",
        "url": "https://s3.eu-west-1.amazonaws.com/data.defra.gov.uk/PRIF/2017_annual_data.ods",
        "filename": "uk_fsa_2017_annual_data.ods",
    },
    {
        "label": "UK PRiF Monitoring 2018",
        "data_year": 2018,
        "published_date": "2019-06-01",
        "url": "https://s3.eu-west-1.amazonaws.com/data.defra.gov.uk/PRIF/2018_annual_data_v2.ods",
        "filename": "uk_fsa_2018_annual_data_v2.ods",
    },
    {
        "label": "UK PRiF Monitoring 2019",
        "data_year": 2019,
        "published_date": "2020-06-01",
        "url": "https://s3.eu-west-1.amazonaws.com/data.defra.gov.uk/PRIF/2019_annual_data.ods",
        "filename": "uk_fsa_2019_annual_data.ods",
    },
    {
        "label": "UK PRiF Monitoring 2020",
        "data_year": 2020,
        "published_date": "2021-06-01",
        "url": "https://s3.eu-west-1.amazonaws.com/data.defra.gov.uk/PRIF/2020_prif_Annual.ods",
        "filename": "uk_fsa_2020_prif_annual.ods",
    },
    {
        "label": "UK PRiF Monitoring 2021",
        "data_year": 2021,
        "published_date": "2022-06-01",
        "url": "https://s3.eu-west-1.amazonaws.com/data.defra.gov.uk/PRIF/2021_annual_data.ods",
        "filename": "uk_fsa_2021_annual_data.ods",
    },
    {
        "label": "UK PRiF Monitoring 2022",
        "data_year": 2022,
        "published_date": "2023-06-01",
        "url": "https://s3.eu-west-1.amazonaws.com/data.defra.gov.uk/PRIF/2022_PRiF_Annual_Data.ods",
        "filename": "uk_fsa_2022_prif_annual_data.ods",
    },
    {
        "label": "UK PRiF Monitoring 2023 GB",
        "data_year": 2023,
        "published_date": "2024-06-01",
        "url": "https://s3.eu-west-1.amazonaws.com/data.defra.gov.uk/PRIF/2023+GB+ODS.ods",
        "filename": "uk_fsa_2023_gb.ods",
    },
    {
        "label": "UK PRiF Monitoring 2023 NI",
        "data_year": 2023,
        "published_date": "2024-06-01",
        "url": "https://s3.eu-west-1.amazonaws.com/data.defra.gov.uk/PRIF/2023+NI+ODS.ods",
        "filename": "uk_fsa_2023_ni.ods",
    },
    {
        "label": "UK PRiF Monitoring 2024 GB",
        "data_year": 2024,
        "published_date": "2025-06-01",
        "url": "https://s3.eu-west-1.amazonaws.com/data.defra.gov.uk/PRIF/2024+GB+ODS.ods",
        "filename": "uk_fsa_2024_gb.ods",
    },
    {
        "label": "UK PRiF Monitoring 2024 NI",
        "data_year": 2024,
        "published_date": "2025-06-01",
        "url": "https://s3.eu-west-1.amazonaws.com/data.defra.gov.uk/PRIF/2024+NI+ODS.ods",
        "filename": "uk_fsa_2024_ni.ods",
    },
]

# Column name candidates for dynamic column detection.
# UK PRiF ODS files may use various column names across years.
SUBSTANCE_COL_CANDIDATES = [
    "pesticide", "substance", "pesticide_name", "active_substance",
    "param_name", "analyte", "chemical", "compound", "res_name",
    "name_of_pesticide", "pesticide_residue_name", "residue",
]
COMMODITY_COL_CANDIDATES = [
    "commodity", "food", "product", "matrix", "commodity_name",
    "food_name", "product_name", "sample_type", "sample_description",
    "description", "food_commodity", "sampled_food", "food_product",
    "food_group",
]
RESULT_COL_CANDIDATES = [
    "result", "value", "concentration", "level", "residue_level",
    "measured_value", "amount", "detected_concentration", "residue_value",
    "result_value", "mgkg", "res", "quantification",
]

# Regex to extract glyphosate concentration from free-text BNA cells.
# Matches patterns like: "glyphosate 0.2 (MRL = 1.6)" or "glyphosate 0.07 (MRL = 0.1*)"
_GLY_VALUE_RE = re.compile(
    r"glyphosate\s+(?:sum\s+)?(\d+\.?\d*)\s*\((?:MRL|LOD)",
    re.IGNORECASE,
)

# Regex to extract LOD from SUM sheet cells like "glyphosate (0.05)" or "<0.05"
_GLY_LOD_RE = re.compile(
    r"glyphosate\s*\((\d+\.?\d*)\)",
    re.IGNORECASE,
)

# Regex to detect "not found" / "below LOD" patterns in SUM sheets
_NOT_FOUND_RE = re.compile(
    r"<\d+\.?\d*\s*\(i\.e\.\s*not\s*found\)",
    re.IGNORECASE,
)


def _get_ods_engine():
    """
    Return a pandas Excel engine name for reading .ods files.
    Tries 'odf' (odfpy), then 'ezodf', raising ImportError with
    a clear message if neither is available.
    """
    try:
        import odf  # noqa: F401
        return "odf"
    except ImportError:
        pass
    try:
        import ezodf  # noqa: F401
        return "ezodf"
    except ImportError:
        pass
    raise ImportError(
        "Cannot read .ods files: install odfpy (`pip install odfpy`) "
        "or ezodf (`pip install ezodf`) to enable UK FSA data parsing."
    )


def _food_category_from_sheet_name(sheet_name: str) -> str | None:
    """
    Extract the food category name from an ODS sheet name.

    Sheet names follow patterns like:
      Bread_BNA, Bread_GB_SUM, Beans_(Dried)_BNA, Beans_(dried)_Q2-Q4_NI_ST,
      BeansWithPods(GB)_BNA, Aubergine(GB)_ST

    Returns the food part (e.g. "Bread", "Beans (Dried)", "Beans With Pods",
    "Aubergine") or None if it cannot be parsed.
    """
    name = sheet_name.strip()
    # Strip trailing underscores/spaces
    name = name.rstrip("_ ")

    # Remove known suffixes: _BNA, _SUM, _ST, _SUM_, _ST_, plus
    # region/quarter qualifiers like _GB, _NI, _Q1, _Q2-Q4, _Part_1, _Part_2
    # Also handle parenthesized regions like (GB), (NI)
    # Strategy: find the food name by removing suffixes from the end.

    # Split on underscores to work with parts
    parts = name.split("_")

    # Known trailing suffix tokens to strip
    strip_tokens = {
        "bna", "sum", "st", "gb", "ni", "eu",
        "q1", "q2", "q3", "q4",
        "q2-q4", "q1-q4",
        "part", "1", "2",
    }

    # Walk backwards stripping known suffix tokens
    food_parts = []
    for part in reversed(parts):
        if part.lower().lstrip("(").rstrip(")") in strip_tokens:
            continue
        # Also skip pure numbers (like "1" from Part_1)
        if part.isdigit():
            continue
        food_parts.insert(0, part)

    if not food_parts:
        return None

    food = "_".join(food_parts)

    # Handle parenthesized region codes that are still attached:
    # e.g. "Bread(GB)" -> "Bread", "BeansWithPods(GB)" -> "Beans With Pods"
    food = re.sub(r"\s*\(GB\)\s*$", "", food, flags=re.IGNORECASE)
    food = re.sub(r"\s*\(NI\)\s*$", "", food, flags=re.IGNORECASE)
    food = re.sub(r"\s*\(EU\)\s*$", "", food, flags=re.IGNORECASE)
    food = re.sub(r"\(GB\)", "", food, flags=re.IGNORECASE)
    food = re.sub(r"\(NI\)", "", food, flags=re.IGNORECASE)
    food = re.sub(r"\(EU\)", "", food, flags=re.IGNORECASE)

    # Convert underscores and CamelCase to spaces for readability
    food = food.replace("_", " ")
    # Insert space before uppercase letters in CamelCase (e.g. BeansWithPods -> Beans With Pods)
    food = re.sub(r"([a-z])([A-Z])", r"\1 \2", food)

    # Clean up whitespace
    food = re.sub(r"\s+", " ", food).strip()

    return food if food else None


class UKFSAFetcher(BaseFetcher):
    SOURCE_NAME = "UK_FSA"

    def fetch(self) -> list[Path]:
        """
        Download annual PRiF ODS data files from Defra's S3 bucket.
        """
        paths = []

        for report in UK_FSA_REPORTS:
            url = report["url"]
            filename = report["filename"]
            try:
                path = download_file(url, filename)
                paths.append(path)
            except Exception as e:
                logger.warning(
                    "UK_FSA: failed to download %s: %s",
                    url, e,
                )

        if not paths:
            logger.warning("UK_FSA: no data files downloaded")
        return paths

    def parse(self, files: list[Path]) -> list[dict]:
        """
        Parse downloaded ODS data files and return Tier 2 aggregate rows.
        Each file is parsed individually, glyphosate rows are filtered,
        and results are aggregated by canonical food category.
        """
        all_rows = []
        for path in files:
            try:
                rows = self._parse_data_file(path)
                all_rows.extend(rows)
            except Exception as e:
                logger.warning(
                    "UK_FSA: failed to parse %s: %s -- skipping file",
                    path.name, e,
                )
        return all_rows

    # -- Parse helpers ---------------------------------------------------

    def _parse_data_file(self, path: Path) -> list[dict]:
        """
        Parse a single ODS file, filter for glyphosate,
        and aggregate results by food category.
        """
        suffix = path.suffix.lower()
        if suffix == ".ods":
            return self._parse_ods(path)
        elif suffix in (".xlsx", ".xls"):
            return self._parse_excel(path)
        elif suffix == ".csv":
            return self._parse_csv(path)
        else:
            logger.warning("UK_FSA: unsupported file format %s -- skipping", suffix)
            return []

    def _parse_ods(self, ods_path: Path) -> list[dict]:
        """
        Parse an ODS data file for glyphosate rows.

        Reads ALL sheets from the multi-sheet workbook. For each sheet that
        contains glyphosate data, extracts the food category from the sheet
        name and parses glyphosate values according to the sheet type:
          - BNA sheets: free-text "glyphosate 0.2 (MRL = 1.6)" in pesticide column
          - SUM/ST sheets: structured rows with pesticide name and detection counts
          - Analyte_Detections: aggregate totals without food breakdown
        """
        engine = _get_ods_engine()
        try:
            all_sheets = pd.read_excel(ods_path, sheet_name=None, engine=engine)
        except Exception as e:
            raise ValueError(
                f"Cannot read ODS {ods_path.name}: {e}"
            ) from e

        data_year = self._extract_year_from_filename(ods_path.name) or 2020
        published_date = f"{data_year + 1}-06-01"

        # Collect glyphosate findings per canonical food category.
        # key = food_category, value = dict with aggregation stats.
        by_category: dict[str, dict] = defaultdict(
            lambda: {"total": 0, "detected": 0, "ppb_values": [], "raw_cats": []}
        )

        sheet_count = len(all_sheets)
        gly_sheet_count = 0

        for sheet_name, df in all_sheets.items():
            if df.empty:
                continue

            sheet_lower = sheet_name.lower()

            # Skip purely introductory/summary sheets with no real data
            if sheet_lower in ("summary",) or sheet_lower.startswith("summary"):
                # But check for glyphosate anyway
                pass

            # Find glyphosate in this sheet
            gly_findings = self._find_glyphosate_in_sheet(df, sheet_name, ods_path)
            if not gly_findings:
                continue

            gly_sheet_count += 1

            # Derive food category from sheet name
            food_cat_raw = _food_category_from_sheet_name(sheet_name)

            for finding in gly_findings:
                if finding["source_type"] == "bna":
                    # Individual sample with measured glyphosate value
                    ppb = finding.get("ppb")
                    raw_cat = food_cat_raw or finding.get("food_raw", "unknown")
                    canonical = normalize_category(raw_cat)
                    if not canonical:
                        logger.debug(
                            "UK_FSA: no canonical category for '%s' -- skipping", raw_cat
                        )
                        continue

                    stats = by_category[canonical]
                    stats["total"] += 1
                    if ppb is not None and ppb > 0:
                        stats["detected"] += 1
                        stats["ppb_values"].append(ppb)
                    stats["raw_cats"].append(raw_cat)

                elif finding["source_type"] == "sum":
                    # Summary sheet row with detection count
                    raw_cat = food_cat_raw or finding.get("food_raw", "unknown")
                    canonical = normalize_category(raw_cat)
                    if not canonical:
                        logger.debug(
                            "UK_FSA: no canonical category for '%s' -- skipping", raw_cat
                        )
                        continue

                    n_samples = finding.get("n_samples", 0)
                    n_detected = finding.get("n_detected", 0)
                    ppb_values = finding.get("ppb_values", [])

                    stats = by_category[canonical]
                    stats["total"] += n_samples
                    stats["detected"] += n_detected
                    stats["ppb_values"].extend(ppb_values)
                    stats["raw_cats"].append(raw_cat)

                elif finding["source_type"] == "analyte":
                    # Analyte_Detections sheet -- aggregate totals only,
                    # no food category breakdown available.
                    n_detected = finding.get("n_detected", 0)
                    n_above_mrl = finding.get("n_above_mrl", 0)
                    logger.info(
                        "UK_FSA: Analyte_Detections in %s: %d detections below MRL, "
                        "%d above MRL (no food breakdown -- recording as aggregate)",
                        ods_path.name, n_detected, n_above_mrl,
                    )
                    # Store as an "all foods" aggregate row
                    raw_cat = "all foods"
                    canonical = normalize_category(raw_cat)
                    if canonical:
                        stats = by_category[canonical]
                        stats["total"] += n_detected + n_above_mrl
                        stats["detected"] += n_detected + n_above_mrl
                        stats["raw_cats"].append(raw_cat)

        logger.info(
            "UK_FSA: scanned %d sheets in %s, %d sheets contained glyphosate data",
            sheet_count, ods_path.name, gly_sheet_count,
        )

        # Build output rows from aggregated data.
        rows = self._build_output_rows(by_category, data_year, published_date, ods_path)

        logger.info(
            "UK_FSA: parsed %d category rows from %s",
            len(rows), ods_path.name,
        )
        return rows

    def _find_glyphosate_in_sheet(
        self, df: pd.DataFrame, sheet_name: str, file_path: Path
    ) -> list[dict]:
        """
        Scan a single sheet DataFrame for glyphosate data.

        Returns a list of finding dicts. Each finding has a "source_type" key
        indicating the data format ("bna", "sum", or "analyte") plus extracted
        glyphosate data.

        Strategy:
        1. Check if this is a known Analyte_Detections sheet (2019-2020).
        2. Check all cells for "glyphosate" text.
        3. Determine sheet type (BNA vs SUM/ST) and parse accordingly.
        """
        sheet_lower = sheet_name.strip().lower()

        # --- Analyte_Detections sheets (2019-2020) ---
        if "analyte" in sheet_lower and "detection" in sheet_lower:
            return self._parse_analyte_sheet(df, sheet_name, file_path)

        # --- Scan all cells for "glyphosate" ---
        gly_cols = []
        for col in df.columns:
            vals = df[col].dropna().astype(str).str.lower()
            if vals.str.contains("glyphosate", na=False).any():
                gly_cols.append(col)

        if not gly_cols:
            return []

        # Determine sheet type from name suffix
        is_bna = sheet_lower.endswith("_bna")
        is_sum = (
            sheet_lower.endswith("_sum")
            or sheet_lower.endswith("_st")
            or sheet_lower.endswith("_sum_")
            or sheet_lower.endswith("_st_")
        )

        findings = []

        if is_bna:
            findings = self._parse_bna_sheet(df, sheet_name, gly_cols, file_path)
        elif is_sum:
            findings = self._parse_sum_sheet(df, sheet_name, gly_cols, file_path)
        else:
            # Unknown sheet type -- try both approaches
            findings_bna = self._parse_bna_sheet(df, sheet_name, gly_cols, file_path)
            findings_sum = self._parse_sum_sheet(df, sheet_name, gly_cols, file_path)
            findings = findings_bna if findings_bna else findings_sum

        return findings

    def _parse_analyte_sheet(
        self, df: pd.DataFrame, sheet_name: str, file_path: Path
    ) -> list[dict]:
        """
        Parse an Analyte_Detections sheet (2019-2020 format).

        Columns: active/residue, number_of_detections_below_mrl,
                 number_of_detections_over_mrl.
        """
        df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]

        # Find the substance column
        sub_col = None
        for candidate in ["active", "residue", "substance", "pesticide", "analyte"]:
            for col in df.columns:
                if candidate in col:
                    sub_col = col
                    break
            if sub_col:
                break

        if not sub_col:
            return []

        mask = df[sub_col].astype(str).str.lower().str.contains("glyphosate", na=False)
        # Exclude AMPA-only rows
        ampa_mask = df[sub_col].astype(str).str.lower().str.contains("ampa", na=False) & ~mask
        gly_mask = mask & ~ampa_mask

        gly_df = df[gly_mask.values]
        if gly_df.empty:
            return []

        findings = []
        for _, row in gly_df.iterrows():
            n_below = self._safe_int(row, [
                "number_of_detections_below_mrl",
                "number_findings_below_mrl",
            ])
            n_above = self._safe_int(row, [
                "number_of_detections_over_mrl",
                "number_of_findings_above_mrl",
            ])
            n_total = self._safe_int(row, [
                "number_of_total_findings",
            ])

            if n_total is not None:
                n_detected = n_total
            else:
                n_detected = (n_below or 0) + (n_above or 0)

            findings.append({
                "source_type": "analyte",
                "n_detected": n_detected,
                "n_above_mrl": n_above or 0,
            })

        if findings:
            logger.info(
                "UK_FSA: Analyte_Detections in %s sheet [%s]: %d glyphosate entries",
                file_path.name, sheet_name, len(findings),
            )

        return findings

    def _parse_bna_sheet(
        self, df: pd.DataFrame, sheet_name: str, gly_cols: list, file_path: Path
    ) -> list[dict]:
        """
        Parse a BNA (Brand Name Annex) sheet for glyphosate.

        BNA sheets have individual sample rows. The pesticide column contains
        free-text entries like "glyphosate 0.2 (MRL = 1.6)". The food category
        is derived from the sheet name.

        For 2016, columns are properly named. For 2017+, the first row of data
        is the actual header row (row 0 has "Sample ID", "Date of Sampling", etc.).
        The pesticide column is typically the last column.
        """
        # Detect if this is a multi-row header sheet (2017+).
        # In 2017+ BNA sheets, the first column name is a long text label like
        # "Expert Committee on Pesticide Residues in Food Sample Details ..."
        # and row 0 contains the actual headers ("Sample ID", etc.).
        # In 2016, columns are already properly named.
        has_multirow_header = False
        first_col = df.columns[0]
        first_col_lower = first_col.lower().strip()
        if len(df) > 0 and str(df.iloc[0, 0]).strip().lower() == "sample id":
            # Row 0 has "Sample ID" -> the real headers are in row 0
            # This is the case for 2017+ where column names are long text
            if "unnamed" in first_col_lower or "expert_committee" in first_col_lower or "expert committee" in first_col_lower:
                has_multirow_header = True

        if has_multirow_header:
            # Use row 0 as the actual column headers
            new_headers = []
            for i, col in enumerate(df.columns):
                val = str(df.iloc[0, i]).strip()
                if val and val.lower() != "nan":
                    new_headers.append(val)
                else:
                    # Keep original column name for empty cells
                    new_headers.append(col)
            df = df.iloc[1:].reset_index(drop=True)
            df.columns = new_headers

        # Find the pesticide residues column
        pestic_col = None
        for col in df.columns:
            col_lower = col.lower().strip()
            if "pesticide" in col_lower and "residu" in col_lower:
                pestic_col = col
                break
            if "pesticide" in col_lower and "mg" in col_lower:
                pestic_col = col
                break
            if col_lower.startswith("pesticide"):
                pestic_col = col
                break

        # Also check gly_cols (already confirmed to contain glyphosate)
        if pestic_col is None:
            pestic_col = gly_cols[-1]  # Last column is typically the pesticide col

        # Scan for glyphosate values in the pesticide column
        findings = []
        pestic_values = df[pestic_col].dropna().astype(str)
        gly_mask = pestic_values.str.lower().str.contains("glyphosate", na=False)
        # Exclude AMPA
        ampa_mask = pestic_values.str.lower().str.contains("ampa", na=False)
        gly_only = gly_mask & ~ampa_mask

        gly_values = pestic_values[gly_only]
        for val in gly_values:
            ppb = self._extract_glyphosate_ppb(val)
            findings.append({
                "source_type": "bna",
                "ppb": ppb,
                "raw_value": val,
            })

        if findings:
            logger.info(
                "UK_FSA: BNA sheet [%s] in %s: %d glyphosate findings",
                sheet_name, file_path.name, len(findings),
            )

        return findings

    def _parse_sum_sheet(
        self, df: pd.DataFrame, sheet_name: str, gly_cols: list, file_path: Path
    ) -> list[dict]:
        """
        Parse a SUM/ST (summary) sheet for glyphosate.

        SUM sheets have per-pesticide rows. Column 0 typically contains the
        pesticide name. The structure varies by year but common patterns are:
          - glyphosate | <0.05 (i.e. not found) | <count>
          - glyphosate (0.05) | nan | nan    (LOD-only entry)
        """
        findings = []

        for col in gly_cols:
            vals = df[col].dropna().astype(str)
            gly_mask = vals.str.lower().str.contains("glyphosate", na=False)
            # Exclude AMPA and abbreviation codes like "GLY" alone
            ampa_mask = vals.str.lower().str.contains("ampa", na=False)
            gly_only = gly_mask & ~ampa_mask

            gly_values = vals[gly_only]
            for val in gly_values:
                val_lower = val.lower().strip()

                # Skip pure abbreviation codes (e.g. "GLY") -- these are
                # just index entries, not data rows
                if re.match(r"^[a-z]{2,4}$", val_lower):
                    continue

                # Skip entries that are just "glyphosate" without a value --
                # the real data is on the next columns
                if val_lower == "glyphosate":
                    # Get the row index and read other columns for detection info
                    idx_positions = gly_only[gly_only].index
                    for idx in idx_positions:
                        if df.loc[idx, col] != val:
                            continue
                        finding = self._parse_sum_row(df, idx, col)
                        if finding:
                            findings.append(finding)
                    break  # Already processed all rows for this column

                # Check for LOD-only entry like "glyphosate (0.05)"
                lod_match = _GLY_LOD_RE.match(val)
                if lod_match and "mrl" not in val_lower:
                    # This is a LOD reference, no actual detections
                    # (e.g. "glyphosate (0.05)" means glyphosate was tested
                    # with LOD 0.05 mg/kg but not necessarily detected)
                    continue

                # Check for BNA-style embedded value (shouldn't happen in SUM,
                # but handle gracefully)
                ppb = self._extract_glyphosate_ppb(val)
                if ppb is not None:
                    findings.append({
                        "source_type": "bna",  # Treat as sample-level finding
                        "ppb": ppb,
                        "raw_value": val,
                    })

        if findings:
            logger.info(
                "UK_FSA: SUM sheet [%s] in %s: %d glyphosate findings",
                sheet_name, file_path.name, len(findings),
            )

        return findings

    def _parse_sum_row(
        self, df: pd.DataFrame, idx: int, name_col: str
    ) -> dict | None:
        """
        Parse a single row from a SUM sheet where the name column contains
        exactly "glyphosate". Look at adjacent columns for detection data.

        Typical SUM row pattern:
          col0: "glyphosate"
          col1: "<0.05 (i.e. not found)" or "<0.1 (i.e. not found)" (LOD text)
          col2: "53" or "7" (sample count where it was tested)
        """
        row = df.loc[idx]
        cols = list(df.columns)
        name_col_idx = cols.index(name_col)

        # Read values from columns after the name column
        lod_text = None
        n_samples = 0
        ppb_values = []
        n_detected = 0

        for i in range(name_col_idx + 1, min(name_col_idx + 6, len(cols))):
            col = cols[i]
            cell_val = str(row.get(col, "")).strip()
            if not cell_val or cell_val.lower() == "nan":
                continue

            # Check for LOD / "not found" text
            if _NOT_FOUND_RE.search(cell_val):
                lod_text = cell_val
                continue

            # Check for sample count (integer)
            try:
                count = int(float(cell_val))
                # Heuristic: if we have a LOD text and this is a number,
                # it's the count of samples where glyphosate was below LOD
                # (i.e. tested but not detected at that LOD).
                # The number represents samples with residue below LOD.
                n_samples += count
                continue
            except (ValueError, TypeError):
                pass

            # Check for country-of-origin breakdown (not useful for ppb)
            if re.search(r"\([0-9]+\)", cell_val):
                # e.g. "Argentina (4), Canada (7), UK (2)"
                continue

        if n_samples == 0:
            return None

        return {
            "source_type": "sum",
            "n_samples": n_samples,
            "n_detected": n_detected,
            "ppb_values": ppb_values,
        }

    def _extract_glyphosate_ppb(self, text: str) -> float | None:
        """
        Extract glyphosate concentration in ppb (ug/kg) from free-text.

        Handles patterns like:
          "glyphosate 0.2 (MRL = 1.6)"
          "glyphosate 0.07 (MRL = 0.1*)"

        Returns the value in ppb (mg/kg * 1000), or None if not parseable.
        """
        match = _GLY_VALUE_RE.search(text)
        if match:
            mg_kg = float(match.group(1))
            return mg_kg * 1000.0  # Convert mg/kg to ppb (ug/kg)
        return None

    def _build_output_rows(
        self,
        by_category: dict[str, dict],
        data_year: int,
        published_date: str,
        file_path: Path,
    ) -> list[dict]:
        """Build Tier 2 output rows from aggregated category data."""
        rows = []
        for food_category, stats in by_category.items():
            if stats["total"] == 0:
                continue

            total = stats["total"]
            n_detected = stats["detected"]
            detection_rate = round(n_detected / total, 4) if total > 0 else None
            avg_ppb = (
                round(sum(stats["ppb_values"]) / len(stats["ppb_values"]), 2)
                if stats["ppb_values"]
                else None
            )
            max_ppb = (
                round(max(stats["ppb_values"]), 2)
                if stats["ppb_values"]
                else None
            )
            raw_cat = ", ".join(sorted(set(stats["raw_cats"])))

            rows.append({
                "tier": 2,
                "source_name": "UK_FSA",
                "source_url": COLLECTION_URL,
                "report_label": f"UK PRiF Monitoring {data_year}",
                "published_date": published_date,
                "data_year": data_year,
                "food_category": food_category,
                "raw_category": raw_cat,
                "samples_total": total,
                "samples_detected": n_detected,
                "detection_rate": detection_rate,
                "avg_ppb": avg_ppb,
                "max_ppb": max_ppb,
                "original_unit": "mg/kg",
                "unit_conversion": 1000.0,
                "methodology_note": (
                    f"UK FSA Pesticide Residues in Food (PRiF) monitoring programme. "
                    f"Individual sample results from annual data for {data_year}. "
                    f"Glyphosate-specific results aggregated by canonical food category. "
                    f"Multi-pesticide dataset filtered for glyphosate (AMPA excluded). "
                    f"Data extracted from multi-sheet ODS workbook (BNA and SUM sheets). "
                    f"Original data in mg/kg, converted to ppb."
                ),
                "confidence": "high",
                "raw_file_path": str(file_path),
                "dedup_key": build_dedup_key(
                    "UK_FSA", food_category, data_year
                ),
            })

        return rows

    def _parse_csv(self, csv_path: Path) -> list[dict]:
        """Parse a CSV data file for glyphosate rows."""
        try:
            df = pd.read_csv(csv_path, low_memory=False)
        except UnicodeDecodeError:
            try:
                df = pd.read_csv(csv_path, low_memory=False, encoding="latin-1")
            except Exception as e:
                raise ValueError(
                    f"Cannot read CSV {csv_path.name}: {e}"
                ) from e
        return self._extract_glyphosate_rows(df, csv_path)

    def _parse_excel(self, xlsx_path: Path) -> list[dict]:
        """Parse an Excel data file for glyphosate rows."""
        try:
            df = pd.read_excel(xlsx_path, sheet_name=0, engine="openpyxl")
        except Exception:
            try:
                df = pd.read_excel(xlsx_path, sheet_name=0, engine="xlrd")
            except Exception as e:
                raise ValueError(
                    f"Cannot read Excel {xlsx_path.name}: {e}"
                ) from e
        return self._extract_glyphosate_rows(df, xlsx_path)

    def _extract_glyphosate_rows(
        self, df: pd.DataFrame, file_path: Path
    ) -> list[dict]:
        """
        Fallback glyphosate extraction for non-ODS formats (CSV, XLSX).
        Uses dynamic column detection with the traditional approach.
        """
        # Normalize column names for matching.
        df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]

        logger.info(
            "UK_FSA: %s -- %d rows, columns: %s",
            file_path.name, len(df), list(df.columns),
        )

        # Dynamic column detection.
        substance_col = self._find_col(df, SUBSTANCE_COL_CANDIDATES)
        commodity_col = self._find_col(df, COMMODITY_COL_CANDIDATES)
        result_col = self._find_col(df, RESULT_COL_CANDIDATES)

        if not substance_col:
            raise ValueError(
                f"No substance/pesticide column found in {file_path.name}. "
                f"Available: {list(df.columns)}"
            )
        if not commodity_col:
            raise ValueError(
                f"No commodity/food column found in {file_path.name}. "
                f"Available: {list(df.columns)}"
            )

        # Filter for glyphosate.
        gly_mask = df[substance_col].astype(str).str.lower().str.contains(
            "glyphosate", na=False
        )
        gly_df = df[gly_mask].copy()

        if gly_df.empty:
            logger.info("UK_FSA: no glyphosate rows in %s", file_path.name)
            return []

        # Exclude AMPA metabolite rows.
        ampa_mask = gly_df[substance_col].astype(str).str.lower().str.contains(
            "ampa", na=False
        )
        gly_df = gly_df[~ampa_mask].copy()

        if gly_df.empty:
            logger.info(
                "UK_FSA: only AMPA (no glyphosate) in %s", file_path.name
            )
            return []

        logger.info(
            "UK_FSA: %d glyphosate sample rows in %s",
            len(gly_df), file_path.name,
        )

        # Infer data year from filename.
        data_year = self._extract_year_from_filename(file_path.name) or 2020
        published_date = f"{data_year + 1}-06-01"

        # Aggregate by canonical food category.
        by_category: dict[str, dict] = defaultdict(
            lambda: {"total": 0, "detected": 0, "ppb_values": [], "raw_cats": []}
        )

        for commodity, group in gly_df.groupby(commodity_col):
            raw_cat = str(commodity).strip()
            if not raw_cat or raw_cat.lower() in ("nan", "total", "all"):
                continue
            food_category = normalize_category(raw_cat)
            if not food_category:
                logger.debug(
                    "UK_FSA: no canonical category for '%s' -- skipping", raw_cat
                )
                continue

            total = len(group)

            if result_col and result_col in group.columns:
                values = pd.to_numeric(group[result_col], errors="coerce")
                detected_values = values[values > 0]
                n_detected = len(detected_values)
                ppb_detected = (detected_values * 1000.0).tolist()
            else:
                n_detected = 0
                ppb_detected = []

            stats = by_category[food_category]
            stats["total"] += total
            stats["detected"] += n_detected
            stats["ppb_values"].extend(ppb_detected)
            stats["raw_cats"].append(raw_cat)

        return self._build_output_rows(by_category, data_year, published_date, file_path)

    def _find_col(self, df: pd.DataFrame, candidates: list[str]) -> str | None:
        """Find the first matching column name from a list of candidates."""
        for col in candidates:
            if col in df.columns:
                return col
        # Fallback: substring match
        for col in df.columns:
            for candidate in candidates:
                if candidate in col:
                    return col
        return None

    @staticmethod
    def _safe_int(row: pd.Series, candidates: list[str]) -> int | None:
        """Safely extract an integer from a row by trying multiple column names."""
        for col in candidates:
            col_lower = col.lower().strip().replace(" ", "_")
            if col_lower in row.index:
                try:
                    return int(float(row[col_lower]))
                except (ValueError, TypeError):
                    pass
        return None

    @staticmethod
    def _extract_year_from_filename(filename: str) -> int | None:
        """Try to extract a 4-digit year from a filename."""
        match = re.search(r"(20[12]\d)", filename)
        if match:
            return int(match.group(1))
        return None
