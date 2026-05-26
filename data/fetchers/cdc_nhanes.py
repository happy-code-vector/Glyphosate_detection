"""
fetchers/cdc_nhanes.py

CDC NHANES (National Health and Nutrition Examination Survey) —
Biomonitoring data for glyphosate and AMPA in urine.

Source:
  CDC National Center for Health Statistics.
  https://wwwn.cdc.gov/nchs/nhanes/

Downloads XPT (SAS Transport) files containing individual-level urine
glyphosate concentrations from the NHANES laboratory component.
Computes population-level exposure statistics (detection rate, geometric
mean, percentiles) for insertion into the biomonitoring table.

This is nationally representative data — the U.S. gold standard for
human exposure assessment.
"""

import logging
import math
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from fetchers.base import BaseFetcher, download_file, RAW_DATA_DIR
from db.database import build_dedup_key, get_connection

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# NHANES cycle registry
# ─────────────────────────────────────────────────────────────────────
NHANES_CYCLES = [
    # CDC publishes glyphosate-specific XPT files only for certain cycles.
    # 2019-2020 and 2021-2022 cycles do not have separate glyphosate files.
    {
        "cycle": "2013-2014",
        "filename": "SSGLYP_H.xpt",
        "url": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2013/DataFiles/SSGLYP_H.xpt",
    },
    {
        "cycle": "2015-2016",
        "filename": "SSGLYP_I.xpt",
        "url": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2015/DataFiles/SSGLYP_I.xpt",
    },
    {
        "cycle": "2017-2018",
        "filename": "SSGLYP_J.xpt",
        "url": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/SSGLYP_J.xpt",
    },
]

# NHANES variable definitions
# SSGLYP  = glyphosate concentration (ng/mL = ppb)
# SSGLYPL = below-detection flag (0 = detected, 1 = below LOD)
# WTSSGLYP = sample weight for national representativeness
# LOD     = 0.2 ng/mL

GLYPHOSATE_COL = "SSGLYP"
BELOW_DET_COL = "SSGLYPL"
WEIGHT_COL = "WTSSGLYP"
LOD = 0.2  # ng/mL

# SQL for creating the biomonitoring table
_BIOMONITORING_DDL = """
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
"""


def _read_xpt(path: Path) -> pd.DataFrame:
    """
    Read an XPT (SAS Transport) file into a pandas DataFrame.

    Tries multiple parsing strategies:
      1. pandas read_sas() — built-in XPT reader (pandas >= 1.5)
      2. pandas read_xpt() — if available as standalone function
      3. pyreadstat package — robust SAS file reader
      4. xport package — dedicated XPT reader

    Falls back gracefully with clear error messages.
    """
    # Strategy 1: pd.read_sas (most common, available since pandas 0.23)
    try:
        df = pd.read_sas(path, format="xport")
        if df is not None and not df.empty:
            # read_sas may return byte-string columns; decode them
            df = _decode_byte_columns(df)
            logger.info("Read XPT via pd.read_sas: %d rows, %d cols", len(df), len(df.columns))
            return df
    except Exception as e:
        logger.debug("pd.read_sas failed for %s: %s", path.name, e)

    # Strategy 2: pd.read_xpt (pandas >= 2.0 may expose this directly)
    try:
        df = pd.read_xpt(path)
        if df is not None and not df.empty:
            df = _decode_byte_columns(df)
            logger.info("Read XPT via pd.read_xpt: %d rows, %d cols", len(df), len(df.columns))
            return df
    except Exception as e:
        logger.debug("pd.read_xpt failed for %s: %s", path.name, e)

    # Strategy 3: pyreadstat package
    try:
        import pyreadstat
        df, _ = pyreadstat.read_xport(str(path))
        if df is not None and not df.empty:
            df = _decode_byte_columns(df)
            logger.info("Read XPT via pyreadstat: %d rows, %d cols", len(df), len(df.columns))
            return df
    except ImportError:
        logger.debug("pyreadstat not available")
    except Exception as e:
        logger.debug("pyreadstat failed for %s: %s", path.name, e)

    # Strategy 4: xport package
    try:
        import xport
        with open(path, "rb") as f:
            df = xport.to_dataframe(f)
        if df is not None and not df.empty:
            df = _decode_byte_columns(df)
            logger.info("Read XPT via xport: %d rows, %d cols", len(df), len(df.columns))
            return df
    except ImportError:
        logger.debug("xport package not available")
    except Exception as e:
        logger.debug("xport failed for %s: %s", path.name, e)

    raise RuntimeError(
        f"Could not read XPT file {path.name}. "
        "Install pyreadstat (`pip install pyreadstat`) or xport (`pip install xport`) "
        "for SAS Transport file support, or upgrade pandas to >= 2.0."
    )


