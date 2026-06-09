"""
data/migrate_to_firestore.py
Migrate all ResidueIQ SQLite data to Google Firestore.

Usage:
    # Make sure firebase-service-account.json is in project root
    python data/migrate_to_firestore.py

    # Custom paths
    python data/migrate_to_firestore.py --db data/residueiq.db --cred firebase-service-account.json
"""

import argparse
import sqlite3
import sys
import logging
from pathlib import Path
from datetime import datetime

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    print("ERROR: firebase-admin not installed. Run: pip install firebase-admin>=6.2.0")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Firestore batch limit ──
BATCH_LIMIT = 500

# ── Tables to migrate (table_name → firestore_collection) ──
TABLES = [
    "product_tests",
    "category_summaries",
    "category_aliases",
    "tolerance_limits",
    "certified_products",
    "international_mrls",
    "water_tests",
    "biomonitoring",
    "ingest_log",
    "ingredients",
    "regulatory_flags",
    "commodities",
    "alternatives",
]

# ── Columns that are 0/1 integers → booleans ──
BOOL_COLUMNS = {
    "product_tests": ["below_detection", "is_organic", "is_grf_certified"],
    "category_summaries": ["is_organic"],
    "water_tests": ["below_detection", "is_aggregate"],
    "tolerance_limits": [],
    "certified_products": [],
    "international_mrls": [],
    "biomonitoring": [],
    "category_aliases": [],
    "ingest_log": [],
    "ingredients": [],
    "regulatory_flags": [],
    "commodities": ["dirty_dozen"],
    "alternatives": [],
}

# ── Columns to skip (auto-generated in SQLite, not needed in Firestore) ──
SKIP_COLUMNS = {
    "ingest_log": ["id"],
    "ingredients": [],
    "regulatory_flags": [],
    "commodities": [],
    "alternatives": [],
}


def sanitize_doc_id(value: str) -> str:
    """Sanitize a string for use as a Firestore document ID.
    Firestore doesn't allow '/' in document IDs."""
    return value.replace("/", "_").replace("\\", "_")


def get_document_id(table: str, row: dict) -> str | None:
    """Determine the Firestore document ID for a row."""
    if table == "category_aliases":
        return row.get("alias", None)
    if table == "ingest_log":
        return None  # auto-generate
    if table == "ingredients":
        return row.get("ingredient_id", None)
    if table == "regulatory_flags":
        return row.get("flag_id", None)
    if table == "commodities":
        return row.get("commodity_slug", None)
    if table == "alternatives":
        return row.get("lookup_key", None)
    return row.get("dedup_key", None)


def convert_row(table: str, row: dict) -> dict:
    """Convert SQLite row types to Firestore-compatible types."""
    bools = BOOL_COLUMNS.get(table, [])
    skips = SKIP_COLUMNS.get(table, [])

    converted = {}
    for key, value in row.items():
        if key in skips:
            continue

        # None stays None
        if value is None:
            converted[key] = None
            continue

        # Boolean conversion
        if key in bools:
            converted[key] = bool(value)
            continue

        # Timestamp-like strings → keep as strings (Firestore timestamps
        # are tricky with inconsistent formats across sources)
        converted[key] = value

    return converted


def read_table(conn: sqlite3.Connection, table: str) -> list[dict]:
    """Read all rows from a SQLite table."""
    cursor = conn.execute(f"SELECT * FROM {table}")
    columns = [desc[0] for desc in cursor.description]
    rows = []
    for row in cursor.fetchall():
        rows.append(dict(zip(columns, row)))
    return rows


