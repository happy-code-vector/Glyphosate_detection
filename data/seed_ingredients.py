"""
seed_ingredients.py

One-time seed script for regulatory data tables:
- ingredients (master reference for flagged ingredients)
- regulatory_flags (jurisdiction-specific flag records)
- commodities (USDA PDP commodity data + ingredient aliases)

Idempotent — safe to re-run. Uses INSERT OR IGNORE.

Usage:
    python seed_ingredients.py              # seed all tables
    python seed_ingredients.py --dry-run    # print counts without inserting
"""

import argparse
import json
import logging
import sys

from db.database import (
    initialize,
    get_connection,
    insert_ingredients,
    insert_regulatory_flags,
    insert_commodities,
    build_dedup_key,
)
from contaminants import CONTAMINANTS, get_ingredients, get_regulatory_flags

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed")

# ═════════════════════════════════════════════
# COMMODITY SEED DATA
# From PurityIQ Handoff v3 Section 6
# ═════════════════════════════════════════════

COMMODITY_SEEDS = [
    # Consumption tiers:
    #   daily     — staple foods eaten every day (wheat, rice, milk, eggs, corn, oats)
    #   weekly    — common foods eaten several times/week (fruits, vegetables, potatoes)
    #   occasional — foods eaten a few times/month (berries, nuts, specific vegetables)
    #   rare      — specialty items eaten infrequently (cherries, pears, barley)

    # Priority 1 — Dirty Dozen
    {
        "commodity_slug": "strawberry",
        "display_name": "Strawberry",
        "dirty_dozen": True,
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "strawberries", "organic strawberries", "freeze-dried strawberries",
            "strawberry puree", "strawberry juice", "strawberry extract",
            "strawberry concentrate", "strawberry powder", "dried strawberries",
        ],
    },
    {
        "commodity_slug": "spinach",
        "display_name": "Spinach",
        "dirty_dozen": True,
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "spinach", "organic spinach", "baby spinach", "spinach powder",
            "spinach puree", "dehydrated spinach", "spinach extract",
        ],
    },
    {
        "commodity_slug": "kale",
        "display_name": "Kale",
        "dirty_dozen": True,
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "kale", "organic kale", "kale powder", "dehydrated kale",
            "kale extract", "collard greens", "mixed greens",
        ],
    },
    {
        "commodity_slug": "peach",
        "display_name": "Peach",
        "dirty_dozen": True,
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "peaches", "organic peaches", "peach puree", "peach juice",
            "peach concentrate", "dried peaches", "freeze-dried peaches",
        ],
    },
    {
        "commodity_slug": "celery",
        "display_name": "Celery",
        "dirty_dozen": True,
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "celery", "celery seed", "celery salt", "celery extract",
            "celery juice", "celery powder",
        ],
    },
    {
        "commodity_slug": "carrot",
        "display_name": "Carrot",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "carrots", "organic carrots", "baby carrots", "carrot puree",
            "carrot juice", "dehydrated carrots", "carrot powder",
            "carrot extract",
        ],
    },
    {
        "commodity_slug": "lettuce",
        "display_name": "Lettuce",
        "dirty_dozen": True,
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "lettuce", "romaine lettuce", "iceberg lettuce",
            "mixed greens", "salad greens", "butter lettuce",
        ],
    },
    {
        "commodity_slug": "cucumber",
        "display_name": "Cucumber",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "cucumbers", "pickles", "pickle juice", "gherkin",
        ],
    },
    {
        "commodity_slug": "orange",
        "display_name": "Orange",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "oranges", "orange juice", "orange concentrate", "orange extract",
            "orange peel", "orange zest", "mandarin", "tangerine", "clementine",
            "orange pulp", "frozen orange juice",
        ],
    },
    {
        "commodity_slug": "lemon",
        "display_name": "Lemon",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "lemon", "lemon juice", "lemon extract", "lemon peel",
            "lemon zest", "lemon pulp", "lemon concentrate",
        ],
    },
    {
        "commodity_slug": "dairy",
        "display_name": "Dairy",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "milk", "whole milk", "skim milk", "low-fat milk", "nonfat milk",
            "milk solids", "dried milk", "nonfat dry milk", "lactose",
            "whey", "whey protein", "buttermilk", "cream", "cheese",
            "yogurt", "joghurt", "butter", "ghee", "kefir",
        ],
    },
    {
        "commodity_slug": "egg",
        "display_name": "Egg",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "eggs", "whole eggs", "egg whites", "egg yolks", "dried eggs",
            "egg powder", "egg solids", "egg albumen",
        ],
    },
    # Priority 2 — High-volume packaged food ingredients
    {
        "commodity_slug": "wheat",
        "display_name": "Wheat",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "wheat", "wheat flour", "whole wheat", "wheat starch",
            "wheat gluten", "wheat bran", "wheat germ", "semolina",
            "durum wheat", "enriched flour", "bleached flour",
        ],
    },
    {
        "commodity_slug": "corn",
        "display_name": "Corn",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "corn", "corn meal", "corn starch", "corn syrup",
            "high fructose corn syrup", "corn flour", "corn oil",
            "corn gluten", "popcorn", "sweetcorn", "maize",
        ],
    },
    {
        "commodity_slug": "soybean",
        "display_name": "Soybean",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "soy", "soybean", "soybeans", "soy protein", "soy lecithin",
            "soy flour", "soy oil", "soybean oil", "tofu", "tempeh",
            "soy milk", "edamame", "soy sauce",
        ],
    },
    {
        "commodity_slug": "apple",
        "display_name": "Apple",
        "dirty_dozen": True,
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "apples", "apple juice", "apple puree", "apple concentrate",
            "apple cider", "dried apples", "apple sauce", "apple extract",
        ],
    },
    {
        "commodity_slug": "grape",
        "display_name": "Grape",
        "dirty_dozen": True,
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "grapes", "grape juice", "raisins", "grape concentrate",
            "grape seed oil", "grape extract", "wine", "grape must",
        ],
    },
    {
        "commodity_slug": "rice",
        "display_name": "Rice",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "rice", "white rice", "brown rice", "rice flour",
            "rice starch", "rice syrup", "rice bran", "rice milk",
            "jasmine rice", "basmati rice", "wild rice",
        ],
    },
    {
        "commodity_slug": "potato",
        "display_name": "Potato",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "potatoes", "potato starch", "potato flour", "dehydrated potatoes",
            "potato flakes", "potato chips", "french fries",
        ],
    },
    {
        "commodity_slug": "tomato",
        "display_name": "Tomato",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "tomatoes", "tomato paste", "tomato puree", "tomato sauce",
            "tomato juice", "sun-dried tomatoes", "tomato powder",
            "ketchup", "tomato concentrate",
        ],
    },
    {
        "commodity_slug": "banana",
        "display_name": "Banana",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "bananas", "banana puree", "banana powder", "dried bananas",
            "freeze-dried bananas", "plantain",
        ],
    },
    {
        "commodity_slug": "blueberry",
        "display_name": "Blueberry",
        "dirty_dozen": True,
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "blueberries", "organic blueberries", "freeze-dried blueberries",
            "blueberry puree", "blueberry juice", "blueberry concentrate",
            "dried blueberries", "blueberry extract",
        ],
    },
    {
        "commodity_slug": "oat",
        "display_name": "Oat",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "oats", "oat flour", "oat bran", "oat fiber", "oat milk",
            "rolled oats", "steel-cut oats", "instant oats",
            "whole grain oats", "oat groats",
        ],
    },
    {
        "commodity_slug": "barley",
        "display_name": "Barley",
        "consumption_tier": "occasional",
        "ingredient_aliases": [
            "barley", "barley malt", "barley flour", "pearl barley",
            "barley extract",
        ],
    },
    {
        "commodity_slug": "almond",
        "display_name": "Almond",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "almonds", "almond flour", "almond milk", "almond butter",
            "almond oil", "almond extract", "sliced almonds",
        ],
    },
    {
        "commodity_slug": "peanut",
        "display_name": "Peanut",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "peanuts", "peanut butter", "peanut oil", "peanut flour",
            "peanut protein", "groundnuts",
        ],
    },
    {
        "commodity_slug": "cherry",
        "display_name": "Cherry",
        "dirty_dozen": True,
        "consumption_tier": "occasional",
        "ingredient_aliases": [
            "cherries", "cherry juice", "dried cherries", "maraschino cherries",
            "cherry puree", "tart cherries",
        ],
    },
    {
        "commodity_slug": "pear",
        "display_name": "Pear",
        "dirty_dozen": True,
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "pears", "pear juice", "pear puree", "pear concentrate",
            "dried pears",
        ],
    },
    {
        "commodity_slug": "bean",
        "display_name": "Bean",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "beans", "kidney beans", "black beans", "pinto beans",
            "navy beans", "lima beans", "green beans", "white beans",
            "bean sprouts", "fava beans",
        ],
    },
    {
        "commodity_slug": "broccoli",
        "display_name": "Broccoli",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "broccoli", "broccoli sprouts", "broccoli powder",
            "dehydrated broccoli",
        ],
    },
]


