"""
run_pipeline.py

Master pipeline runner. Execute this to ingest all sources.
Safe to re-run any time — idempotent via dedup_key.

Usage:
    python run_pipeline.py                  # run all sources
    python run_pipeline.py --source ewg     # run one source only
    python run_pipeline.py --validate       # validate DB after run
"""

import argparse
import logging
import sys
import time
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / f"pipeline_{time.strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("pipeline")

parser = argparse.ArgumentParser()
parser.add_argument("--source", help="Run only this source: ewg/florida/cfia/efsa/fda")
parser.add_argument("--validate", action="store_true")
args = parser.parse_args()


def run_all():
    from db.database import initialize
    from fetchers.ewg import EWGFetcher
    from fetchers.florida_hff import FloridaHFFetcher
    from fetchers.sources import CFIAFetcher, EFSAFetcher, FDAFetcher

    logger.info("Initializing database")
    initialize()

    sources = [
        ("cfia",    CFIAFetcher),
        ("efsa",    EFSAFetcher),
        ("fda",     FDAFetcher),
        ("ewg",     EWGFetcher),
        ("florida", FloridaHFFetcher),
    ]

    totals = {"inserted": 0, "skipped": 0, "failed": 0}
    errors = []

    for name, FetcherClass in sources:
        if args.source and args.source != name:
            continue
        logger.info("-" * 60)
        try:
            counts = FetcherClass().run()
            for k in totals:
                totals[k] += counts.get(k, 0)
        except Exception as e:
            logger.error("Source %s failed: %s", name, e, exc_info=True)
            errors.append((name, str(e)))

    logger.info("-" * 60)
    logger.info("PIPELINE COMPLETE: inserted=%d skipped=%d failed=%d",
                totals["inserted"], totals["skipped"], totals["failed"])
    if errors:
        logger.error("Sources with errors: %s", errors)
    return len(errors) == 0


def validate():
    import sqlite3
    from db.database import DB_PATH
    logger.info("Running validation checks...")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    issues = []

    bad_rates = conn.execute("""
        SELECT id, source_name, food_category, detection_rate
        FROM glyphosate_measurements
        WHERE detection_rate IS NOT NULL AND (detection_rate < 0 OR detection_rate > 1)
    """).fetchall()
    issues += [f"Invalid detection_rate {r['detection_rate']} in row {r['id']}" for r in bad_rates]

    neg_ppb = conn.execute("""
        SELECT id FROM glyphosate_measurements
        WHERE (measured_ppb IS NOT NULL AND measured_ppb < 0)
           OR (avg_ppb IS NOT NULL AND avg_ppb < 0)
    """).fetchall()
    issues += [f"Negative ppb in row {r['id']}" for r in neg_ppb]

    missing = conn.execute("""
        SELECT id, source_name FROM glyphosate_measurements
        WHERE food_category IS NULL OR food_category = ''
           OR source_name IS NULL OR published_date IS NULL OR confidence IS NULL
    """).fetchall()
    issues += [f"Missing required fields row {r['id']} ({r['source_name']})" for r in missing]

    total = conn.execute("SELECT COUNT(*) FROM glyphosate_measurements").fetchone()[0]
    t1    = conn.execute("SELECT COUNT(*) FROM glyphosate_measurements WHERE tier=1").fetchone()[0]
    t2    = conn.execute("SELECT COUNT(*) FROM glyphosate_measurements WHERE tier=2").fetchone()[0]
    cats  = conn.execute("SELECT COUNT(DISTINCT food_category) FROM glyphosate_measurements WHERE tier=2").fetchone()[0]

    logger.info("DB summary: total=%d tier1=%d tier2=%d categories=%d", total, t1, t2, cats)

    if issues:
        logger.error("VALIDATION FAILED: %d issues", len(issues))
        for i in issues:
            logger.error("  - %s", i)
        return False
    logger.info("All validation checks passed.")
    return True


if __name__ == "__main__":
    ok = run_all()
    valid = validate()
    sys.exit(0 if (ok and valid) else 1)
