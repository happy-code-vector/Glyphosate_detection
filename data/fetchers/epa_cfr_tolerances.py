"""
fetchers/epa_cfr_tolerances.py

EPA 40 CFR Part 180 — Full Pesticide Tolerance Database from XML.

Source:
  GovInfo — CFR Title 40, Volume 24, Part 180
  https://www.govinfo.gov/content/pkg/CFR-2014-title40-vol24/xml/CFR-2014-title40-vol24-part180.xml

Content:
  All pesticide tolerances from 40 CFR Part 180 (Subpart C — Specific Tolerances).
  Each section (180.xxx) defines tolerances for one pesticide across all commodities.

  12,600+ tolerance entries covering:
  - 370+ pesticides
  - 1,700+ food commodities
  - Tolerance values in ppm (converted to ppb for storage)

XML Structure:
  <CFRGRANULE>
    <PART>
      <SECTION>
        <SECTNO>180.364</SECTNO>
        <SUBJECT>Glyphosate; tolerances for residues.</SUBJECT>
        <GPOTABLE>
          <ROW>
            <ENT>Commodity name</ENT>
            <ENT>0.2</ENT>  <!-- ppm -->
          </ROW>
        </GPOTABLE>
      </SECTION>
    </PART>
  </CFRGRANULE>
"""

import logging
import re
from pathlib import Path

from fetchers.base import BaseFetcher, RAW_DATA_DIR, SESSION
from db.database import normalize_category, build_dedup_key, get_connection, log_ingest

logger = logging.getLogger(__name__)

SOURCE_NAME = "EPA_CFR_Part180"
XML_URL = "https://www.govinfo.gov/content/pkg/CFR-2014-title40-vol24/xml/CFR-2014-title40-vol24-part180.xml"


class EPACFRTolerancesFetcher(BaseFetcher):
    """Fetch EPA tolerances from 40 CFR Part 180 XML."""

    SOURCE_NAME = SOURCE_NAME

    def run(self) -> dict:
        """Override run() to insert into tolerance_limits table."""
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

        logger.info("%s parsed %d tolerance entries, inserting...", self.SOURCE_NAME, len(rows))

        inserted = skipped = failed = 0
        with get_connection() as conn:
            for row in rows:
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO tolerance_limits
                            (food_category, raw_commodity, tolerance_ppm, tolerance_ppb,
                             contaminant, source, regulation_reference, dedup_key)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["food_category"], row["raw_commodity"],
                            row["tolerance_ppm"], row["tolerance_ppb"],
                            row["contaminant"], row["source"],
                            row["regulation_reference"], row["dedup_key"],
                        ),
                    )
                    changes = conn.execute("SELECT changes()").fetchone()[0]
                    if changes:
                        inserted += 1
                    else:
                        skipped += 1
                except Exception as e:
                    logger.error("Insert failed for %s/%s: %s", row["contaminant"], row["raw_commodity"], e)
                    failed += 1

        log_ingest(self.SOURCE_NAME, "success" if failed == 0 else "partial",
                   inserted, skipped, failed)
        logger.info("%s complete: inserted=%d skipped=%d failed=%d",
                    self.SOURCE_NAME, inserted, skipped, failed)
        return {"inserted": inserted, "skipped": skipped, "failed": failed}

    def fetch(self) -> list[Path]:
        """Download EPA 40 CFR Part 180 XML."""
        dest = RAW_DATA_DIR / "cfr_40_part180.xml"

        if dest.exists():
            logger.info("EPA CFR cache hit: %s (%d bytes)", dest.name, dest.stat().st_size)
            return [dest]

        try:
            logger.info("EPA CFR: downloading from govinfo.gov...")
            resp = SESSION.get(XML_URL, timeout=180)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            logger.info("EPA CFR: downloaded %d bytes", len(resp.content))
            return [dest]
        except Exception as e:
            logger.error("EPA CFR download failed: %s", e)
            raise

    def parse(self, files: list[Path]) -> list[dict]:
        """Parse EPA XML into tolerance_limits rows."""
        import xml.etree.ElementTree as ET

        if not files:
            return []

        path = files[0]
        logger.info("EPA CFR: parsing %s", path.name)

        try:
            tree = ET.parse(path)
            root = tree.getroot()
        except Exception as e:
            logger.error("EPA CFR: failed to parse XML: %s", e)
            return []

        rows = []
        for sec in root.findall(".//SECTION"):
            sectno = sec.find("SECTNO")
            subject = sec.find("SUBJECT")
            if sectno is None or subject is None:
                continue

            section_num = (sectno.text or "").strip().replace("§", "").strip()
            raw_subject = (subject.text or "").strip()

            # Extract pesticide name from subject (before semicolon)
            pesticide = raw_subject.split(";")[0].strip()
            if not pesticide:
                continue

            # Find GPOTABLE elements
            for table in sec.findall(".//GPOTABLE"):
                for row in table.findall("ROW"):
                    cells = row.findall("ENT")
                    if len(cells) < 2:
                        continue

                    commodity = "".join(cells[0].itertext()).strip()
                    ppm_str = "".join(cells[1].itertext()).strip()

                    # Skip headers and empty rows
                    if not commodity or commodity.lower() in ("commodity", "parts per million", ""):
                        continue

                    # Parse ppm
                    try:
                        ppm = float(ppm_str.replace(",", ""))
                    except ValueError:
                        continue

                    if ppm <= 0:
                        continue

                    # Normalize commodity name
                    food_category = normalize_category(commodity.lower())
                    if not food_category:
                        food_category = commodity.lower()

                    dedup = build_dedup_key(SOURCE_NAME, food_category, pesticide.lower())
                    rows.append({
                        "food_category": food_category,
                        "raw_commodity": commodity,
                        "tolerance_ppm": ppm,
                        "tolerance_ppb": ppm * 1000.0,
                        "contaminant": pesticide.lower(),
                        "source": SOURCE_NAME,
                        "regulation_reference": f"40 CFR {section_num}",
                        "dedup_key": dedup,
                    })

        logger.info("EPA CFR: parsed %d tolerance entries from %d sections",
                    len(rows), len(set(r["regulation_reference"] for r in rows)))
        return rows
