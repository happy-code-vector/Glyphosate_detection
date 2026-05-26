"""
fetchers/water_quality.py

Multi-contaminant water monitoring data from USGS Water Quality Portal and EPA UCMR.

Supported contaminants: glyphosate, lead, atrazine.
Each is queried separately from USGS WQP with contaminant-specific parameters.

Sources:
  1. USGS WQP — surface water + groundwater detections nationwide
     API: https://waterqualitydata.us/data/Result/search
  2. EPA UCMR 3 — drinking water data (2013-2015)
     URL: https://www.epa.gov/dwucmr/occurrence-data-unregulated-contaminant-monitoring-rule
  3. Drinking water regulatory standards (EPA MCL, EU DWD, Health Canada)

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
        paths = []
        wqp_path = self._fetch_wqp()
        if wqp_path:
            paths.append(wqp_path)
        return paths

    def _fetch_wqp(self) -> Path | None:
        """Download water data from Water Quality Portal for this contaminant."""
        cache_path = RAW_DATA_DIR / self.wqp_filename
        if cache_path.exists():
            logger.info("Cache hit: %s", self.wqp_filename)
            return cache_path

        params = {
            "characteristicName": self.config["wqp_characteristic"],
            "sampleMedia": "Water",
            "mimeType": "csv",
            "sorted": "no",
            "providers": "STORET,NWIS",
        }

        try:
            logger.info("Downloading USGS WQP %s water data...", self.contaminant)
            resp = SESSION.get(WQP_BASE_URL, params=params, timeout=300)
            resp.raise_for_status()

            if len(resp.content) < 100:
                logger.warning("WQP returned very little data for %s", self.contaminant)
                return None

            cache_path.write_bytes(resp.content)
            logger.info("WQP %s download: %d bytes", self.contaminant, len(resp.content))
            return cache_path
        except Exception as e:
            logger.error("WQP %s download failed: %s", self.contaminant, e)
            return None

    def parse(self, files: list[Path]) -> list[dict]:
        all_rows = []
        file_map = {f.name: f for f in files}
        wqp_path = file_map.get(self.wqp_filename)
        if wqp_path:
            all_rows.extend(self._parse_wqp(wqp_path))
        return all_rows

    def _parse_wqp(self, csv_path: Path) -> list[dict]:
        """Parse WQP CSV water data for this contaminant."""
        try:
            df = pd.read_csv(csv_path, low_memory=False)
        except Exception as e:
            logger.error("WQP CSV parse failed for %s: %s", self.contaminant, e)
            return []

        logger.info("WQP %s: %d rows, columns: %s",
                     self.contaminant, len(df), list(df.columns)[:15])

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
        site_type_col = next(
            (c for c in df.columns if "sitetype" in c.lower() or "ActivityMediaName" in c),
            None,
        )
        char_col = next(
            (c for c in df.columns if "characteristicname" in c.lower()), None,
        )
        detection_col = next(
            (c for c in df.columns if "resultdetectioncondition" in c.lower()),
            None,
        )

        if not result_col:
            logger.error("WQP %s: no result column found", self.contaminant)
            return []

        # Filter for this contaminant only
        data = df.copy()
        if char_col:
            contam_name = self.config["wqp_characteristic"].lower()
            data = data[
                data[char_col].str.lower().str.contains(contam_name, na=False)
            ].copy()

        if data.empty:
            logger.warning("WQP %s: no rows found", self.contaminant)
            return []

        logger.info("WQP %s: %d result rows", self.contaminant, len(data))

        # Determine year
        if date_col:
            data["_year"] = pd.to_datetime(data[date_col], errors="coerce").dt.year
            data = data[data["_year"].notna() & (data["_year"] >= 1970)].copy()
        else:
            data["_year"] = None

        # Parse result values
        data["_ppb"] = pd.to_numeric(data[result_col], errors="coerce")

        # Unit conversion: mg/L → ppb (× 1000), ug/L → ppb (× 1)
        if unit_col:
            data["_unit"] = data[unit_col].fillna("").astype(str).str.lower().str.strip()
        else:
            data["_unit"] = "ug/l"
        data["_conversion"] = data["_unit"].apply(
            lambda u: 1000.0 if "mg/l" in str(u) else 1.0
        )
        data["_ppb"] = data["_ppb"] * data["_conversion"]

        # Detect below-detection
        data["_below_det"] = False
        if detection_col:
            data["_below_det"] = data[detection_col].astype(str).str.lower().str.contains(
                "below|not detected|nd|non-detect", na=False
            )

        # Map water type
        if site_type_col:
            data["_water_type"] = data[site_type_col].apply(_map_site_type)
        else:
            data["_water_type"] = "surface"

        # ── Build rows ──────────────────────────────────────────────
        rows = []
        agg_groups = data.groupby(["_water_type", "_year"], dropna=False)

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
                "contaminant": self.contaminant,
                "source_name": "USGS_WQP",
                "source_url": "https://waterqualitydata.us",
                "report_label": f"USGS WQP {self.contaminant.title()} Water {year_clean}",
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
                    f"USGS Water Quality Portal aggregate. "
                    f"{total} water samples for {self.contaminant} "
                    f"({wtype_clean}), {year_clean}. Units: ug/L (ppb)."
                ),
                "confidence": "high",
                "dedup_key": build_dedup_key(
                    self.contaminant, "USGS_WQP", wtype_clean, year_clean
                ),
            })

        logger.info("WQP %s: parsed %d aggregate rows", self.contaminant, len(rows))
        return rows
