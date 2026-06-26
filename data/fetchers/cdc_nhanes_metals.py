"""
fetchers/cdc_nhanes_metals.py

CDC NHANES Heavy Metals Biomonitoring — Lead, Cadmium, Mercury, Arsenic.

Source:
  CDC National Center for Health Statistics.
  https://wwwn.cdc.gov/nchs/nhanes/

Downloads XPT files from NHANES standard laboratory panels:
  - PbCd (Lead, Cadmium, Mercury in blood)
  - UAS (Arsenic in urine)

Computes population-level exposure statistics using NHANES sample weights.
"""

import logging
import numpy as np
import pandas as pd
from pathlib import Path

from fetchers.base import BaseFetcher, download_file, RAW_DATA_DIR
from fetchers.cdc_nhanes import _read_xpt, _weighted_percentile, _weighted_geometric_mean
from db.database import build_dedup_key, get_connection

logger = logging.getLogger(__name__)

# Canonical source identifier — used for row lineage and dedup keys below,
# and re-exposed as the fetcher's SOURCE_NAME for ingest logging.
SOURCE_NAME = "CDC_NHANES_Metals"

# ─────────────────────────────────────────────────────────────────────
# NHANES heavy metals configuration
# Each entry defines: analyte name, XPT file, variable name, LOD, unit,
# below-detection flag column, and weight column.
# ─────────────────────────────────────────────────────────────────────

METAL_CYCLES = [
    # 2017-2018 cycle
    {
        "cycle": "2017-2018",
        "analytes": [
            {
                "analyte": "Lead",
                "filename": "PbCd_J.XPT",
                "url": "https://wwwn.cdc.gov/Nchs/Nhanes/2017-2018/PBCD_J.XPT",
                "var": "LBXBPB",
                "flag_var": "LBXBPBLL",
                "weight_var": "WTSANGPR",
                "lod": 0.07,
                "unit": "ug/dL",
                "unit_to_ng_ml": 10.0,  # 1 ug/dL = 10 ng/mL
            },
            {
                "analyte": "Cadmium",
                "filename": "PbCd_J.XPT",
                "url": "https://wwwn.cdc.gov/Nchs/Nhanes/2017-2018/PBCD_J.XPT",
                "var": "LBXBCD",
                "flag_var": "LBXBCDLL",
                "weight_var": "WTSANGPR",
                "lod": 0.02,
                "unit": "ug/L",
                "unit_to_ng_ml": 1.0,  # 1 ug/L = 1 ng/mL
            },
            {
                "analyte": "Mercury",
                "filename": "PbCd_J.XPT",
                "url": "https://wwwn.cdc.gov/Nchs/Nhanes/2017-2018/PBCD_J.XPT",
                "var": "LBXTHG",
                "flag_var": "LBXTHGLL",
                "weight_var": "WTSANGPR",
                "lod": 0.28,
                "unit": "ug/L",
                "unit_to_ng_ml": 1.0,
            },
            {
                "analyte": "Arsenic",
                "filename": "UAS_J.XPT",
                "url": "https://wwwn.cdc.gov/Nchs/Nhanes/2017-2018/UAS_J.XPT",
                "var": "URXUAS3",  # Arsenic III (inorganic arsenic)
                "flag_var": "URDUA3LC",  # Below-detection flag
                "weight_var": "WTSA2YR",
                "lod": 0.6,
                "unit": "ug/L",
                "unit_to_ng_ml": 1.0,
            },
        ],
    },
    # 2015-2016 cycle
    {
        "cycle": "2015-2016",
        "analytes": [
            {
                "analyte": "Lead",
                "filename": "PbCd_I.XPT",
                "url": "https://wwwn.cdc.gov/Nchs/Nhanes/2015-2016/PBCD_I.XPT",
                "var": "LBXBPB",
                "flag_var": "LBXBPBLL",
                "weight_var": "WTSANGPR",
                "lod": 0.07,
                "unit": "ug/dL",
                "unit_to_ng_ml": 10.0,
            },
            {
                "analyte": "Cadmium",
                "filename": "PbCd_I.XPT",
                "url": "https://wwwn.cdc.gov/Nchs/Nhanes/2015-2016/PBCD_I.XPT",
                "var": "LBXBCD",
                "flag_var": "LBXBCDLL",
                "weight_var": "WTSANGPR",
                "lod": 0.02,
                "unit": "ug/L",
                "unit_to_ng_ml": 1.0,
            },
            {
                "analyte": "Mercury",
                "filename": "PbCd_I.XPT",
                "url": "https://wwwn.cdc.gov/Nchs/Nhanes/2015-2016/PBCD_I.XPT",
                "var": "LBXTHG",
                "flag_var": "LBXTHGLL",
                "weight_var": "WTSANGPR",
                "lod": 0.28,
                "unit": "ug/L",
                "unit_to_ng_ml": 1.0,
            },
        ],
    },
    # 2013-2014 cycle
    {
        "cycle": "2013-2014",
        "analytes": [
            {
                "analyte": "Lead",
                "filename": "PbCd_H.XPT",
                "url": "https://wwwn.cdc.gov/Nchs/Nhanes/2013-2014/PBCD_H.XPT",
                "var": "LBXBPB",
                "flag_var": "LBXBPBLL",
                "weight_var": "WTSANGPR",
                "lod": 0.07,
                "unit": "ug/dL",
                "unit_to_ng_ml": 10.0,
            },
            {
                "analyte": "Cadmium",
                "filename": "PbCd_H.XPT",
                "url": "https://wwwn.cdc.gov/Nchs/Nhanes/2013-2014/PBCD_H.XPT",
                "var": "LBXBCD",
                "flag_var": "LBXBCDLL",
                "weight_var": "WTSANGPR",
                "lod": 0.02,
                "unit": "ug/L",
                "unit_to_ng_ml": 1.0,
            },
            {
                "analyte": "Mercury",
                "filename": "PbCd_H.XPT",
                "url": "https://wwwn.cdc.gov/Nchs/Nhanes/2013-2014/PBCD_H.XPT",
                "var": "LBXTHG",
                "flag_var": "LBXTHGLL",
                "weight_var": "WTSANGPR",
                "lod": 0.28,
                "unit": "ug/L",
                "unit_to_ng_ml": 1.0,
            },
        ],
    },
]


