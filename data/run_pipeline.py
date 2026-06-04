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
parser.add_argument("--source", help="Run only this source: ewg/florida/cfia/efsa/fda/usda_pdp/uk_fsa/ca_dpr/germany_bvl/epa_tolerances/australia_fsnz/codex_mrls/japan_brazil_mrls/academic_papers/detox_project/cdc_nhanes/clean_label_project/consumer_reports/detox_certifications/epa_full_tolerances/usda_fas_mrls/water_quality_glyphosate/water_quality_lead/water_quality_atrazine")
parser.add_argument("--validate", action="store_true")
args = parser.parse_args()


def run_all():
    from db.database import initialize
    from fetchers.ewg import EWGFetcher
    from fetchers.florida_hff import FloridaHFFetcher
    from fetchers.sources import CFIAFetcher, EFSAFetcher, FDAFetcher
    from fetchers.usda_pdp import USDA_PDPFetcher
    from fetchers.uk_fsa import UKFSAFetcher
    from fetchers.ca_dpr import CADPRFetcher
    from fetchers.germany_bvl import GermanyBVLFetcher
    from fetchers.epa_tolerances import EPATolerancesFetcher
    from fetchers.australia_fsnz import AustraliaFSANZFetcher
    from fetchers.codex_mrls import CodexMRLsFetcher
    from fetchers.japan_brazil_mrls import JapanBrazilMRLFetcher
    from fetchers.academic_papers import AcademicPapersFetcher
    from fetchers.detox_project import DetoxProjectFetcher
    from fetchers.cdc_nhanes import CDC_NHANESFetcher
    from fetchers.clean_label_project import CleanLabelProjectFetcher
    from fetchers.consumer_reports import ConsumerReportsFetcher
    from fetchers.detox_certifications import DetoxCertificationsFetcher
    from fetchers.epa_full_tolerances import EPAFullTolerancesFetcher
    from fetchers.usda_fas_mrls import USDAFASMRLFetcher
    from fetchers.water_quality import WaterQualityFetcher
    from fetchers.moms_across_america import MomsAcrossAmericaFetcher
    from fetchers.food_democracy_now import FoodDemocracyNowFetcher
    from fetchers.soil_association import SoilAssociationFetcher
    from fetchers.hri_labs import HRILabsFetcher
    from fetchers.usda_organic import USDAOrganicFetcher

    logger.info("Initializing database")
    initialize()

    sources = [
        ("cfia",            CFIAFetcher),
        ("efsa",            EFSAFetcher),
        ("fda",             FDAFetcher),
        ("ewg",             EWGFetcher),
        ("florida",         FloridaHFFetcher),
        ("usda_pdp",        USDA_PDPFetcher),
        ("uk_fsa",          UKFSAFetcher),
        ("ca_dpr",          CADPRFetcher),
        ("germany_bvl",     GermanyBVLFetcher),
        ("epa_tolerances",  EPATolerancesFetcher),
        ("australia_fsnz",  AustraliaFSANZFetcher),
        ("codex_mrls",      CodexMRLsFetcher),
        ("japan_brazil_mrls", JapanBrazilMRLFetcher),
        ("academic_papers", AcademicPapersFetcher),
        ("detox_project",   DetoxProjectFetcher),
        ("cdc_nhanes",      CDC_NHANESFetcher),
        ("clean_label_project", CleanLabelProjectFetcher),
        ("consumer_reports",    ConsumerReportsFetcher),
        ("detox_certifications", DetoxCertificationsFetcher),
        ("epa_full_tolerances", EPAFullTolerancesFetcher),
        ("usda_fas_mrls",       USDAFASMRLFetcher),
        ("moms_across_america",  MomsAcrossAmericaFetcher),
        ("food_democracy_now",   FoodDemocracyNowFetcher),
        ("soil_association",     SoilAssociationFetcher),
        ("usda_organic",         USDAOrganicFetcher),
        ("hri_labs",             HRILabsFetcher),
        ("water_quality_glyphosate", lambda: WaterQualityFetcher("glyphosate")),
        ("water_quality_lead",      lambda: WaterQualityFetcher("lead")),
        ("water_quality_atrazine",  lambda: WaterQualityFetcher("atrazine")),
    ]

    totals = {"inserted": 0, "skipped": 0, "failed": 0}
    errors = []

    for name, FetcherFactory in sources:
        if args.source and args.source != name:
            # Allow "water_quality" to match all three water_quality_* sources
            if args.source == "water_quality" and name.startswith("water_quality_"):
                pass
            else:
                continue
        logger.info("-" * 60)
        try:
            fetcher = FetcherFactory()
            counts = fetcher.run()
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

    # Tier 2: check detection rates in category_summaries
    bad_rates = conn.execute("""
        SELECT id, source_name, food_category, detection_rate
        FROM category_summaries
        WHERE detection_rate < 0 OR detection_rate > 1
    """).fetchall()
    issues += [f"Invalid detection_rate {r['detection_rate']} in row {r['id']}" for r in bad_rates]

    # Check negative ppb in both tables
    neg_ppb = conn.execute("""
        SELECT id FROM product_tests
        WHERE measured_ppb IS NOT NULL AND measured_ppb < 0
    """).fetchall()
    neg_ppb += conn.execute("""
        SELECT id FROM category_summaries
        WHERE (avg_ppb IS NOT NULL AND avg_ppb < 0)
           OR (max_ppb IS NOT NULL AND max_ppb < 0)
    """).fetchall()
    issues += [f"Negative ppb in row {r['id']}" for r in neg_ppb]

    # Check missing required fields in both tables
    missing = conn.execute("""
        SELECT id, source_name FROM product_tests
        WHERE food_category IS NULL OR food_category = ''
           OR product_name IS NULL OR source_name IS NULL
           OR published_date IS NULL OR confidence IS NULL
    """).fetchall()
    missing += conn.execute("""
        SELECT id, source_name FROM category_summaries
        WHERE food_category IS NULL OR food_category = ''
           OR source_name IS NULL OR published_date IS NULL OR confidence IS NULL
    """).fetchall()
    issues += [f"Missing required fields row {r['id']} ({r['source_name']})" for r in missing]

    t1    = conn.execute("SELECT COUNT(*) FROM product_tests").fetchone()[0]
    t2    = conn.execute("SELECT COUNT(*) FROM category_summaries").fetchone()[0]
    cats  = conn.execute("SELECT COUNT(DISTINCT food_category) FROM category_summaries").fetchone()[0]

    logger.info("DB summary: product_tests=%d category_summaries=%d categories=%d", t1, t2, cats)

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
