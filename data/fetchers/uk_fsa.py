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

  ALL pesticide data is extracted by scanning ALL sheets for substance
  columns, then parsing values and aggregating by (canonical food category,
  substance name). Each output row includes a "contaminant" field with the
  substance name.

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

# Generic regex to extract concentration from free-text BNA cells.
# Matches patterns like: "glyphosate 0.2 (MRL = 1.6)" or "chlorpyrifos 0.07 (MRL = 0.1*)"
# Group 1 = substance name, group 2 = concentration value.
_VALUE_RE = re.compile(
    r"(\b[a-zA-Z][\w\s\-()/]*?)\s+(?:sum\s+)?(\d+\.?\d*)\s*\((?:MRL|LOD)",
    re.IGNORECASE,
)

# Generic regex to extract LOD from SUM sheet cells like "glyphosate (0.05)" or "chlorpyrifos (0.01)"
# Group 1 = substance name, group 2 = LOD value.
_LOD_RE = re.compile(
    r"(\b[a-zA-Z][\w\s\-()/]*?)\s*\((\d+\.?\d*)\)",
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
        Each file is parsed individually, all pesticide substance rows are
        extracted, and results are aggregated by (canonical food category, substance).
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
        Parse a single ODS file, extract all pesticide substance data,
        and aggregate results by (food category, substance).
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
        Parse an ODS data file for all pesticide rows.

        Reads ALL sheets from the multi-sheet workbook. For each sheet that
        contains pesticide data, extracts the food category from the sheet
        name and parses values according to the sheet type:
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

        # Collect pesticide findings per (canonical food category, substance).
        # key = (food_category, substance), value = dict with aggregation stats.
        by_category_substance: dict[tuple[str, str], dict] = defaultdict(
            lambda: {"total": 0, "detected": 0, "ppb_values": [], "raw_cats": []}
        )

        sheet_count = len(all_sheets)
        data_sheet_count = 0

        for sheet_name, df in all_sheets.items():
            if df.empty:
                continue

            sheet_lower = sheet_name.lower()

            # Skip purely introductory/summary sheets with no real data
            if sheet_lower in ("summary",) or sheet_lower.startswith("summary"):
                pass

            # Find all pesticide substance data in this sheet
            findings = self._find_pesticide_data_in_sheet(df, sheet_name, ods_path)
            if not findings:
                continue

            data_sheet_count += 1

            # Derive food category from sheet name
            food_cat_raw = _food_category_from_sheet_name(sheet_name)

            for finding in findings:
                substance = finding.get("substance", "unknown")

                if finding["source_type"] == "bna":
                    # Individual sample with measured value
                    ppb = finding.get("ppb")
                    raw_cat = food_cat_raw or finding.get("food_raw", "unknown")
                    canonical = normalize_category(raw_cat)
                    if not canonical:
                        logger.debug(
                            "UK_FSA: no canonical category for '%s' -- skipping", raw_cat
                        )
                        continue

                    key = (canonical, substance)
                    stats = by_category_substance[key]
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

                    key = (canonical, substance)
                    stats = by_category_substance[key]
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
                        "%d above MRL for %s (no food breakdown -- recording as aggregate)",
                        ods_path.name, n_detected, n_above_mrl, substance,
                    )
                    # Store as an "all foods" aggregate row
                    raw_cat = "all foods"
                    canonical = normalize_category(raw_cat)
                    if canonical:
                        key = (canonical, substance)
                        stats = by_category_substance[key]
                        stats["total"] += n_detected + n_above_mrl
                        stats["detected"] += n_detected + n_above_mrl
                        stats["raw_cats"].append(raw_cat)

        logger.info(
            "UK_FSA: scanned %d sheets in %s, %d sheets contained pesticide data",
            sheet_count, ods_path.name, data_sheet_count,
        )

        # Build output rows from aggregated data.
        rows = self._build_output_rows(by_category_substance, data_year, published_date, ods_path)

        logger.info(
            "UK_FSA: parsed %d category-substance rows from %s",
            len(rows), ods_path.name,
        )
        return rows

    def _find_pesticide_data_in_sheet(
        self, df: pd.DataFrame, sheet_name: str, file_path: Path
    ) -> list[dict]:
        """
        Scan a single sheet DataFrame for all pesticide substance data.

        Returns a list of finding dicts. Each finding has a "source_type" key
        indicating the data format ("bna", "sum", or "analyte") plus extracted
        substance data including a "substance" field.

        Strategy:
        1. Check if this is a known Analyte_Detections sheet (2019-2020).
        2. Detect substance/pesticide columns.
        3. Determine sheet type (BNA vs SUM/ST) and parse accordingly.
        """
        sheet_lower = sheet_name.strip().lower()

        # --- Analyte_Detections sheets (2019-2020) ---
        if "analyte" in sheet_lower and "detection" in sheet_lower:
            return self._parse_analyte_sheet(df, sheet_name, file_path)

        # --- Detect substance/pesticide columns ---
        # Scan all columns for any that contain pesticide substance names.
        # We look for columns whose values contain known pesticide-related text
        # or match our substance column candidates.
        substance_cols = []
        for col in df.columns:
            col_lower = str(col).lower().strip()
            # Check if the column name matches substance candidates
            if any(candidate in col_lower for candidate in SUBSTANCE_COL_CANDIDATES):
                substance_cols.append(col)
                continue
            # Check if column values contain pesticide-related content
            vals = df[col].dropna().astype(str).str.lower()
            if vals.str.contains(r"pesticide|residue|substance|analyte", na=False, regex=True).any():
                substance_cols.append(col)

        if not substance_cols:
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
            findings = self._parse_bna_sheet(df, sheet_name, substance_cols, file_path)
        elif is_sum:
            findings = self._parse_sum_sheet(df, sheet_name, substance_cols, file_path)
        else:
            # Unknown sheet type -- try both approaches
            findings_bna = self._parse_bna_sheet(df, sheet_name, substance_cols, file_path)
            findings_sum = self._parse_sum_sheet(df, sheet_name, substance_cols, file_path)
            findings = findings_bna if findings_bna else findings_sum

        return findings

    def _parse_analyte_sheet(
        self, df: pd.DataFrame, sheet_name: str, file_path: Path
    ) -> list[dict]:
        """
        Parse an Analyte_Detections sheet (2019-2020 format).

        Columns: active/residue, number_of_detections_below_mrl,
                 number_of_detections_over_mrl.

        Processes ALL substances (not just glyphosate).
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

        # Process all substance rows (no glyphosate/AMPA filtering)
        findings = []
        for _, row in df.iterrows():
            substance = str(row[sub_col]).strip()
            if not substance or substance.lower() == "nan":
                continue

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
                "substance": substance,
                "n_detected": n_detected,
                "n_above_mrl": n_above or 0,
            })

        if findings:
            logger.info(
                "UK_FSA: Analyte_Detections in %s sheet [%s]: %d substance entries",
                file_path.name, sheet_name, len(findings),
            )

        return findings

    def _parse_bna_sheet(
        self, df: pd.DataFrame, sheet_name: str, substance_cols: list, file_path: Path
    ) -> list[dict]:
        """
        Parse a BNA (Brand Name Annex) sheet for all pesticide substances.

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

        # Also check substance_cols as fallback
        if pestic_col is None:
            pestic_col = substance_cols[-1]  # Last column is typically the pesticide col

        # Scan ALL values in the pesticide column (no glyphosate filter)
        findings = []
        pestic_values = df[pestic_col].dropna().astype(str)

        for val in pestic_values:
            val_stripped = val.strip()
            if not val_stripped or val_stripped.lower() == "nan":
                continue

            # Try to extract substance name and concentration from free-text
            # Pattern: "substance_name value (MRL = x)" e.g. "glyphosate 0.2 (MRL = 1.6)"
            substance, ppb = self._extract_pesticide_ppb(val_stripped)
            if substance and ppb is not None:
                findings.append({
                    "source_type": "bna",
                    "substance": substance,
                    "ppb": ppb,
                    "raw_value": val_stripped,
                })
            elif substance:
                # Substance mentioned but no parseable value
                findings.append({
                    "source_type": "bna",
                    "substance": substance,
                    "ppb": None,
                    "raw_value": val_stripped,
                })

        if findings:
            logger.info(
                "UK_FSA: BNA sheet [%s] in %s: %d pesticide findings",
                sheet_name, file_path.name, len(findings),
            )

        return findings

    def _parse_sum_sheet(
        self, df: pd.DataFrame, sheet_name: str, substance_cols: list, file_path: Path
    ) -> list[dict]:
        """
        Parse a SUM/ST (summary) sheet for all pesticide substances.

        SUM sheets have per-pesticide rows. Column 0 typically contains the
        pesticide name. The structure varies by year but common patterns are:
          - glyphosate | <0.05 (i.e. not found) | <count>
          - chlorpyrifos (0.05) | nan | nan    (LOD-only entry)
        """
        findings = []

        for col in substance_cols:
            vals = df[col].dropna().astype(str)

            for val in vals:
                val_lower = val.lower().strip()

                # Skip pure abbreviation codes (e.g. "GLY") -- these are
                # just index entries, not data rows
                if re.match(r"^[a-z]{2,4}$", val_lower):
                    continue

                # Skip empty / nan
                if not val_lower or val_lower == "nan":
                    continue

                # Try to identify substance name from the cell value.
                # For SUM sheets, the substance name is often the cell value itself
                # (e.g. "glyphosate", "chlorpyrifos"), with detection data in
                # adjacent columns.
                substance_name = self._identify_substance(val_lower)
                if not substance_name:
                    continue

                # Skip entries that are just the substance name without a value --
                # the real data is on the next columns
                if val_lower == substance_name.lower():
                    # Get the row index and read other columns for detection info
                    idx_positions = vals[vals == val].index
                    for idx in idx_positions:
                        if df.loc[idx, col] != val:
                            continue
                        finding = self._parse_sum_row(df, idx, col, substance_name)
                        if finding:
                            findings.append(finding)
                    continue

                # Check for LOD-only entry like "glyphosate (0.05)"
                lod_match = _LOD_RE.match(val)
                if lod_match and "mrl" not in val_lower:
                    # This is a LOD reference, no actual detections
                    continue

                # Check for BNA-style embedded value (shouldn't happen in SUM,
                # but handle gracefully)
                extracted_substance, ppb = self._extract_pesticide_ppb(val)
                if ppb is not None:
                    findings.append({
                        "source_type": "bna",  # Treat as sample-level finding
                        "substance": extracted_substance or substance_name,
                        "ppb": ppb,
                        "raw_value": val,
                    })

        if findings:
            logger.info(
                "UK_FSA: SUM sheet [%s] in %s: %d substance findings",
                sheet_name, file_path.name, len(findings),
            )

        return findings

    def _parse_sum_row(
        self, df: pd.DataFrame, idx: int, name_col: str, substance_name: str
    ) -> dict | None:
        """
        Parse a single row from a SUM sheet where the name column contains
        a substance name. Look at adjacent columns for detection data.

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
                # it's the count of samples where the substance was below LOD
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
            "substance": substance_name,
            "n_samples": n_samples,
            "n_detected": n_detected,
            "ppb_values": ppb_values,
        }

    def _extract_pesticide_ppb(self, text: str) -> tuple[str | None, float | None]:
        """
        Extract substance name and concentration in ppb (ug/kg) from free-text.

        Handles patterns like:
          "glyphosate 0.2 (MRL = 1.6)"
          "chlorpyrifos 0.07 (MRL = 0.1*)"

        Returns (substance_name, ppb_value) or (substance_name, None) if value
        not parseable, or (None, None) if no substance found.
        """
        match = _VALUE_RE.search(text)
        if match:
            substance = match.group(1).strip().rstrip(" ")
            try:
                mg_kg = float(match.group(2))
                return substance, mg_kg * 1000.0  # Convert mg/kg to ppb (ug/kg)
            except (ValueError, TypeError):
                return substance, None
        return None, None

    def _identify_substance(self, text: str) -> str | None:
        """
        Try to identify a pesticide substance name from a text string.

        For SUM sheets, the cell value is often just the substance name
        (e.g. "glyphosate", "chlorpyrifos", "deltamethrin"). This method
        checks if the text looks like a valid substance name.

        Returns the substance name (title-cased) or None if not identifiable.
        """
        text = text.strip()
        if not text or text.lower() == "nan":
            return None

        # Skip entries that look like numbers, LOD values, or structural markers
        if re.match(r"^[\d<>=\.\s]+$", text):
            return None
        # Skip abbreviation codes (e.g. "GLY", "CLO")
        if re.match(r"^[a-z]{2,4}$", text.lower()):
            return None
        # Skip "not found" patterns
        if "not found" in text.lower():
            return None
        # Skip MRL-only entries
        if re.match(r"^[^a-zA-Z]*mrl", text.lower()):
            return None
        # Must contain at least one letter and be a reasonable length
        if not re.search(r"[a-zA-Z]", text):
            return None
        if len(text) > 80:  # Too long to be a substance name
            return None

        return text.title()

    def _build_output_rows(
        self,
        by_category_substance: dict[tuple[str, str], dict],
        data_year: int,
        published_date: str,
        file_path: Path,
    ) -> list[dict]:
        """Build Tier 2 output rows from aggregated (category, substance) data."""
        rows = []
        for (food_category, substance), stats in by_category_substance.items():
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
                "contaminant": substance,
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
                    f"Results aggregated by canonical food category and substance. "
                    f"Data extracted from multi-sheet ODS workbook (BNA and SUM sheets). "
                    f"Original data in mg/kg, converted to ppb."
                ),
                "confidence": "high",
                "raw_file_path": str(file_path),
                "dedup_key": build_dedup_key(
                    "UK_FSA", food_category, substance, data_year
                ),
            })

        return rows

    def _parse_csv(self, csv_path: Path) -> list[dict]:
        """Parse a CSV data file for all pesticide rows."""
        try:
            df = pd.read_csv(csv_path, low_memory=False)
        except UnicodeDecodeError:
            try:
                df = pd.read_csv(csv_path, low_memory=False, encoding="latin-1")
            except Exception as e:
                raise ValueError(
                    f"Cannot read CSV {csv_path.name}: {e}"
                ) from e
        return self._extract_pesticide_rows(df, csv_path)

    def _parse_excel(self, xlsx_path: Path) -> list[dict]:
        """Parse an Excel data file for all pesticide rows."""
        try:
            df = pd.read_excel(xlsx_path, sheet_name=0, engine="openpyxl")
        except Exception:
            try:
                df = pd.read_excel(xlsx_path, sheet_name=0, engine="xlrd")
            except Exception as e:
                raise ValueError(
                    f"Cannot read Excel {xlsx_path.name}: {e}"
                ) from e
        return self._extract_pesticide_rows(df, xlsx_path)

    def _extract_pesticide_rows(
        self, df: pd.DataFrame, file_path: Path
    ) -> list[dict]:
        """
        Extract all pesticide substance data for non-ODS formats (CSV, XLSX).
        Uses dynamic column detection. Processes ALL substances, not just glyphosate.
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

        # Drop rows with empty substance values.
        clean_df = df[
            df[substance_col].notna()
            & (df[substance_col].astype(str).str.strip().str.lower() != "nan")
            & (df[substance_col].astype(str).str.strip() != "")
        ].copy()

        if clean_df.empty:
            logger.info("UK_FSA: no substance rows in %s", file_path.name)
            return []

        logger.info(
            "UK_FSA: %d substance sample rows in %s",
            len(clean_df), file_path.name,
        )

        # Infer data year from filename.
        data_year = self._extract_year_from_filename(file_path.name) or 2020
        published_date = f"{data_year + 1}-06-01"

        # Aggregate by (canonical food category, substance).
        by_category_substance: dict[tuple[str, str], dict] = defaultdict(
            lambda: {"total": 0, "detected": 0, "ppb_values": [], "raw_cats": []}
        )

        for (commodity, substance), group in clean_df.groupby([commodity_col, substance_col]):
            raw_cat = str(commodity).strip()
            if not raw_cat or raw_cat.lower() in ("nan", "total", "all"):
                continue
            food_category = normalize_category(raw_cat)
            if not food_category:
                logger.debug(
                    "UK_FSA: no canonical category for '%s' -- skipping", raw_cat
                )
                continue

            substance_name = str(substance).strip().title()
            if not substance_name or substance_name.lower() == "nan":
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

            key = (food_category, substance_name)
            stats = by_category_substance[key]
            stats["total"] += total
            stats["detected"] += n_detected
            stats["ppb_values"].extend(ppb_detected)
            stats["raw_cats"].append(raw_cat)

        return self._build_output_rows(by_category_substance, data_year, published_date, file_path)

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