def seed_ingredients_table(dry_run=False):
    """Seed the ingredients table from contaminants.py."""
    ingredients = get_ingredients()
    logger.info("Prepared %d ingredient records", len(ingredients))
    if dry_run:
        for ing in ingredients:
            logger.info("  [DRY RUN] %s — %s", ing["ingredient_id"], ing["display_name"])
        return
    result = insert_ingredients(ingredients)
    logger.info("Ingredients: inserted=%d, skipped=%d, failed=%d",
                result["inserted"], result["skipped"], result["failed"])


def seed_regulatory_flags_table(dry_run=False):
    """Seed the regulatory_flags table from contaminants.py."""
    flags = get_regulatory_flags()
    logger.info("Prepared %d regulatory flag records", len(flags))
    if dry_run:
        for flag in flags:
            logger.info("  [DRY RUN] %s / %s — %s",
                        flag["ingredient_id"], flag["jurisdiction"], flag["flag_type"])
        return
    result = insert_regulatory_flags(flags)
    logger.info("Regulatory flags: inserted=%d, skipped=%d, failed=%d",
                result["inserted"], result["skipped"], result["failed"])


def seed_commodities_table(dry_run=False):
    """Seed the commodities table from the hardcoded seed list."""
    rows = []
    for commodity in COMMODITY_SEEDS:
        rows.append({
            "commodity_slug": commodity["commodity_slug"],
            "display_name": commodity["display_name"],
            "ingredient_aliases": json.dumps(commodity.get("ingredient_aliases", [])),
            "dirty_dozen": 1 if commodity.get("dirty_dozen") else 0,
            "consumption_tier": commodity.get("consumption_tier", "occasional"),
        })
    logger.info("Prepared %d commodity records", len(rows))
    if dry_run:
        for row in rows:
            aliases = json.loads(row["ingredient_aliases"])
            logger.info("  [DRY RUN] %s — %d aliases, tier=%s",
                        row["commodity_slug"], len(aliases), row["consumption_tier"])
        return
    result = insert_commodities(rows)
    logger.info("Commodities: inserted=%d, skipped=%d, failed=%d",
                result["inserted"], result["skipped"], result["failed"])


