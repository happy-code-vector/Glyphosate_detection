"""
seed_alternatives.py

Seed the alternatives table from PurityIQ_Alternatives_Mapping.xlsx.
Groups alternatives by flagged product and builds JSON arrays.

Usage:
    python seed_alternatives.py
    python seed_alternatives.py --dry-run
"""

import argparse
import json
import logging
import sqlite3
from collections import defaultdict
from pathlib import Path

import pandas as pd

from db.database import initialize, get_connection, build_dedup_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_alternatives")

EXCEL_PATH = Path(__file__).parent.parent / "research" / "PurityIQ_Alternatives_Mapping.xlsx"


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    return (
        text.lower()
        .strip()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("(", "")
        .replace(")", "")
        .replace("'", "")
        .replace('"', "")
        .replace(",", "")
        .replace("__", "_")
        .strip("_")
    )


def seed_alternatives(dry_run=False):
    """Read the Excel file and seed the alternatives table."""
    if not EXCEL_PATH.exists():
        logger.error("Alternatives mapping file not found: %s", EXCEL_PATH)
        return

    df = pd.read_excel(EXCEL_PATH, sheet_name="Alternatives Mapping")
    logger.info("Read %d rows from Alternatives Mapping", len(df))

    # Group by flagged product to build alternatives arrays
    grouped = defaultdict(lambda: {
        "category": "",
        "flagged_product": "",
        "brand": "",
        "contaminants": "",
        "severity": "",
        "action_label": "",
        "alternatives": [],
    })

    for _, row in df.iterrows():
        flagged = str(row["Flagged Product"]).strip()
        if not flagged or flagged == "nan":
            continue

        key = slugify(flagged)
        group = grouped[key]

        group["category"] = str(row.get("Category", "")).strip()
        group["flagged_product"] = flagged
        group["brand"] = str(row.get("Brand", "")).strip()
        group["contaminants"] = str(row.get("Primary Contaminant(s)", "")).strip()
        group["severity"] = str(row.get("Severity", "")).strip()
        group["action_label"] = str(row.get("Action Label", "")).strip()

        alt_name = str(row.get("Alternative Product", "")).strip()
        if alt_name and alt_name != "nan":
            group["alternatives"].append({
                "name": alt_name,
                "brand": str(row.get("Alternative Brand", "")).strip(),
                "why_better": str(row.get("Why It's Clean", "")).strip(),
                "certification": str(row.get("Certification", "")).strip(),
                "affiliate_eligible": str(row.get("Affiliate Opportunity", "")).strip().lower() == "yes",
            })

    logger.info("Grouped into %d unique flagged products", len(grouped))

    # Build rows for insertion
    rows = []
    for key, data in grouped.items():
        if not data["alternatives"]:
            continue

        rows.append({
            "lookup_key": key,
            "lookup_type": "product_slug",
            "flagged_product_name": data["flagged_product"],
            "flagged_brand": data["brand"],
            "risk_label": data["action_label"],
            "flag_summary": f"{data['contaminants']} ({data['severity']})",
            "alternatives": json.dumps(data["alternatives"]),
        })

    logger.info("Prepared %d alternative records", len(rows))

    if dry_run:
        for row in rows[:10]:
            alts = json.loads(row["alternatives"])
            logger.info("  [DRY RUN] %s → %d alternatives", row["lookup_key"], len(alts))
        if len(rows) > 10:
            logger.info("  ... and %d more", len(rows) - 10)
        return

    # Insert into database
    inserted = skipped = failed = 0
    with get_connection() as conn:
        for row in rows:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO alternatives (
                        lookup_key, lookup_type, flagged_product_name,
                        flagged_brand, risk_label, flag_summary, alternatives, last_updated
                    ) VALUES (
                        :lookup_key, :lookup_type, :flagged_product_name,
                        :flagged_brand, :risk_label, :flag_summary, :alternatives,
                        datetime('now')
                    )
                """, row)
                changes = conn.execute("SELECT changes()").fetchone()[0]
                if changes:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.error("Failed to insert %s: %s", row["lookup_key"], e)
                failed += 1

    logger.info("Alternatives: inserted=%d, skipped=%d, failed=%d", inserted, skipped, failed)


def main():
    parser = argparse.ArgumentParser(description="Seed alternatives table")
    parser.add_argument("--dry-run", action="store_true", help="Print without inserting")
    args = parser.parse_args()

    logger.info("Initializing database")
    initialize()

    logger.info("=== Seeding alternatives table ===")
    seed_alternatives(dry_run=args.dry_run)

    logger.info("Done!")


if __name__ == "__main__":
    main()