def _compute_analyte_stats(df: pd.DataFrame, config: dict, cycle: str) -> dict | None:
    """
    Compute population-level exposure statistics for a single analyte
    from a single NHANES cycle's individual-level data.
    """
    var = config["var"]
    flag_var = config.get("flag_var")
    weight_var = config.get("weight_var")
    lod = config["lod"]
    unit_conv = config["unit_to_ng_ml"]

    df.columns = [c.upper().strip() for c in df.columns]

    if var not in df.columns:
        logger.warning("NHANES %s %s: variable '%s' not found — skipping",
                       cycle, config["analyte"], var)
        return None

    values = pd.to_numeric(df[var], errors="coerce")
    has_flag = flag_var and flag_var.upper() in df.columns
    has_weight = weight_var and weight_var.upper() in df.columns

    if has_flag:
        below_flag = pd.to_numeric(df[flag_var.upper()], errors="coerce")
    else:
        below_flag = None

    if has_weight:
        weights = pd.to_numeric(df[weight_var.upper()], errors="coerce").fillna(0)
    else:
        weights = None

    # Valid measurements
    valid_mask = values.notna()
    total_samples = int(valid_mask.sum())

    if total_samples == 0:
        return None

    # Detection status
    if has_flag is not None and below_flag is not None:
        detected_mask = valid_mask & (below_flag < 0.5)
    else:
        detected_mask = valid_mask & (values > lod)

    detected_count = int(detected_mask.sum())
    detection_rate = round(detected_count / total_samples, 4)

    # Detected values only (convert to ng/mL)
    detected_values = values[detected_mask].values * unit_conv
    detected_weights = weights[detected_mask].values if weights is not None else None

    # Compute statistics
    if len(detected_values) > 0:
        if detected_weights is not None and np.sum(detected_weights) > 0:
            geo_mean = round(_weighted_geometric_mean(detected_values, detected_weights), 4)
            p50 = round(_weighted_percentile(detected_values, detected_weights, 50), 4)
            p75 = round(_weighted_percentile(detected_values, detected_weights, 75), 4)
            p90 = round(_weighted_percentile(detected_values, detected_weights, 90), 4)
            p95 = round(_weighted_percentile(detected_values, detected_weights, 95), 4)
        else:
            geo_mean = round(float(np.exp(np.mean(np.log(detected_values)))), 4)
            p50 = round(float(np.percentile(detected_values, 50)), 4)
            p75 = round(float(np.percentile(detected_values, 75)), 4)
            p90 = round(float(np.percentile(detected_values, 90)), 4)
            p95 = round(float(np.percentile(detected_values, 95)), 4)
    else:
        geo_mean = p50 = p75 = p90 = p95 = None

    return {
        "source": SOURCE_NAME,
        "cycle": cycle,
        "analyte": config["analyte"],
        "population_group": "US general population",
        "sample_size": total_samples,
        "detected_count": detected_count,
        "detection_rate": detection_rate,
        "geometric_mean": geo_mean,
        "percentile_50": p50,
        "percentile_75": p75,
        "percentile_90": p90,
        "percentile_95": p95,
        "unit": "ng/mL",
        "lod": round(lod * unit_conv, 4),
        "methodology_note": (
            f"CDC NHANES {cycle} cycle. {config['analyte']} measured in "
            f"{'urine' if 'UAS' in config['filename'] else 'blood'} via "
            "ICP-MS or AAS. Nationally representative sample. "
            f"LOD = {round(lod * unit_conv, 4)} ng/mL. "
            f"Converted from {config['unit']} to ng/mL."
        ),
        "confidence": "high",
        "dedup_key": build_dedup_key(SOURCE_NAME, config["analyte"], cycle),
    }


