"""
fetchers/water_quality.py

Glyphosate water monitoring data from USGS Water Quality Portal and EPA UCMR 3.

Sources:
  1. USGS WQP — surface water + groundwater glyphosate detections nationwide
     API: https://waterqualitydata.us/data/Result/search
  2. EPA UCMR 3 — drinking water glyphosate data (2013-2015)
     URL: https://www.epa.gov/dwucmr/occurrence-data-unregulated-contaminant-monitoring-rule
  3. Drinking water regulatory standards (EPA MCL, EU DWD, Health Canada)

All values stored as ppb (ug/L).
"""

import io
import logging
import zipfile
from collections import defaultdict
from pathlib import Path

import pandas as pd

from fetchers.base import BaseFetcher, download_file, SESSION, RAW_DATA_DIR
from db.database import build_dedup_key, get_connection

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# USGS Water Quality Portal
# ─────────────────────────────────────────────────────────────────────
WQP_BASE_URL = "https://www.waterqualitydata.us/data/Result/search"
WQP_PARAMS = {
    "characteristicName": "Glyphosate",
    "sampleMedia": "Water",
    "mimeType": "csv",
    "sorted": "no",
    "providers": "STORET,NWIS",
}
WQP_FILENAME = "wqp_glyphosate_water.csv"

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