def _decode_byte_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Decode byte-string columns that pd.read_sas may return.
    Converts columns like b'VALUE' to plain 'VALUE'.
    """
    for col in df.columns:
        if df[col].dtype == object:
            sample = df[col].dropna().head(5)
            if any(isinstance(v, bytes) for v in sample):
                df[col] = df[col].apply(
                    lambda v: v.decode("utf-8", errors="replace") if isinstance(v, bytes) else v
                )
    return df


def _weighted_percentile(values: np.ndarray, weights: np.ndarray, pct: float) -> float:
    """
    Compute a weighted percentile using the interpolation method.

    Parameters
    ----------
    values : array of glyphosate concentrations
    weights : array of sample weights
    pct : target percentile (0-100)

    Returns
    -------
    float : weighted percentile value
    """
    if len(values) == 0:
        return np.nan

    sorted_idx = np.argsort(values)
    sorted_vals = values[sorted_idx]
    sorted_wts = weights[sorted_idx]

    cum_wts = np.cumsum(sorted_wts)
    total_wt = cum_wts[-1]
    target = (pct / 100.0) * total_wt

    # Interpolate between adjacent values
    idx = np.searchsorted(cum_wts, target, side="right")
    idx = min(idx, len(sorted_vals) - 1)

    return float(sorted_vals[idx])


def _weighted_geometric_mean(values: np.ndarray, weights: np.ndarray) -> float:
    """
    Compute weighted geometric mean: exp(sum(w_i * ln(x_i)) / sum(w_i)).

    All values must be > 0.
    """
    if len(values) == 0:
        return np.nan

    log_vals = np.log(values)
    weighted_sum = np.sum(weights * log_vals)
    total_weight = np.sum(weights)

    return float(np.exp(weighted_sum / total_weight))


class CDC_NHANESFetcher(BaseFetcher):
    """
    Fetcher for CDC NHANES glyphosate biomonitoring data.

    Downloads XPT files, parses individual-level urine glyphosate
    concentrations, and computes population-level exposure statistics
    using NHANES sample weights.
    """

    SOURCE_NAME = "CDC_NHANES"

    def fetch(self) -> list[Path]:
        """
        Download NHANES XPT files from CDC for each cycle.
        Returns list of local paths to the downloaded XPT files.
        """
        paths = []
        for cycle_info in NHANES_CYCLES:
            cycle = cycle_info["cycle"]
            try:
                path = download_file(
                    url=cycle_info["url"],
                    dest_filename=f"nhanes_{cycle.replace('-', '_')}_{cycle_info['filename']}",
                )
                paths.append(path)
            except Exception as e:
                logger.error(
                    "NHANES %s: download failed: %s — skipping cycle", cycle, e
                )

        return paths

    def parse(self, files: list[Path]) -> list[dict]:
        """
        Parse XPT files and compute population-level glyphosate exposure
        statistics for each NHANES cycle.

        Returns a list of dicts ready for insertion into the biomonitoring table.
        Each dict represents one cycle's summary statistics.
        """
        results = []

        for cycle_info in NHANES_CYCLES:
            cycle = cycle_info["cycle"]
            expected_prefix = f"nhanes_{cycle.replace('-', '_')}_"

            # Find the matching file for this cycle
            matching = [
                f for f in files if f.name.startswith(expected_prefix)
            ]
            if not matching:
                logger.warning("NHANES %s: no downloaded file found — skipping", cycle)
                continue

            path = matching[0]

            try:
                df = _read_xpt(path)
            except RuntimeError as e:
                logger.error("NHANES %s: %s — skipping cycle", cycle, e)
                continue
            except Exception as e:
                logger.error("NHANES %s: unexpected error reading XPT: %s — skipping", cycle, e)
                continue

            stats = self._compute_cycle_stats(df, cycle)
            if stats:
                results.append(stats)

        return results

    def _compute_cycle_stats(self, df: pd.DataFrame, cycle: str) -> dict | None:
        """
        Compute population-level glyphosate exposure statistics from a
        single NHANES cycle's individual-level data.
        """
        # Normalize column names to uppercase for reliable lookup
        df.columns = [c.upper().strip() for c in df.columns]

        gly_col = GLYPHOSATE_COL.upper()
        flag_col = BELOW_DET_COL.upper()
        wt_col = WEIGHT_COL.upper()

        if gly_col not in df.columns:
            logger.warning(
                "NHANES %s: glyphosate column '%s' not found. "
                "Available: %s — skipping cycle",
                cycle, gly_col, list(df.columns),
            )
            return None

        logger.info(
            "NHANES %s: %d total records, columns: %s",
            cycle, len(df), list(df.columns),
        )

        # Extract glyphosate values and below-detection flag
        glyphosate = pd.to_numeric(df[gly_col], errors="coerce")
        has_flag = flag_col in df.columns
        has_weight = wt_col in df.columns

        if has_flag:
            below_flag = pd.to_numeric(df[flag_col], errors="coerce")
        else:
            below_flag = pd.Series(np.nan, index=df.index)

        if has_weight:
            weights = pd.to_numeric(df[wt_col], errors="coerce").fillna(0)
        else:
            weights = None

        # Total sample size (non-NaN glyphosate measurements)
        valid_mask = glyphosate.notna()
        total_samples = int(valid_mask.sum())

        if total_samples == 0:
            logger.warning("NHANES %s: no valid glyphosate measurements", cycle)
            return None

        # Detection status
        if has_flag:
            detected_mask = valid_mask & (below_flag < 0.5)
        else:
            # If no flag column, treat values > LOD as detected
            detected_mask = valid_mask & (glyphosate > LOD)

        detected_count = int(detected_mask.sum())
        detection_rate = round(detected_count / total_samples, 4) if total_samples > 0 else 0.0

        # Detected values only (for geometric mean and percentiles)
        detected_values = glyphosate[detected_mask].values
        detected_weights = weights[detected_mask].values if weights is not None else None

        # Compute statistics
        if len(detected_values) > 0:
            # Geometric mean
            if detected_weights is not None and np.sum(detected_weights) > 0:
                geo_mean = round(
                    _weighted_geometric_mean(detected_values, detected_weights), 4
                )
                p50 = round(
                    _weighted_percentile(detected_values, detected_weights, 50), 4
                )
                p75 = round(
                    _weighted_percentile(detected_values, detected_weights, 75), 4
                )
                p90 = round(
                    _weighted_percentile(detected_values, detected_weights, 90), 4
                )
                p95 = round(
                    _weighted_percentile(detected_values, detected_weights, 95), 4
                )
            else:
                # Unweighted statistics
                geo_mean = round(
                    float(np.exp(np.mean(np.log(detected_values)))), 4
                )
                p50 = round(float(np.percentile(detected_values, 50)), 4)
                p75 = round(float(np.percentile(detected_values, 75)), 4)
                p90 = round(float(np.percentile(detected_values, 90)), 4)
                p95 = round(float(np.percentile(detected_values, 95)), 4)
        else:
            geo_mean = None
            p50 = None
            p75 = None
            p90 = None
            p95 = None

        weight_note = (
            "weighted using NHANES sample weights (WTSSGLYP)"
            if detected_weights is not None
            else "unweighted (sample weights not available)"
        )

        return {
            "source": "CDC_NHANES",
            "cycle": cycle,
            "analyte": "Glyphosate",
            "population_group": "US general population (age 6+)",
            "sample_size": total_samples,
            "detected_count": detected_count,
            "detection_rate": detection_rate,
            "geometric_mean": geo_mean,
            "percentile_50": p50,
            "percentile_75": p75,
            "percentile_90": p90,
            "percentile_95": p95,
            "unit": "ng/mL",
            "lod": LOD,
            "methodology_note": (
                f"CDC NHANES {cycle} cycle. Glyphosate measured in urine via "
                "isotope-dilution LC-MS/MS. Nationally representative sample "
                "of the U.S. civilian noninstitutionalized population. "
                f"LOD = {LOD} ng/mL. Statistics {weight_note}. "
                "Values below LOD excluded from geometric mean and percentile "
                "calculations. Data source: CDC National Center for Health Statistics."
            ),
            "confidence": "high",
            "dedup_key": build_dedup_key("CDC_NHANES", "Glyphosate", cycle),
        }

    def run(self) -> dict:
        """
        Override base class run() — CDC NHANES uses a separate
        biomonitoring table, not glyphosate_measurements.
        """
        from db.database import log_ingest

        logger.info("=== Starting %s pipeline ===", self.SOURCE_NAME)

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

        if not rows:
            logger.warning("%s: no rows to insert", self.SOURCE_NAME)
            log_ingest(self.SOURCE_NAME, "success", inserted=0, skipped=0, failed=0)
            return {"inserted": 0, "skipped": 0, "failed": 0}

        logger.info("%s parsed %d rows, inserting into biomonitoring...", self.SOURCE_NAME, len(rows))

        # Create the biomonitoring table if it doesn't exist
        with get_connection() as conn:
            conn.execute(_BIOMONITORING_DDL)

        # Custom insert into biomonitoring table
        inserted = skipped = failed = 0
        with get_connection() as conn:
            for row in rows:
                if not row.get("dedup_key"):
                    logger.warning("Row missing dedup_key — skipping: %s", row)
                    failed += 1
                    continue
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO biomonitoring (
                            source, cycle, analyte, population_group,
                            sample_size, detected_count, detection_rate,
                            geometric_mean,
                            percentile_50, percentile_75, percentile_90, percentile_95,
                            unit, lod, dedup_key
                        ) VALUES (
                            :source, :cycle, :analyte, :population_group,
                            :sample_size, :detected_count, :detection_rate,
                            :geometric_mean,
                            :percentile_50, :percentile_75, :percentile_90, :percentile_95,
                            :unit, :lod, :dedup_key
                        )
                    """, row)
                    changes = conn.execute("SELECT changes()").fetchone()[0]
                    if changes:
                        inserted += 1
                        logger.info(
                            "%s inserted: cycle=%s, n=%d, det_rate=%.2f%%, geo_mean=%s ng/mL",
                            self.SOURCE_NAME, row["cycle"], row["sample_size"],
                            (row["detection_rate"] or 0) * 100,
                            row["geometric_mean"],
                        )
                    else:
                        skipped += 1
                        logger.debug("%s skipped (duplicate): cycle=%s", self.SOURCE_NAME, row["cycle"])
                except sqlite3.Error as e:
                    logger.error(
                        "%s insert failed for cycle %s: %s",
                        self.SOURCE_NAME, row.get("cycle"), e,
                    )
                    failed += 1

        status = "success" if failed == 0 else "partial"
        log_ingest(
            self.SOURCE_NAME, status,
            inserted=inserted, skipped=skipped, failed=failed,
            source_file=str([f.name for f in files]),
        )

        logger.info(
            "%s complete: inserted=%d skipped=%d failed=%d",
            self.SOURCE_NAME, inserted, skipped, failed,
        )
        return {"inserted": inserted, "skipped": skipped, "failed": failed}