def batch_write(db, collection_name: str, rows: list[dict], id_func) -> int:
    """Write rows to a Firestore collection in batches."""
    written = 0
    batch = db.batch()
    batch_count = 0

    for row in rows:
        doc_id = id_func(row)
        if doc_id:
            ref = db.collection(collection_name).document(doc_id)
        else:
            ref = db.collection(collection_name).document()

        batch.set(ref, row)
        batch_count += 1
        written += 1

        if batch_count >= BATCH_LIMIT:
            batch.commit()
            logger.info("  Committed batch of %d docs to %s", batch_count, collection_name)
            batch = db.batch()
            batch_count = 0

    # Commit remaining
    if batch_count > 0:
        batch.commit()
        logger.info("  Committed final batch of %d docs to %s", batch_count, collection_name)

    return written


def compute_risk_level(detection_rate: float | None, max_ppb: float | None) -> str:
    """Compute risk level matching the SQLite CASE logic."""
    if detection_rate is None and max_ppb is None:
        return "unknown"
    if detection_rate is not None:
        if detection_rate >= 0.66:
            return "high"
        if detection_rate >= 0.31:
            return "medium"
        if detection_rate > 0.0:
            return "low"
    return "none"


def compute_product_risk(row: dict) -> str:
    """Compute product risk level matching the SQLite CASE logic."""
    if row.get("is_grf_certified"):
        return "certified_grf"
    if row.get("is_organic") and row.get("below_detection"):
        return "organic_clean"
    if row.get("is_organic"):
        return "organic_detected"
    if row.get("below_detection"):
        return "none"
    ppb = row.get("measured_ppb")
    if ppb is not None:
        if ppb >= 500:
            return "high"
        if ppb >= 100:
            return "medium"
        if ppb > 0:
            return "low"
    return "unknown"


def source_priority(source_name: str) -> int:
    """Source priority for best-summary selection."""
    return {"FDA": 3, "CFIA": 2, "EFSA": 1}.get(source_name, 0)


def precompute_food_overview(db, conn: sqlite3.Connection):
    """
    Pre-compute app_food_overview collection.
    Mirrors the SQLite view: one doc per food_category+contaminant with best-source stats.
    """
    logger.info("Pre-computing app_food_overview...")

    # Get all category summaries (all contaminants)
    summaries = conn.execute("""
        SELECT food_category, contaminant, source_name, data_year, samples_total,
               samples_detected, detection_rate, avg_ppb, max_ppb, confidence
        FROM category_summaries
    """).fetchall()

    # Group by (food_category, contaminant), pick best source
    best = {}
    for row in summaries:
        cat, contaminant = row[0], row[1]
        priority = source_priority(row[2])
        key = (cat, contaminant)
        if key not in best or (priority, row[3]) > (source_priority(best[key][2]), best[key][3]):
            best[key] = row

    # Product stats per (category, contaminant)
    product_stats = conn.execute("""
        SELECT food_category, contaminant,
               COUNT(*) AS total,
               SUM(CASE WHEN below_detection = 0 THEN 1 ELSE 0 END) AS with_detection,
               ROUND(AVG(measured_ppb), 1) AS avg_ppb,
               MAX(measured_ppb) AS max_ppb
        FROM product_tests
        GROUP BY food_category, contaminant
    """).fetchall()
    ps_map = {(r[0], r[1]): r for r in product_stats}

    # Certified product counts
    cert_counts = conn.execute("""
        SELECT food_category, COUNT(*) AS cnt
        FROM certified_products
        GROUP BY food_category
    """).fetchall()
    cc_map = {r[0]: r[1] for r in cert_counts}

    # Build and write documents
    docs = []
    for (cat, contaminant), row in best.items():
        food_category, contam, source_name, data_year, samples_total, samples_detected, detection_rate, avg_ppb, max_ppb, confidence = row
        ps = ps_map.get((cat, contaminant))
        doc_id = sanitize_doc_id(f"{cat}_{contaminant}")
        docs.append({
            "food_category": food_category,
            "contaminant": contaminant,
            "best_source": source_name,
            "best_data_year": data_year,
            "detection_rate": detection_rate,
            "avg_ppb": avg_ppb,
            "max_ppb": max_ppb,
            "samples_total": samples_total,
            "samples_detected": samples_detected,
            "risk_level": compute_risk_level(detection_rate, max_ppb),
            "confidence": confidence,
            "total_products_tested": ps[2] if ps else 0,
            "products_with_detection": ps[3] if ps else 0,
            "avg_product_ppb": ps[4] if ps else 0,
            "max_product_ppb": ps[5] if ps else 0,
            "certified_products_available": cc_map.get(cat, 0),
            "_doc_id": doc_id,
        })

    batch = db.batch()
    count = 0
    for doc in docs:
        doc_id = doc.pop("_doc_id")
        ref = db.collection("app_food_overview").document(doc_id)
        batch.set(ref, doc)
        count += 1
        if count >= BATCH_LIMIT:
            batch.commit()
            batch = db.batch()
            count = 0
    if count > 0:
        batch.commit()
    logger.info("  Wrote %d app_food_overview documents", len(docs))