class CDC_NHANES_MetalsFetcher(BaseFetcher):
    """Fetcher for CDC NHANES heavy metals biomonitoring data."""

    SOURCE_NAME = SOURCE_NAME  # re-export module-level constant

    def fetch(self) -> list[Path]:
        """Download NHANES XPT files for heavy metals."""
        paths = []
        seen_urls = set()

        for cycle_info in METAL_CYCLES:
            for analyte_config in cycle_info["analytes"]:
                url = analyte_config["url"]
                if url in seen_urls:
                    continue  # Same file serves multiple analytes (e.g. PbCd)
                seen_urls.add(url)

                cycle = cycle_info["cycle"]
                filename = analyte_config["filename"]
                dest = f"nhanes_metals_{cycle.replace('-', '_')}_{filename}"

                try:
                    path = download_file(url=url, dest_filename=dest)
                    paths.append(path)
                except Exception as e:
                    logger.error("NHANES metals %s %s: download failed: %s — skipping",
                                cycle, filename, e)

        return paths

    def parse(self, files: list[Path]) -> list[dict]:
        """Parse XPT files and compute stats for each analyte per cycle."""
        results = []

        for cycle_info in METAL_CYCLES:
            cycle = cycle_info["cycle"]
            expected_prefix = f"nhanes_metals_{cycle.replace('-', '_')}_"

            # Find matching files for this cycle
            matching = [f for f in files if f.name.startswith(expected_prefix)]
            if not matching:
                logger.warning("NHANES metals %s: no downloaded files — skipping", cycle)
                continue

            # Cache loaded DataFrames (one file may serve multiple analytes)
            df_cache = {}

            for analyte_config in cycle_info["analytes"]:
                filename = analyte_config["filename"]

                # Find the matching file
                file_path = next((f for f in matching if f.name.endswith(filename)), None)
                if not file_path:
                    logger.warning("NHANES metals %s %s: file not found — skipping",
                                  cycle, filename)
                    continue

                # Load DataFrame (cached)
                if file_path not in df_cache:
                    try:
                        df_cache[file_path] = _read_xpt(file_path)
                    except Exception as e:
                        logger.error("NHANES metals %s: %s — skipping", cycle, e)
                        break

                df = df_cache[file_path]
                stats = _compute_analyte_stats(df, analyte_config, cycle)
                if stats:
                    results.append(stats)

        return results

    def run(self) -> dict:
        """Override base class run() — inserts into biomonitoring table."""
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

        logger.info("%s parsed %d rows, inserting...", self.SOURCE_NAME, len(rows))

        # Create table if needed
        from fetchers.cdc_nhanes import _BIOMONITORING_DDL
        with get_connection() as conn:
            conn.execute(_BIOMONITORING_DDL)

        # Insert
        inserted = skipped = failed = 0
        with get_connection() as conn:
            for row in rows:
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
                        logger.info("%s inserted: %s cycle=%s, n=%d, det=%.1f%%",
                                   self.SOURCE_NAME, row["analyte"], row["cycle"],
                                   row["sample_size"], (row["detection_rate"] or 0) * 100)
                    else:
                        skipped += 1
                except Exception as e:
                    logger.error("%s insert failed: %s %s: %s",
                                self.SOURCE_NAME, row.get("analyte"), row.get("cycle"), e)
                    failed += 1

        status = "success" if failed == 0 else "partial"
        log_ingest(self.SOURCE_NAME, status,
                   inserted=inserted, skipped=skipped, failed=failed)

        logger.info("%s complete: inserted=%d skipped=%d failed=%d",
                    self.SOURCE_NAME, inserted, skipped, failed)
        return {"inserted": inserted, "skipped": skipped, "failed": failed}
