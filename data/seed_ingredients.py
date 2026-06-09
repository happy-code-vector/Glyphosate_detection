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
    # Priority 1 — Dirty Dozen
    {
        "commodity_slug": "strawberry",
        "display_name": "Strawberry",
        "dirty_dozen": True,
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
        "ingredient_aliases": [
            "spinach", "organic spinach", "baby spinach", "spinach powder",
            "spinach puree", "dehydrated spinach", "spinach extract",
        ],
    },
    {
        "commodity_slug": "kale",
        "display_name": "Kale",
        "dirty_dozen": True,
        "ingredient_aliases": [
            "kale", "organic kale", "kale powder", "dehydrated kale",
            "kale extract", "collard greens", "mixed greens",
        ],
    },
    {
        "commodity_slug": "peach",
        "display_name": "Peach",
        "dirty_dozen": True,
        "ingredient_aliases": [
            "peaches", "organic peaches", "peach puree", "peach juice",
            "peach concentrate", "dried peaches", "freeze-dried peaches",
        ],
    },
    {
        "commodity_slug": "celery",
        "display_name": "Celery",
        "dirty_dozen": True,
        "ingredient_aliases": [
            "celery", "celery seed", "celery salt", "celery extract",
            "celery juice", "celery powder",
        ],
    },
    {
        "commodity_slug": "carrot",
        "display_name": "Carrot",
        "dirty_dozen": True,
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
        "ingredient_aliases": [
            "lettuce", "romaine lettuce", "iceberg lettuce",
            "mixed greens", "salad greens", "butter lettuce",
        ],
    },
    {
        "commodity_slug": "cucumber",
        "display_name": "Cucumber",
        "dirty_dozen": True,
        "ingredient_aliases": [
            "cucumbers", "pickles", "pickle juice", "gherkin",
        ],
    },
    {
        "commodity_slug": "orange",
        "display_name": "Orange",
        "dirty_dozen": True,
        "ingredient_aliases": [
            "oranges", "orange juice", "orange concentrate", "orange extract",
            "orange peel", "orange zest", "mandarin", "tangerine", "clementine",
            "orange pulp", "frozen orange juice",
        ],
    },
    {
        "commodity_slug": "lemon",
        "display_name": "Lemon",
        "dirty_dozen": True,
        "ingredient_aliases": [
            "lemon", "lemon juice", "lemon extract", "lemon peel",
            "lemon zest", "lemon pulp", "lemon concentrate",
        ],
    },
    {
        "commodity_slug": "milk",
        "display_name": "Milk",
        "dirty_dozen": True,
        "ingredient_aliases": [
            "milk", "whole milk", "skim milk", "low-fat milk", "nonfat milk",
            "milk solids", "dried milk", "nonfat dry milk", "lactose",
            "whey", "whey protein", "buttermilk", "cream",
        ],
    },
    {
        "commodity_slug": "egg",
        "display_name": "Egg",
        "dirty_dozen": True,
        "ingredient_aliases": [
            "eggs", "whole eggs", "egg whites", "egg yolks", "dried eggs",
            "egg powder", "egg solids", "egg albumen",
        ],
    },
    # Priority 2 — High-volume packaged food ingredients
    {
        "commodity_slug": "wheat",
        "display_name": "Wheat",
        "ingredient_aliases": [
            "wheat", "wheat flour", "whole wheat", "wheat starch",
            "wheat gluten", "wheat bran", "wheat germ", "semolina",
            "durum wheat", "enriched flour", "bleached flour",
        ],
    },
    {
        "commodity_slug": "corn",
        "display_name": "Corn",
        "ingredient_aliases": [
            "corn", "corn meal", "corn starch", "corn syrup",
            "high fructose corn syrup", "corn flour", "corn oil",
            "corn gluten", "popcorn", "sweetcorn", "maize",
        ],
    },
    {
        "commodity_slug": "soybean",
        "display_name": "Soybean",
        "ingredient_aliases": [
            "soy", "soybean", "soybeans", "soy protein", "soy lecithin",
            "soy flour", "soy oil", "soybean oil", "tofu", "tempeh",
            "soy milk", "edamame", "soy sauce",
        ],
    },
    {
        "commodity_slug": "apple",
        "display_name": "Apple",
        "ingredient_aliases": [
            "apples", "apple juice", "apple puree", "apple concentrate",
            "apple cider", "dried apples", "apple sauce", "apple extract",
        ],
    },
    {
        "commodity_slug": "grape",
        "display_name": "Grape",
        "ingredient_aliases": [
            "grapes", "grape juice", "raisins", "grape concentrate",
            "grape seed oil", "grape extract", "wine", "grape must",
        ],
    },
    {
        "commodity_slug": "rice",
        "display_name": "Rice",
        "ingredient_aliases": [
            "rice", "white rice", "brown rice", "rice flour",
            "rice starch", "rice syrup", "rice bran", "rice milk",
            "jasmine rice", "basmati rice", "wild rice",
        ],
    },
    {
        "commodity_slug": "potato",
        "display_name": "Potato",
        "ingredient_aliases": [
            "potatoes", "potato starch", "potato flour", "dehydrated potatoes",
            "potato flakes", "potato chips", "french fries",
        ],
    },
    {
        "commodity_slug": "tomato",
        "display_name": "Tomato",
        "ingredient_aliases": [
            "tomatoes", "tomato paste", "tomato puree", "tomato sauce",
            "tomato juice", "sun-dried tomatoes", "tomato powder",
            "ketchup", "tomato concentrate",
        ],
    },
    {
        "commodity_slug": "banana",
        "display_name": "Banana",
        "ingredient_aliases": [
            "bananas", "banana puree", "banana powder", "dried bananas",
            "freeze-dried bananas", "plantain",
        ],
    },
    {
        "commodity_slug": "blueberry",
        "display_name": "Blueberry",
        "ingredient_aliases": [
            "blueberries", "organic blueberries", "freeze-dried blueberries",
            "blueberry puree", "blueberry juice", "blueberry concentrate",
            "dried blueberries", "blueberry extract",
        ],
    },
    {
        "commodity_slug": "oat",
        "display_name": "Oat",
        "ingredient_aliases": [
            "oats", "oat flour", "oat bran", "oat fiber", "oat milk",
            "rolled oats", "steel-cut oats", "instant oats",
            "whole grain oats", "oat groats",
        ],
    },
    {
        "commodity_slug": "barley",
        "display_name": "Barley",
        "ingredient_aliases": [
            "barley", "barley malt", "barley flour", "pearl barley",
            "barley extract",
        ],
    },
    {
        "commodity_slug": "almond",
        "display_name": "Almond",
        "ingredient_aliases": [
            "almonds", "almond flour", "almond milk", "almond butter",
            "almond oil", "almond extract", "sliced almonds",
        ],
    },
    {
        "commodity_slug": "peanut",
        "display_name": "Peanut",
        "ingredient_aliases": [
            "peanuts", "peanut butter", "peanut oil", "peanut flour",
            "peanut protein", "groundnuts",
        ],
    },
    {
        "commodity_slug": "cherry",
        "display_name": "Cherry",
        "ingredient_aliases": [
            "cherries", "cherry juice", "dried cherries", "maraschino cherries",
            "cherry puree", "tart cherries",
        ],
    },
    {
        "commodity_slug": "pear",
        "display_name": "Pear",
        "ingredient_aliases": [
            "pears", "pear juice", "pear puree", "pear concentrate",
            "dried pears",
        ],
    },
    {
        "commodity_slug": "bean",
        "display_name": "Bean",
        "ingredient_aliases": [
            "beans", "kidney beans", "black beans", "pinto beans",
            "navy beans", "lima beans", "green beans", "white beans",
            "bean sprouts", "fava beans",
        ],
    },
    {
        "commodity_slug": "broccoli",
        "display_name": "Broccoli",
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
        })
    logger.info("Prepared %d commodity records", len(rows))
    if dry_run:
        for row in rows:
            aliases = json.loads(row["ingredient_aliases"])
            logger.info("  [DRY RUN] %s — %d aliases", row["commodity_slug"], len(aliases))
        return
    result = insert_commodities(rows)
    logger.info("Commodities: inserted=%d, skipped=%d, failed=%d",
                result["inserted"], result["skipped"], result["failed"])


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

    logger.info("Done!")


if __name__ == "__main__":
    main()