def precompute_product_lookup(db, conn: sqlite3.Connection):
    """
    Pre-compute app_product_lookup collection.
    Same as product_tests but with computed risk_level. All contaminants.
    """
    logger.info("Pre-computing app_product_lookup...")

    rows = conn.execute("""
        SELECT product_name, food_category, contaminant, source_name, report_label,
               data_year, measured_ppb, below_detection, limit_of_detection,
               is_organic, is_grf_certified, confidence, methodology_note,
               source_url, updated_at, dedup_key
        FROM product_tests
    """).fetchall()
    columns = ["product_name", "food_category", "contaminant", "source_name", "report_label",
               "data_year", "measured_ppb", "below_detection", "limit_of_detection",
               "is_organic", "is_grf_certified", "confidence", "methodology_note",
               "source_url", "updated_at", "dedup_key"]

    batch = db.batch()
    count = 0
    for row in rows:
        d = dict(zip(columns, row))
        d["below_detection"] = bool(d["below_detection"])
        d["is_organic"] = bool(d["is_organic"])
        d["is_grf_certified"] = bool(d["is_grf_certified"])
        d["risk_level"] = compute_product_risk(d)

        ref = db.collection("app_product_lookup").document(d.pop("dedup_key"))
        batch.set(ref, d)
        count += 1

        if count >= BATCH_LIMIT:
            batch.commit()
            batch = db.batch()
            count = 0

    if count > 0:
        batch.commit()
    logger.info("  Wrote %d app_product_lookup documents", len(rows))


def precompute_regulatory_limits(db, conn: sqlite3.Connection):
    """Pre-compute app_regulatory_limits: detection vs tolerance comparison."""
    logger.info("Pre-computing app_regulatory_limits...")

    rows = conn.execute("""
        SELECT cs.food_category, cs.contaminant, cs.source_name, cs.data_year, cs.detection_rate,
               cs.max_ppb AS measured_max_ppb, cs.avg_ppb AS measured_avg_ppb,
               tl.tolerance_ppb AS epa_tolerance_ppb,
               tl.tolerance_ppm AS epa_tolerance_ppm,
               tl.source AS tolerance_source,
               tl.regulation_reference,
               CASE
                   WHEN tl.tolerance_ppb > 0 AND cs.max_ppb IS NOT NULL
                   THEN ROUND(cs.max_ppb / tl.tolerance_ppb * 100.0, 1)
                   ELSE NULL
               END AS pct_of_tolerance
        FROM category_summaries cs
        LEFT JOIN tolerance_limits tl
            ON cs.food_category = tl.food_category
            AND cs.contaminant = tl.contaminant
        WHERE cs.detection_rate > 0
        ORDER BY cs.contaminant, cs.food_category, cs.data_year DESC
    """).fetchall()

    # Group by (food_category, contaminant) → array of comparisons
    columns = ["food_category", "contaminant", "source_name", "data_year", "detection_rate",
               "measured_max_ppb", "measured_avg_ppb", "epa_tolerance_ppb",
               "epa_tolerance_ppm", "tolerance_source", "regulation_reference",
               "pct_of_tolerance"]

    grouped = {}
    for row in rows:
        d = dict(zip(columns, row))
        cat = d.pop("food_category")
        contam = d.pop("contaminant")
        key = (cat, contam)
        if key not in grouped:
            grouped[key] = {"food_category": cat, "contaminant": contam, "entries": []}
        grouped[key]["entries"].append(d)

    batch = db.batch()
    count = 0
    for (cat, contam), doc in grouped.items():
        doc_id = sanitize_doc_id(f"{cat}_{contam}")
        ref = db.collection("app_regulatory_limits").document(doc_id)
        batch.set(ref, doc)
        count += 1
        if count >= BATCH_LIMIT:
            batch.commit()
            batch = db.batch()
            count = 0

    if count > 0:
        batch.commit()
    logger.info("  Wrote %d app_regulatory_limits documents", len(grouped))


