"""
fetchers/water_quality.py

Multi-contaminant water monitoring data from USGS Water Quality Portal.

Source:
  USGS Water Quality Portal
  https://waterqualitydata.us

Downloads per-state CSV data, aggregates by (state, water_type, year),
and inserts into the water_tests table.

All values stored as ppb (ug/L).
"""

import logging
from pathlib import Path

import pandas as pd

from fetchers.base import BaseFetcher, SESSION, RAW_DATA_DIR
from db.database import build_dedup_key, get_connection
from contaminants import get_contaminant_config, CONTAMINANTS

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# USGS Water Quality Portal
# ─────────────────────────────────────────────────────────────────────
WQP_BASE_URL = "https://www.waterqualitydata.us/data/Result/search"

# State codes for per-state download
STATE_CODES = {
    "US:06": "California",
    "US:19": "Iowa",
    "US:17": "Illinois",
    "US:39": "Ohio",
    "US:55": "Wisconsin",
    "US:26": "Michigan",
    "US:27": "Minnesota",
    "US:53": "Washington",
    "US:41": "Oregon",
    "US:51": "Virginia",
    "US:36": "New York",
    "US:48": "Texas",
    "US:12": "Florida",
    "US:42": "Pennsylvania",
    "US:25": "Massachusetts",
}

# Site type → water_type mapping
_SITE_TYPE_MAP = {
    "Stream": "surface",
    "River/Stream": "surface",
    "Lake": "surface",
    "Reservoir": "surface",
    "Estuary": "surface",
    "Ocean": "surface",
    "Well": "groundwater",
    "Spring": "groundwater",
    "Land": "groundwater",
    "Atmosphere": "surface",
}


def _map_site_type(raw: str) -> str:
    """Map WQP site type to our water_type."""
    if not raw or raw.lower() == "nan":
        return "surface"
    for key, mapped in _SITE_TYPE_MAP.items():
        if key.lower() in raw.lower():
            return mapped
    return "surface"


