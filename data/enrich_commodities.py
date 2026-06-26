"""
enrich_commodities.py

Post-pipeline script to populate the commodities.residues field
from USDA PDP data in category_summaries.

Run AFTER the pipeline completes:
    python enrich_commodities.py

Maps commodity slugs to PDP food categories and builds per-pesticide
residue arrays from the latest year of data.
"""

import json
import logging
import sqlite3
from datetime import datetime

from db.database import get_connection, DB_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("enrich")

# Commodity slug → PDP food_category mapping
# Now maps 1:1 since PDP fetcher uses specific canonical keys (not broad groups).
COMMODITY_TO_PDP = {
    "strawberry": "strawberry",
    "spinach": "spinach",
    "kale": "kale",
    "peach": "peach",
    "celery": "celery",
    "carrot": "carrot",
    "lettuce": "lettuce",
    "cucumber": "cucumber",
    "orange": "orange",
    "lemon": "lemon",
    "milk": None,  # No PDP data for dairy
    "egg": None,   # No PDP data for eggs
    "wheat": "wheat",
    "corn": "corn",
    "soybean": "soybeans",
    "apple": "apple",
    "grape": "grape",
    "rice": "rice",
    "potato": "potato",
    "tomato": "tomato",
    "banana": "banana",
    "blueberry": "blueberry",
    "oat": "oats",
    "barley": "barley",
    "almond": None,  # No PDP data
    "peanut": None,  # No PDP data
    "cherry": "cherry",
    "pear": "pear",
    "bean": "beans",
    "broccoli": "broccoli",
}

# PDP commodity codes — no longer needed for filtering since categories are now specific,
# but kept for reference and pdp_commodity_code field population.
COMMODITY_PDP_CODES = {
    "strawberry": ["ST"],
    "wheat": ["WH"],
    "corn": ["CO"],
    "soybean": ["SY"],
    "rice": ["RC"],
    "oat": ["OA"],
    "barley": ["BA"],
    "bean": ["BN"],
    "blueberry": ["BB", "BZ"],
    "grape": ["GP"],
}


def _resolve_slug_key(mapping: dict, slug: str):
    """Look up a commodity slug in a PDP mapping, tolerating singular/plural drift.

    Seed commodity slugs are plural ('soybeans', 'oats', 'beans', 'lentils',
    'chickpeas') while COMMODITY_TO_PDP / COMMODITY_PDP_CODES use singular keys
    ('soybean', 'oat', 'bean'). Try the slug as-is first so explicit ``None``
    mappings are preserved, then singular/plural variants.
    """
    if slug in mapping:
        return mapping[slug]
    variants = [slug.removesuffix("es"), slug.removesuffix("s"),
                slug + "s", slug + "es"]
    if slug.endswith("ies"):
        variants.append(slug[:-3] + "y")
    for v in variants:
        if v != slug and v in mapping:
            return mapping[v]
    return None


def enrich_commodities():
    """Populate commodities.residues from category_summaries PDP data."""
    with get_connection() as conn:
        # Global max PDP year across all commodities — the "current cycle".
        # pdp_covered (Addendum B 2.2) is True only for commodities still tested
        # in this current cycle; grains USDA dropped (oats/wheat) fall behind it.
        max_pdp_year = conn.execute(
            "SELECT MAX(data_year) FROM category_summaries WHERE source_name = 'USDA_PDP'"
        ).fetchone()[0]

        # Get all commodities
        commodities = conn.execute(
            "SELECT commodity_slug, display_name FROM commodities"
        ).fetchall()

        enriched = 0
        skipped = 0

        for slug, display_name in commodities:
            pdp_category = _resolve_slug_key(COMMODITY_TO_PDP, slug)
            if not pdp_category:
                logger.info("  %s: no PDP mapping — skipping", slug)
                skipped += 1
                continue

            # Get the latest year of PDP data for this category
            latest_year = conn.execute(
                "SELECT MAX(data_year) FROM category_summaries "
                "WHERE source_name = 'USDA_PDP' AND food_category = ?",
                (pdp_category,)
            ).fetchone()[0]

            if not latest_year:
                logger.info("  %s: no PDP data for '%s' — skipping", slug, pdp_category)
                skipped += 1
                continue

            # Get all pesticide data for this category in the latest year
            # If we have specific PDP codes, filter by those
            pdp_codes = _resolve_slug_key(COMMODITY_PDP_CODES, slug)

            rows = conn.execute(
                "SELECT contaminant, detection_rate, avg_ppb, max_ppb, "
                "samples_total, samples_detected, data_year "
                "FROM category_summaries "
                "WHERE source_name = 'USDA_PDP' AND food_category = ? "
                "AND data_year = ? "
                "ORDER BY detection_rate DESC",
                (pdp_category, latest_year)
            ).fetchall()

            if not rows:
                logger.info("  %s: no PDP rows for '%s' year %d — skipping",
                           slug, pdp_category, latest_year)
                skipped += 1
                continue

            # Build residues array
            residues = []
            for row in rows:
                contaminant = row[0]
                # Skip unknown pesticides
                if contaminant.startswith("pesticide_unknown"):
                    continue
                residues.append({
                    "pesticide": contaminant,
                    "detection_rate": row[1],
                    "avg_ppb": row[2],
                    "max_ppb": row[3],
                    "samples_total": row[4],
                    "samples_detected": row[5],
                    "data_year": row[6],
                })

            # Get PDP commodity code
            pdp_code = COMMODITY_PDP_CODES.get(slug, [None])[0] if pdp_codes else None

            # Covered iff this commodity's latest PDP year is the current cycle.
            pdp_covered = 1 if (max_pdp_year and latest_year == max_pdp_year) else 0

            # Update the commodity row
            conn.execute(
                "UPDATE commodities SET "
                "residues = ?, "
                "pdp_commodity_code = ?, "
                "pdp_year_latest = ?, "
                "pdp_covered = ?, "
                "last_pdp_update = ? "
                "WHERE commodity_slug = ?",
                (
                    json.dumps(residues),
                    pdp_code,
                    latest_year,
                    pdp_covered,
                    datetime.now().isoformat(),
                    slug,
                )
            )

            logger.info("  %s: %d residues from '%s' year %d (pdp_covered=%d)",
                       slug, len(residues), pdp_category, latest_year, pdp_covered)
            enriched += 1

        conn.commit()
        logger.info("Enriched %d commodities, skipped %d", enriched, skipped)


if __name__ == "__main__":
    logger.info("Enriching commodities with PDP residue data...")
    enrich_commodities()
    logger.info("Done!")