def precompute_international_comparison(db, conn: sqlite3.Connection):
    """Pre-compute app_international_comparison: MRL comparisons. All contaminants."""
    logger.info("Pre-computing app_international_comparison...")

    rows = conn.execute("""
        SELECT im.food_category, im.pesticide AS contaminant, im.country_region,
               im.mrl_ppm, im.mrl_ppb, im.regulatory_body, im.source_url,
               cs.detection_rate, cs.max_ppb AS measured_max_ppb,
               CASE
                   WHEN im.mrl_ppb > 0 AND cs.max_ppb IS NOT NULL
                   THEN ROUND(cs.max_ppb / im.mrl_ppb * 100.0, 1)
                   ELSE NULL
               END AS pct_of_mrl
        FROM international_mrls im
        LEFT JOIN category_summaries cs
            ON im.food_category = cs.food_category
            AND cs.contaminant = im.pesticide
        ORDER BY im.pesticide, im.food_category, im.mrl_ppb ASC
    """).fetchall()

    columns = ["food_category", "contaminant", "country_region", "mrl_ppm", "mrl_ppb",
               "regulatory_body", "source_url", "detection_rate",
               "measured_max_ppb", "pct_of_mrl"]

    grouped = {}
    for row in rows:
        d = dict(zip(columns, row))
        cat = d["food_category"]
        contam = d["contaminant"]
        key = (cat, contam)
        if key not in grouped:
            grouped[key] = {"food_category": cat, "contaminant": contam, "entries": []}
        grouped[key]["entries"].append({k: v for k, v in d.items() if k not in ("food_category", "contaminant")})

    batch = db.batch()
    count = 0
    for (cat, contam), doc in grouped.items():
        doc_id = sanitize_doc_id(f"{cat}_{contam}")
        ref = db.collection("app_international_comparison").document(doc_id)
        batch.set(ref, doc)
        count += 1
        if count >= BATCH_LIMIT:
            batch.commit()
            batch = db.batch()
            count = 0
        count += 1
        if count >= BATCH_LIMIT:
            batch.commit()
            batch = db.batch()
            count = 0

    if count > 0:
        batch.commit()
    logger.info("  Wrote %d app_international_comparison documents", len(grouped))