class WaterQualityFetcher(BaseFetcher):
    SOURCE_NAME = "Water_Quality"

    def __init__(self, contaminant: str = "glyphosate"):
        if contaminant not in CONTAMINANTS:
            raise ValueError(f"Unknown contaminant: {contaminant}")
        self.contaminant = contaminant
        self.config = get_contaminant_config(contaminant)
        self.wqp_filename = f"wqp_{contaminant}_water.csv"

    def run(self) -> dict:
        """Fetch + parse + insert. Also seeds drinking water standards."""
        from db.database import insert_rows, log_ingest
        logger.info("=== Starting %s pipeline (contaminant=%s) ===",
                     self.SOURCE_NAME, self.contaminant)

        self._seed_standards_direct()

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

        logger.info("%s (%s) parsed %d rows, inserting...",
                     self.SOURCE_NAME, self.contaminant, len(rows))
        counts = insert_rows(rows, f"{self.SOURCE_NAME}_{self.contaminant}", str(files))
        logger.info(
            "%s (%s) complete: inserted=%d skipped=%d failed=%d",
            self.SOURCE_NAME, self.contaminant,
            counts["inserted"], counts["skipped"], counts["failed"]
        )
        return counts

    def _seed_standards_direct(self):
        """Insert drinking water regulatory standards into tolerance_limits."""
        with get_connection() as conn:
            for std in self.config["water_standards"]:
                dedup = build_dedup_key(
                    self.contaminant, std["source"], "drinking_water"
                )
                conn.execute("""
                    INSERT OR IGNORE INTO tolerance_limits (
                        food_category, raw_commodity, tolerance_ppm, tolerance_ppb,
                        source, regulation_reference, contaminant, dedup_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    "drinking_water", "drinking_water",
                    std["tolerance_ppm"], std["tolerance_ppb"],
                    std["source"], std["regulation_reference"],
                    self.contaminant, dedup,
                ))
        logger.info("Seeded %s drinking water standards", self.contaminant)

    def fetch(self) -> list[Path]:
        """Download per-state water data files."""
        paths = []
        base_params = {
            "characteristicName": self.config["wqp_characteristic"],
            "sampleMedia": "Water",
            "mimeType": "csv",
            "sorted": "no",
        }
        base_params.update(self.config.get("wqp_params_override", {}))

        for statecode, state_name in STATE_CODES.items():
            dest = RAW_DATA_DIR / f"wqp_{self.contaminant}_{state_name.lower().replace(' ', '_')}.csv"
            if dest.exists():
                logger.info("Cache hit: %s", dest.name)
                paths.append(dest)
                continue

            params = {**base_params, "statecode": statecode}
            try:
                logger.info("WQP %s: fetching %s...", self.contaminant, state_name)
                resp = SESSION.get(WQP_BASE_URL, params=params, timeout=120)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    dest.write_bytes(resp.content)
                    paths.append(dest)
                    logger.info("WQP %s %s: %d bytes", self.contaminant, state_name, len(resp.content))
                else:
                    logger.warning("WQP %s %s: status %d (%d bytes)",
                                   self.contaminant, state_name, resp.status_code, len(resp.content))
            except Exception as e:
                logger.warning("WQP %s %s failed: %s", self.contaminant, state_name, e)

        # Also try date range fallback for states without data
        date_ranges = self.config.get("wqp_date_ranges", [])
        for start, end in date_ranges:
            params = {**base_params, "startDateLo": start, "startDateHi": end}
            dest = RAW_DATA_DIR / f"wqp_{self.contaminant}_{start}_{end}.csv"
            if dest.exists():
                paths.append(dest)
                continue
            try:
                logger.info("WQP %s: fetching %s to %s...", self.contaminant, start, end)
                resp = SESSION.get(WQP_BASE_URL, params=params, timeout=300)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    dest.write_bytes(resp.content)
                    paths.append(dest)
                    logger.info("WQP %s %s-%s: %d bytes", self.contaminant, start, end, len(resp.content))
            except Exception as e:
                logger.warning("WQP %s %s-%s failed: %s", self.contaminant, start, end, e)

        if not paths:
            logger.error("WQP %s: all queries returned empty data", self.contaminant)

        return paths

    def parse(self, files: list[Path]) -> list[dict]:
        """Parse per-state water data files and aggregate by (state, water_type, year)."""
        all_rows = []
        for path in files:
            # Extract state name from filename
            state = self._extract_state_from_filename(path)
            rows = self._parse_state_file(path, state)
            all_rows.extend(rows)
        return all_rows

    def _extract_state_from_filename(self, path: Path) -> str:
        """Extract state name from filename like 'wqp_glyphosate_california.csv'."""
        name = path.stem  # e.g., "wqp_glyphosate_california"
        parts = name.split("_")
        # Remove the first two parts (wqp, contaminant)
        if len(parts) >= 3:
            state_part = "_".join(parts[2:])
            # Handle date range files
            if "-" in state_part and state_part.replace("-", "").isdigit():
                return "National"
            return state_part.replace("_", " ").title()
        return "National"

    def _parse_state_file(self, path: Path, state: str) -> list[dict]:
        """Parse a single state's water data file."""
        try:
            df = pd.read_csv(path, low_memory=False, encoding="latin-1")
        except Exception as e:
            logger.warning("WQP %s: failed to read %s: %s", self.contaminant, path.name, e)
            return []

        if df.empty:
            return []

        # Normalize column names
        df.columns = [c.strip() for c in df.columns]

        # Find key columns
        result_col = self._find_col(df, ["ResultMeasureValue", "ResultMeasure/MeasureValue", "result", "value"])
        unit_col = self._find_col(df, ["ResultMeasure/MeasureUnitCode", "MeasureUnitCode", "unit"])
        date_col = self._find_col(df, ["ActivityStartDate", "StartDate", "date"])
        site_type_col = self._find_col(df, ["MonitoringLocationTypeName", "SiteType", "site_type"])
        char_col = self._find_col(df, ["CharacteristicName", "characteristicname", "characteristic"])
        det_cond_col = self._find_col(df, ["ResultDetectionConditionText", "DetectionCondition"])

        if not result_col:
            logger.warning("WQP %s: no result column in %s", self.contaminant, path.name)
            return []

        # Filter to our contaminant
        if char_col:
            char_mask = df[char_col].astype(str).str.lower().str.contains(
                self.config["wqp_characteristic"].lower(), na=False
            )
            df = df[char_mask]

        if df.empty:
            return []

        # Parse result values
        df["_ppb"] = pd.to_numeric(df[result_col], errors="coerce")

        # Unit conversion
        if unit_col:
            units = df[unit_col].astype(str).str.lower()
            mg_mask = units.str.contains("mg/l", na=False)
            df.loc[mg_mask, "_ppb"] = df.loc[mg_mask, "_ppb"] * 1000

        # Detection status
        if det_cond_col:
            det_conds = df[det_cond_col].astype(str).str.lower()
            below_keywords = ["below", "not detected", "nd", "non-detect", "non detect"]
            df["_below_det"] = det_conds.apply(
                lambda x: any(kw in x for kw in below_keywords)
            )
        else:
            df["_below_det"] = df["_ppb"].isna() | (df["_ppb"] <= 0)

        # Parse years
        if date_col:
            df["_year"] = pd.to_datetime(df[date_col], errors="coerce").dt.year
            df = df[df["_year"] >= 1970]
        else:
            df["_year"] = 0

        # Map water type
        if site_type_col:
            df["_water_type"] = df[site_type_col].apply(_map_site_type)
        else:
            df["_water_type"] = "surface"

        # Aggregate by (state, water_type, year)
        rows = []
        for (wtype, year), group in df.groupby(["_water_type", "_year"], dropna=False):
            year_clean = int(year) if pd.notna(year) else 0
            wtype_clean = str(wtype)

            detected = group[~group["_below_det"] & group["_ppb"].notna()]
            total = len(group)
            n_detected = len(detected)
            detection_rate = round(n_detected / total, 4) if total > 0 else 0
            avg_ppb = round(detected["_ppb"].mean(), 2) if len(detected) > 0 else None
            max_ppb = round(detected["_ppb"].max(), 2) if len(detected) > 0 else None

            rows.append({
                "table": "water",
                "contaminant": self.contaminant,
                "source_name": "USGS_WQP",
                "source_url": "https://waterqualitydata.us",
                "report_label": f"USGS WQP {self.contaminant.title()} Water {state} {year_clean}",
                "data_year": year_clean,
                "state": state,
                "water_type": wtype_clean,
                "is_aggregate": 1,
                "samples_total": total,
                "samples_detected": n_detected,
                "detection_rate": detection_rate,
                "avg_ppb": avg_ppb,
                "max_ppb": max_ppb,
                "methodology_note": (
                    f"USGS Water Quality Portal. "
                    f"{total} water samples for {self.contaminant} "
                    f"in {state} ({wtype_clean}), {year_clean}. Units: ug/L (ppb)."
                ),
                "confidence": "high",
                "dedup_key": build_dedup_key(
                    self.contaminant, "USGS_WQP", state, wtype_clean, year_clean
                ),
            })

        logger.info("WQP %s %s: parsed %d aggregate rows from %s",
                     self.contaminant, state, len(rows), path.name)
        return rows

    def _find_col(self, df, candidates):
        """Find first matching column name."""
        for col in candidates:
            if col in df.columns:
                return col
        return None
