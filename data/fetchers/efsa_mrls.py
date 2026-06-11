"""
fetchers/efsa_mrls.py

EU MRLs from DG SANTE Pesticides Datalake API.

Source:
  EU Pesticides Database — Bulk MRL Download
  https://api.datalake.sante.service.ec.europa.eu/sante/pesticides/pesticide-residues-mrls-download

Content:
  All EU Maximum Residue Limits (Regulation (EC) No 396/2005) for pesticides
  across all food commodities. These are generally the strictest internationally.

API Details (from PDF documentation):
  - Bulk download: /sante/pesticides/pesticide-residues-mrls-download
  - Parameters: language_code=EN, format=json, api-version=v3.0
  - No authentication required (open access)
  - Returns JSON array of MRL records
  - Key fields: mrl_value_only, applicability, pesticide_residue_name, product_name

Data Handling:
  - Filter: applicability = 1 (current applicable MRLs only)
  - Use mrl_value_only (clean numeric) not mrl_value (has LOD markers)
  - mrl_lod = "*" means MRL at limit of detection (0.01 mg/kg = 10 ppb)
  - Strip footnote codes from pesticide names: (F), (R), (A), (B)
  - product_name is English, usable for category mapping
"""

import json
import logging
import re
from pathlib import Path

from fetchers.base import BaseFetcher, RAW_DATA_DIR, SESSION
from db.database import build_dedup_key, normalize_category, get_connection, log_ingest

logger = logging.getLogger(__name__)

SOURCE_NAME = "EFSA_MRLs"
BASE_URL = "https://api.datalake.sante.service.ec.europa.eu/sante/pesticides"
API_VERSION = "v3.0"

# Footnote codes to strip from pesticide names
_FOOTNOTE_RE = re.compile(r"\s*\([A-Z]\)\s*$")


class EFSAMrlFetcher(BaseFetcher):
    """Fetch EU MRLs from DG SANTE Pesticides Datalake API."""

    SOURCE_NAME = SOURCE_NAME

    def run(self) -> dict:
        """Override run() to insert into international_mrls table directly."""
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

        logger.info("%s parsed %d international MRL entries, inserting...", self.SOURCE_NAME, len(rows))

        inserted = skipped = failed = 0
        with get_connection() as conn:
            for row in rows:
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO international_mrls
                            (food_category, raw_commodity, pesticide,
                             country_region, mrl_ppm, mrl_ppb,
                             regulatory_body, source_url, dedup_key)
                        VALUES
                            (:food_category, :raw_commodity, :pesticide,
                             :country_region, :mrl_ppm, :mrl_ppb,
                             :regulatory_body, :source_url, :dedup_key)
                        """,
                        row,
                    )
                    changes = conn.execute("SELECT changes()").fetchone()[0]
                    if changes:
                        inserted += 1
                    else:
                        skipped += 1
                except Exception as e:
                    logger.error("Insert failed for %s: %s", row.get("pesticide"), e)
                    failed += 1

        log_ingest(self.SOURCE_NAME, "success" if failed == 0 else "partial",
                   inserted, skipped, failed)
        logger.info("%s complete: inserted=%d skipped=%d failed=%d",
                    self.SOURCE_NAME, inserted, skipped, failed)
        return {"inserted": inserted, "skipped": skipped, "failed": failed}

    def fetch(self) -> list[Path]:
        """Download EU MRL data via bulk API."""
        dest = RAW_DATA_DIR / "efsa_mrls.json"

        # Check cache
        if dest.exists():
            logger.info("EFSA MRL cache hit: %s (%d bytes)", dest.name, dest.stat().st_size)
            return [dest]

        url = f"{BASE_URL}/pesticide-residues-mrls-download"
        params = {"language_code": "EN", "format": "json", "api-version": API_VERSION}

        try:
            logger.info("EFSA MRL: fetching from DG SANTE API...")
            logger.info("  URL: %s", url)
            resp = SESSION.get(url, params=params, timeout=300)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            logger.info("EFSA MRL: downloaded %d bytes", len(resp.content))
            return [dest]
        except Exception as e:
            logger.error("EFSA MRL fetch failed: %s", e)

        # Fallback: check for local file
        for f in RAW_DATA_DIR.glob("efsa_mrl*"):
            if f.suffix in ('.json', '.xlsx', '.csv'):
                logger.info("EFSA MRL: using local file %s", f.name)
                return [f]

        logger.error("EFSA MRL: could not download MRL data.")
        return []

    def parse(self, files: list[Path]) -> list[dict]:
        """Parse EU MRL JSON data into international_mrls rows."""
        if not files:
            return []

        path = files[0]
        logger.info("EFSA MRL: parsing %s", path.name)

        # Parse NDJSON (one JSON object per line) or JSON array
        records = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if isinstance(rec, list):
                            records.extend(rec)
                        else:
                            records.append(rec)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error("EFSA MRL: failed to read file: %s", e)
            return []

        logger.info("EFSA MRL: %d raw records", len(records))

        rows = []
        skipped = 0

        for rec in records:
            # Only current applicable MRLs
            applicability = rec.get("applicability")
            if applicability is not None and int(applicability) != 1:
                skipped += 1
                continue

            # Parse MRL — use mrl_value_only (clean numeric)
            try:
                mrl_ppm = float(rec.get("mrl_value_only", 0))
            except (TypeError, ValueError):
                skipped += 1
                continue

            if mrl_ppm <= 0:
                skipped += 1
                continue

            mrl_ppb = mrl_ppm * 1000.0

            # Clean pesticide name
            raw_pest = str(rec.get("pesticide_residue_name") or "").strip()
            pesticide = _FOOTNOTE_RE.sub("", raw_pest).strip().lower()
            if not pesticide:
                skipped += 1
                continue

            # Map product to canonical food category
            product_name = str(rec.get("product_name") or "").strip()
            food_category = normalize_category(product_name.lower())
            if not food_category:
                food_category = product_name.lower()

            dedup = build_dedup_key("EFSA", food_category, pesticide, "EU")
            rows.append({
                "food_category": food_category,
                "raw_commodity": product_name,
                "pesticide": pesticide,
                "country_region": "EU",
                "mrl_ppm": mrl_ppm,
                "mrl_ppb": mrl_ppb,
                "regulatory_body": "EFSA",
                "source_url": "https://food.ec.europa.eu/plants/pesticides/eu-pesticides-database_en",
                "dedup_key": dedup,
            })

        logger.info("EFSA MRL: parsed %d rows, skipped %d", len(rows), skipped)
        return rows