def precompute_water_overview(db, conn: sqlite3.Connection):
    """Pre-compute app_water_overview: aggregated water stats by state. All contaminants."""
    logger.info("Pre-computing app_water_overview...")

    rows = conn.execute("""
        SELECT wt.contaminant, wt.state, wt.water_type, wt.source_name, wt.report_label,
               wt.data_year, wt.samples_total, wt.samples_detected,
               wt.detection_rate, wt.avg_ppb, wt.max_ppb,
               tl.tolerance_ppb AS epa_mcl_ppb,
               CASE
                   WHEN tl.tolerance_ppb > 0 AND wt.max_ppb IS NOT NULL
                   THEN ROUND(wt.max_ppb / tl.tolerance_ppb * 100.0, 1)
                   ELSE NULL
               END AS pct_of_mcl
        FROM water_tests wt
        LEFT JOIN tolerance_limits tl
            ON tl.food_category = 'drinking_water' AND tl.source = 'EPA_MCL'
            AND tl.contaminant = wt.contaminant
        WHERE wt.is_aggregate = 1
        ORDER BY wt.contaminant, wt.state, wt.water_type, wt.data_year DESC
    """).fetchall()

    columns = ["contaminant", "state", "water_type", "source_name", "report_label",
               "data_year", "samples_total", "samples_detected",
               "detection_rate", "avg_ppb", "max_ppb", "epa_mcl_ppb", "pct_of_mcl"]

    grouped = {}
    for row in rows:
        d = dict(zip(columns, row))
        contam = d["contaminant"]
        state = d["state"] or "unknown"
        key = (contam, state)
        if key not in grouped:
            grouped[key] = {"contaminant": contam, "state": state, "entries": []}
        grouped[key]["entries"].append({k: v for k, v in d.items() if k not in ("contaminant", "state")})

    batch = db.batch()
    count = 0
    for (contam, state), doc in grouped.items():
        doc_id = sanitize_doc_id(f"{contam}_{state}")
        ref = db.collection("app_water_overview").document(doc_id)
        batch.set(ref, doc)
        count += 1
        if count >= BATCH_LIMIT:
            batch.commit()
            batch = db.batch()
            count = 0

    if count > 0:
        batch.commit()
    logger.info("  Wrote %d app_water_overview documents", len(grouped))


def main():
    parser = argparse.ArgumentParser(description="Migrate ResidueIQ SQLite to Firestore")
    parser.add_argument("--db", default=str(Path(__file__).parent / "residueiq.db"),
                        help="Path to SQLite database")
    parser.add_argument("--cred", default=str(Path(__file__).parent.parent / "firebase-service-account.json"),
                        help="Path to Firebase service account JSON")
    parser.add_argument("--skip-precompute", action="store_true",
                        help="Skip pre-computed app collections")
    parser.add_argument("--database", default="purityiq",
                        help="Firestore database ID (default: purityiq)")
    args = parser.parse_args()

    # Validate paths
    db_path = Path(args.db)
    cred_path = Path(args.cred)

    if not db_path.exists():
        logger.error("SQLite database not found: %s", db_path)
        sys.exit(1)
    if not cred_path.exists():
        logger.error("Firebase credentials not found: %s", cred_path)
        logger.error("Download from Firebase Console → Project Settings → Service Accounts")
        sys.exit(1)

    # Init Firebase
    logger.info("Initializing Firebase Admin SDK...")
    cred = credentials.Certificate(str(cred_path))
    firebase_admin.initialize_app(cred)
    db = firestore.client(database_id=args.database)
    logger.info("Connected to Firestore database: %s", args.database)

    # Open SQLite
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # ── Migrate raw tables ──
    total_written = 0
    for table in TABLES:
        logger.info("Migrating %s...", table)
        rows = read_table(conn, table)
        if not rows:
            logger.info("  No rows to migrate")
            continue

        converted = [convert_row(table, dict(r)) for r in rows]
        doc_id_func = lambda r, t=table: get_document_id(t, r)
        written = batch_write(db, table, converted, doc_id_func)
        total_written += written
        logger.info("  Migrated %d documents to %s", written, table)

    # ── Pre-compute app collections ──
    if not args.skip_precompute:
        precompute_food_overview(db, conn)
        precompute_product_lookup(db, conn)
        precompute_regulatory_limits(db, conn)
        precompute_international_comparison(db, conn)
        precompute_water_overview(db, conn)

    conn.close()

    logger.info("═══════════════════════════════════════════")
    logger.info("Migration complete! Total raw docs: %d", total_written)
    logger.info("Pre-computed collections: 5")
    logger.info("═══════════════════════════════════════════")


if __name__ == "__main__":
    main()