def seed_fda_action_levels(dry_run=False):
    """
    Seed FDA heavy metal action levels into tolerance_limits table.
    These are regulatory reference values from FDA's 'Closer to Zero' program
    and EPA drinking water standards.
    """
    action_levels = []

    for contaminant_key, config in CONTAMINANTS.items():
        # Seed FDA action levels (baby food, juice)
        for category, level in config.get("fda_action_levels", {}).items():
            ppb = level["ppb"]
            action_levels.append({
                "food_category": f"baby_food_{category}" if category == "baby_food" else category,
                "raw_commodity": category,
                "tolerance_ppm": ppb / 1000.0,
                "tolerance_ppb": ppb,
                "contaminant": contaminant_key,
                "source": "FDA",
                "regulation_reference": level["reference"],
                "dedup_key": build_dedup_key(contaminant_key, "FDA", category),
            })

        # Seed drinking water standards
        for std in config.get("water_standards", []):
            action_levels.append({
                "food_category": "drinking_water",
                "raw_commodity": "drinking_water",
                "tolerance_ppm": std["tolerance_ppm"],
                "tolerance_ppb": std["tolerance_ppb"],
                "contaminant": contaminant_key,
                "source": std["source"],
                "regulation_reference": std["regulation_reference"],
                "dedup_key": build_dedup_key(contaminant_key, std["source"], "drinking_water"),
            })

    logger.info("Prepared %d FDA/water standard records", len(action_levels))
    if dry_run:
        for row in action_levels:
            logger.info("  [DRY RUN] %s / %s — %s ppb (%s)",
                        row["contaminant"], row["food_category"],
                        row["tolerance_ppb"], row["source"])
        return

    inserted = skipped = failed = 0
    with get_connection() as conn:
        for row in action_levels:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO tolerance_limits (
                        food_category, raw_commodity, tolerance_ppm, tolerance_ppb,
                        contaminant, source, regulation_reference, dedup_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row["food_category"], row["raw_commodity"],
                    row["tolerance_ppm"], row["tolerance_ppb"],
                    row["contaminant"], row["source"],
                    row["regulation_reference"], row["dedup_key"],
                ))
                if conn.execute("SELECT changes()").fetchone()[0]:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.error("Failed to insert %s: %s", row["dedup_key"], e)
                failed += 1

    logger.info("FDA action levels: inserted=%d, skipped=%d, failed=%d",
                inserted, skipped, failed)


def main():
    parser = argparse.ArgumentParser(description="Seed regulatory data tables")
    parser.add_argument("--dry-run", action="store_true", help="Print without inserting")
    args = parser.parse_args()

    logger.info("Initializing database")
    initialize()

    logger.info("=== Seeding ingredients table ===")
    seed_ingredients_table(dry_run=args.dry_run)

    logger.info("=== Seeding regulatory_flags table ===")
    seed_regulatory_flags_table(dry_run=args.dry_run)

    logger.info("=== Seeding commodities table ===")
    seed_commodities_table(dry_run=args.dry_run)

    logger.info("=== Seeding FDA action levels & water standards ===")
    seed_fda_action_levels(dry_run=args.dry_run)

    logger.info("Done!")


if __name__ == "__main__":
    main()