# ─────────────────────────────────────────────────────────────────────
# EPA UCMR 3 — CONFIRMED: glyphosate was NOT in UCMR 3 contaminant list.
# UCMR 3 tested 30 contaminants (VOCs, metals, PFAS, hormones) — no pesticides.
# Leaving this section as documentation. The fetcher does not attempt UCMR 3.
# ─────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────
# Drinking water regulatory standards
# ─────────────────────────────────────────────────────────────────────
WATER_STANDARDS = [
    {
        "food_category": "drinking_water",
        "raw_commodity": "drinking_water",
        "tolerance_ppm": 0.7,
        "tolerance_ppb": 700.0,
        "source": "EPA_MCL",
        "regulation_reference": "40 CFR 141.60 — National Primary Drinking Water Regulation",
    },
    {
        "food_category": "drinking_water",
        "raw_commodity": "drinking_water",
        "tolerance_ppm": 0.0001,
        "tolerance_ppb": 0.1,
        "source": "EU_DWD",
        "regulation_reference": "EU Drinking Water Directive 2020/2184 — individual pesticide limit",
    },
    {
        "food_category": "drinking_water",
        "raw_commodity": "drinking_water",
        "tolerance_ppm": 0.28,
        "tolerance_ppb": 280.0,
        "source": "Health_Canada",
        "regulation_reference": "Health Canada Guidelines for Canadian Drinking Water Quality",
    },
]


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

    def run(self) -> dict:
        """Fetch + parse + insert. Also seeds drinking water standards."""
        from db.database import insert_rows, get_connection
        logger.info("=== Starting %s pipeline ===", self.SOURCE_NAME)

        # Seed drinking water regulatory standards
        self._seed_standards_direct()

        try:
            files = self.fetch()
        except Exception as e:
            from db.database import log_ingest
            log_ingest(self.SOURCE_NAME, "failed", error_message=str(e))
            logger.error("%s fetch failed: %s", self.SOURCE_NAME, e)
            raise

        try:
            rows = self.parse(files)
        except Exception as e:
            from db.database import log_ingest
            log_ingest(self.SOURCE_NAME, "failed", error_message=str(e))
            logger.error("%s parse failed: %s", self.SOURCE_NAME, e)
            raise

        logger.info("%s parsed %d rows, inserting...", self.SOURCE_NAME, len(rows))
        counts = insert_rows(rows, self.SOURCE_NAME, str(files))
        logger.info(
            "%s complete: inserted=%d skipped=%d failed=%d",
            self.SOURCE_NAME, counts["inserted"], counts["skipped"], counts["failed"]
        )
        return counts

    def _seed_standards_direct(self):
        """Insert drinking water regulatory standards into tolerance_limits."""
        with get_connection() as conn:
            for std in WATER_STANDARDS:
                dedup = build_dedup_key(std["source"], "drinking_water")
                conn.execute("""
                    INSERT OR IGNORE INTO tolerance_limits (
                        food_category, raw_commodity, tolerance_ppm, tolerance_ppb,
                        source, regulation_reference, dedup_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    std["food_category"], std["raw_commodity"],
                    std["tolerance_ppm"], std["tolerance_ppb"],
                    std["source"], std["regulation_reference"], dedup,
                ))
        logger.info("Seeded drinking water regulatory standards")

    def fetch(self) -> list[Path]:
        paths = []

        # 1. USGS WQP
        wqp_path = self._fetch_wqp()
        if wqp_path:
            paths.append(wqp_path)

        # 2. EPA UCMR 3
        ucmr_path = self._fetch_ucmr3()
        if ucmr_path:
            paths.append(ucmr_path)

        return paths

    def _fetch_wqp(self) -> Path | None:
        """Download glyphosate water data from Water Quality Portal."""
        cache_path = RAW_DATA_DIR / WQP_FILENAME
        if cache_path.exists():
            logger.info("Cache hit: %s", WQP_FILENAME)
            return cache_path

        try:
            logger.info("Downloading USGS WQP glyphosate water data...")
            resp = SESSION.get(WQP_BASE_URL, params=WQP_PARAMS, timeout=300)
            resp.raise_for_status()

            if len(resp.content) < 100:
                logger.warning("WQP returned very little data — may be empty")
                return None

            cache_path.write_bytes(resp.content)
            logger.info("WQP download: %d bytes", len(resp.content))
            return cache_path
        except Exception as e:
            logger.error("WQP download failed: %s", e)
            return None

    def _fetch_ucmr3(self) -> Path | None:
        """Download EPA UCMR 3 data."""
        txt_path = RAW_DATA_DIR / UCMR3_FILENAME
        if txt_path.exists():
            logger.info("Cache hit: %s", UCMR3_FILENAME)
            return txt_path

        try:
            zip_path = download_file(UCMR3_ZIP_URL, UCMR3_ZIP_FILENAME)
        except Exception as e:
            logger.warning("UCMR 3 download failed: %s", e)
            return None

        try:
            with zipfile.ZipFile(zip_path) as zf:
                # Find the main data file
                names = zf.namelist()
                match = next(
                    (f for f in names if f.lower().endswith(".txt") and "all" in f.lower()),
                    None,
                )
                if not match:
                    match = next(
                        (f for f in names if f.lower().endswith(".txt")),
                        names[0],
                    )
                data = zf.read(match)
                txt_path.write_bytes(data)
                logger.info("Extracted %s from UCMR 3 zip", match)
                return txt_path
        except zipfile.BadZipFile:
            logger.error("UCMR 3: downloaded file is not a valid ZIP")
            return None

    def parse(self, files: list[Path]) -> list[dict]:
        all_rows = []

        file_map = {f.name: f for f in files}

        # Parse WQP
        wqp_path = file_map.get(WQP_FILENAME)
        if wqp_path:
            all_rows.extend(self._parse_wqp(wqp_path))

        # Parse UCMR 3
        ucmr_path = file_map.get(UCMR3_FILENAME)
        if ucmr_path:
            all_rows.extend(self._parse_ucmr3(ucmr_path))

        return all_rows

    def _seed_water_standards(self) -> list[dict]:
        """Insert drinking water regulatory standards into tolerance_limits."""
        rows = []
        for std in WATER_STANDARDS:
            rows.append({
                "table": "food",
                "tier": 2,
                "source_name": std["source"],
                "source_url": "https://www.epa.gov/ground-water-and-drinking-water/national-primary-drinking-water-regulations",
                "report_label": f"Drinking Water Standard ({std['source']})",
                "published_date": "2024-01-01",
                "data_year": 2024,
                "food_category": std["food_category"],
                "raw_category": std["raw_commodity"],
                "samples_total": 0,
                "samples_detected": 0,
                "detection_rate": 0.0,
                "avg_ppb": None,
                "max_ppb": None,
                "original_unit": "ppb",
                "unit_conversion": 1.0,
                "methodology_note": std["regulation_reference"],
                "confidence": "high",
                "raw_file_path": None,
                "dedup_key": build_dedup_key("EPA_MCL", "drinking_water", std["source"]),
            })
        return rows

    def _parse_wqp(self, csv_path: Path) -> list[dict]:
        """Parse WQP CSV glyphosate water data."""
        try:
            df = pd.read_csv(csv_path, low_memory=False)
        except Exception as e:
            logger.error("WQP CSV parse failed: %s", e)
            return []

        logger.info("WQP: %d rows, columns: %s", len(df), list(df.columns)[:15])

        # Normalize column names
        df.columns = [c.strip() for c in df.columns]

        # Find key columns
        result_col = next(
            (c for c in df.columns if c.lower() in ("resultmeasurevalue", "resultmeasure/value")),
            None,
        )
        unit_col = next(
            (c for c in df.columns if "measureunitcode" in c.lower() or "measure/unitcode" in c.lower()),
            None,
        )
        date_col = next(
            (c for c in df.columns if "activitystartdate" in c.lower()),
            None,
        )
        state_col = next(
            (c for c in df.columns if "statecode" in c.lower()),
            None,
        )
        site_type_col = next(
            (c for c in df.columns if "sitetype" in c.lower() or "ActivityMediaName" in c),
            None,
        )
        lat_col = next((c for c in df.columns if c.lower() == "latitudemeasure"), None)
        lon_col = next((c for c in df.columns if c.lower() == "longitudemeasure"), None)
        org_col = next((c for c in df.columns if "organizationidentifier" in c.lower()), None)
        site_id_col = next((c for c in df.columns if "monitoringlocationidentifier" in c.lower()), None)
        char_col = next((c for c in df.columns if "characteristicname" in c.lower()), None)
        detection_col = next(
            (c for c in df.columns if "resultdetectioncondition" in c.lower()),
            None,
        )
        method_col = next(
            (c for c in df.columns if "resultanalyticalmethod/methodname" in c.lower()),
            None,
        )
        provider_col = next((c for c in df.columns if "providername" in c.lower()), None)

        if not result_col:
            logger.error("WQP: no result column found")
            return []

        # Filter for glyphosate only (exclude AMPA)
        if char_col:
            gly = df[
                df[char_col].str.lower().str.contains("glyphosate", na=False)
                & ~df[char_col].str.lower().str.contains("ampa", na=False)
            ].copy()
        else:
            gly = df.copy()

        if gly.empty:
            logger.warning("WQP: no glyphosate rows found")
            return []

        logger.info("WQP: %d glyphosate result rows", len(gly))

        # Determine year
        if date_col:
            gly["_year"] = pd.to_datetime(gly[date_col], errors="coerce").dt.year
            # Drop rows with unparseable dates
            gly = gly[gly["_year"].notna() & (gly["_year"] >= 1970)].copy()
        else:
            gly["_year"] = None

        # Parse result values
        gly["_ppb"] = pd.to_numeric(gly[result_col], errors="coerce")

        # Check unit — WQP uses ug/L (= ppb) for glyphosate
        if unit_col:
            gly["_unit"] = gly[unit_col].fillna("").astype(str).str.lower().str.strip()
        else:
            gly["_unit"] = "ug/l"

        # Convert units: mg/L → ppb (× 1000), ug/L → ppb (× 1)
        gly["_conversion"] = gly["_unit"].apply(
            lambda u: 1000.0 if "mg/l" in str(u) else 1.0
        )
        gly["_ppb"] = gly["_ppb"] * gly["_conversion"]

        # Detect below-detection
        gly["_below_det"] = False
        if detection_col:
            gly["_below_det"] = gly[detection_col].astype(str).str.lower().str.contains(
                "below|not detected|nd|non-detect", na=False
            )

        # Map water type
        if site_type_col:
            gly["_water_type"] = gly[site_type_col].apply(_map_site_type)
        else:
            gly["_water_type"] = "surface"

        # Map state — WQP may not include state column, use provider or org as proxy
        gly["_state"] = "National"
        if org_col:
            # Use organization as a rough proxy for geographic scope
            pass
        if provider_col:
            gly["_provider"] = gly[provider_col].fillna("").astype(str)

        # ── Build rows ──────────────────────────────────────────────
        rows = []

        # Aggregate by (water_type, year) — national level
        agg_groups = gly.groupby(
            ["_water_type", "_year"], dropna=False
        )

        for (wtype, year), group in agg_groups:
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
                "source_name": "USGS_WQP",
                "source_url": "https://waterqualitydata.us",
                "report_label": f"USGS WQP Glyphosate Water {year_clean}",
                "data_year": year_clean,
                "state": "National",
                "water_type": wtype_clean,
                "is_aggregate": 1,
                "samples_total": total,
                "samples_detected": n_detected,
                "detection_rate": detection_rate,
                "avg_ppb": avg_ppb,
                "max_ppb": max_ppb,
                "methodology_note": (
                    "USGS Water Quality Portal aggregate. "
                    f"{total} water samples for glyphosate "
                    f"({wtype_clean}), {year_clean}. Units: ug/L (ppb)."
                ),
                "confidence": "high",
                "dedup_key": build_dedup_key("USGS_WQP", wtype_clean, year_clean),
            })

        logger.info("WQP: parsed %d aggregate rows", len(rows))
        return rows

    def _parse_ucmr3(self, txt_path: Path) -> list[dict]:
        """Parse EPA UCMR 3 drinking water data for glyphosate."""
        try:
            df = pd.read_csv(txt_path, sep="\t", low_memory=False, encoding="latin-1")
        except Exception as e:
            logger.error("UCMR 3 parse failed: %s", e)
            return []

        df.columns = [c.strip() for c in df.columns]
        logger.info("UCMR 3: %d rows, columns: %s", len(df), list(df.columns)[:20])

        # Find contaminant column
        chem_col = next(
            (c for c in df.columns if any(
                t in c.lower() for t in ["contaminant", "chemical", "analyte", "parameter"]
            )),
            None,
        )
        if not chem_col:
            # Try to find glyphosate in any column's values
            for col in df.columns:
                if df[col].dtype == object:
                    if df[col].str.lower().str.contains("glyphosate", na=False).any():
                        chem_col = col
                        break

        if not chem_col:
            logger.warning("UCMR 3: no contaminant column found — skipping")
            return []

        # Filter for glyphosate
        gly = df[df[chem_col].str.lower().str.contains("glyphosate", na=False)].copy()
        if gly.empty:
            logger.warning("UCMR 3: no glyphosate rows found")
            return []

        logger.info("UCMR 3: %d glyphosate rows", len(gly))

        # Find result value column
        result_col = next(
            (c for c in gly.columns if any(
                t in c.lower() for t in ["result", "value", "analyticalresult", "level"]
            )),
            None,
        )
        # Find state column
        state_col = next(
            (c for c in gly.columns if any(
                t in c.lower() for t in ["state", "pws_state", "facility_state"]
            )),
            None,
        )
        # Find date/year column
        year_col = next(
            (c for c in gly.columns if any(
                t in c.lower() for t in ["year", "date", "sampling"]
            )),
            None,
        )
        # Find detection indicator
        mrl_col = next(
            (c for c in gly.columns if any(
                t in c.lower() for t in ["mrl", "reporting", "detection_limit", "min_report"]
            )),
            None,
        )

        # Parse result values
        if result_col:
            gly["_ppb"] = pd.to_numeric(gly[result_col], errors="coerce")
        else:
            gly["_ppb"] = None

        # Parse year
        if year_col:
            gly["_year"] = pd.to_numeric(gly[year_col], errors="coerce")
            if gly["_year"].max() > 3000:
                # Might be a date string
                gly["_year"] = pd.to_datetime(gly[year_col], errors="coerce").dt.year
        else:
            gly["_year"] = 2014  # UCMR 3 midpoint

        # Parse state
        if state_col:
            gly["_state"] = gly[state_col].astype(str).str.strip()
        else:
            gly["_state"] = "Unknown"

        # Build aggregate rows by state
        rows = []
        for state, group in gly.groupby("_state", dropna=False):
            state_clean = str(state) if pd.notna(state) else "Unknown"
            years = group["_year"].dropna().unique()
            year_val = int(years[0]) if len(years) > 0 else 2014

            total = len(group)
            detected = group[group["_ppb"].notna() & (group["_ppb"] > 0)]
            n_detected = len(detected)
            detection_rate = round(n_detected / total, 4) if total > 0 else 0
            avg_ppb = round(detected["_ppb"].mean(), 2) if len(detected) > 0 else None
            max_ppb = round(detected["_ppb"].max(), 2) if len(detected) > 0 else None

            rows.append({
                "table": "water",
                "source_name": "EPA_UCMR3",
                "source_url": "https://www.epa.gov/dwucmr/occurrence-data-unregulated-contaminant-monitoring-rule",
                "report_label": f"EPA UCMR 3 Glyphosate Drinking Water {state_clean}",
                "data_year": year_val,
                "state": state_clean,
                "water_type": "drinking",
                "is_aggregate": 1,
                "samples_total": total,
                "samples_detected": n_detected,
                "detection_rate": detection_rate,
                "avg_ppb": avg_ppb,
                "max_ppb": max_ppb,
                "methodology_note": (
                    "EPA Unregulated Contaminant Monitoring Rule 3 (2013-2015). "
                    f"Drinking water glyphosate results for {state_clean}. "
                    f"{total} public water system samples. Units: ug/L (ppb)."
                ),
                "confidence": "high",
                "dedup_key": build_dedup_key("EPA_UCMR3", state_clean, year_val),
            })

        logger.info("UCMR 3: parsed %d aggregate rows", len(rows))
        return rows
