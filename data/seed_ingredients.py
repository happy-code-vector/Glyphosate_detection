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
        "commodity_slug": "soybeans",
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
        "commodity_slug": "oats",
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
        "commodity_slug": "beans",
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
    # ── Additional high-volume categories ──────────────────────────────
    {
        "commodity_slug": "chicken",
        "display_name": "Chicken",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "chicken", "chicken breast", "chicken thigh", "chicken wing",
            "poultry", "turkey", "duck",
        ],
    },
    {
        "commodity_slug": "cattle",
        "display_name": "Cattle/Beef",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "beef", "cattle", "steak", "ground beef", "veal",
        ],
    },
    {
        "commodity_slug": "fish",
        "display_name": "Fish",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "fish", "salmon", "tuna", "cod", "tilapia", "catfish",
            "shrimp", "seafood",
        ],
    },
    {
        "commodity_slug": "pepper",
        "display_name": "Pepper",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "pepper", "bell pepper", "sweet pepper", "hot pepper",
            "chili pepper", "jalapeno",
        ],
    },
    {
        "commodity_slug": "onion",
        "display_name": "Onion",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "onion", "onions", "shallot", "shallots", "scallion", "green onion",
        ],
    },
    {
        "commodity_slug": "mushroom",
        "display_name": "Mushroom",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "mushroom", "mushrooms", "shiitake", "portobello", "cremini",
        ],
    },
    {
        "commodity_slug": "cabbage",
        "display_name": "Cabbage",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "cabbage", "red cabbage", "savoy cabbage", "chinese cabbage",
            "napa cabbage", "bok choy",
        ],
    },
    {
        "commodity_slug": "peas",
        "display_name": "Peas",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "peas", "green peas", "snap peas", "snow peas", "split peas",
        ],
    },
    {
        "commodity_slug": "lentils",
        "display_name": "Lentils",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "lentils", "red lentils", "green lentils", "brown lentils",
        ],
    },
    {
        "commodity_slug": "chickpeas",
        "display_name": "Chickpeas",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "chickpeas", "chickpea", "garbanzo beans", "hummus",
        ],
    },
    {
        "commodity_slug": "avocado",
        "display_name": "Avocado",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "avocado", "avocados", "guacamole",
        ],
    },
    {
        "commodity_slug": "pineapple",
        "display_name": "Pineapple",
        "consumption_tier": "occasional",
        "ingredient_aliases": [
            "pineapple", "pineapples", "pineapple juice",
        ],
    },
    {
        "commodity_slug": "mango",
        "display_name": "Mango",
        "consumption_tier": "occasional",
        "ingredient_aliases": [
            "mango", "mangoes", "mangos",
        ],
    },
    {
        "commodity_slug": "watermelon",
        "display_name": "Watermelon",
        "consumption_tier": "occasional",
        "ingredient_aliases": [
            "watermelon", "watermelons",
        ],
    },
    {
        "commodity_slug": "cantaloupe",
        "display_name": "Cantaloupe",
        "consumption_tier": "occasional",
        "ingredient_aliases": [
            "cantaloupe", "cantaloupes",
        ],
    },
    {
        "commodity_slug": "cauliflower",
        "display_name": "Cauliflower",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "cauliflower",
        ],
    },
    {
        "commodity_slug": "squash",
        "display_name": "Squash",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "squash", "butternut squash", "acorn squash", "zucchini",
        ],
    },
    {
        "commodity_slug": "asparagus",
        "display_name": "Asparagus",
        "consumption_tier": "occasional",
        "ingredient_aliases": [
            "asparagus",
        ],
    },
    {
        "commodity_slug": "plum",
        "display_name": "Plum",
        "consumption_tier": "occasional",
        "ingredient_aliases": [
            "plum", "plums", "prune", "prunes",
        ],
    },
    {
        "commodity_slug": "raspberry",
        "display_name": "Raspberry",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "raspberry", "raspberries",
        ],
    },
    {
        "commodity_slug": "blackberry",
        "display_name": "Blackberry",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "blackberry", "blackberries",
        ],
    },
    {
        "commodity_slug": "pumpkin",
        "display_name": "Pumpkin",
        "consumption_tier": "occasional",
        "ingredient_aliases": [
            "pumpkin", "pumpkins", "pumpkin seeds",
        ],
    },
    {
        "commodity_slug": "hog, meat",
        "display_name": "Pork",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "pork", "ham", "bacon", "sausage", "salami",
        ],
    },
    {
        "commodity_slug": "honey",
        "display_name": "Honey",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "honey",
        ],
    },
    {
        "commodity_slug": "cocoa",
        "display_name": "Cocoa",
        "consumption_tier": "weekly",
        "ingredient_aliases": [
            "cocoa", "chocolate", "cocoa powder",
        ],
    },
    {
        "commodity_slug": "coconut",
        "display_name": "Coconut",
        "consumption_tier": "occasional",
        "ingredient_aliases": [
            "coconut", "coconut milk", "coconut oil", "coconut water",
        ],
    },
    {
        "commodity_slug": "tea",
        "display_name": "Tea",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "tea", "green tea", "black tea", "herbal tea",
        ],
    },
    {
        "commodity_slug": "coffee",
        "display_name": "Coffee",
        "consumption_tier": "daily",
        "ingredient_aliases": [
            "coffee",
        ],
    },
    # ── Remaining high-volume categories ───────────────────────────────
    {
        "commodity_slug": "water",
        "display_name": "Water",
        "consumption_tier": "daily",
        "ingredient_aliases": ["water", "drinking water", "bottled water"],
    },
    {
        "commodity_slug": "sunflower",
        "display_name": "Sunflower",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["sunflower", "sunflower seeds", "sunflower oil"],
    },
    {
        "commodity_slug": "melon",
        "display_name": "Melon",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["melon", "melons", "honeydew"],
    },
    {
        "commodity_slug": "radish",
        "display_name": "Radish",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["radish", "radishes"],
    },
    {
        "commodity_slug": "garlic",
        "display_name": "Garlic",
        "consumption_tier": "daily",
        "ingredient_aliases": ["garlic"],
    },
    {
        "commodity_slug": "beet",
        "display_name": "Beet",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["beet", "beets", "beetroot"],
    },
    {
        "commodity_slug": "apricot",
        "display_name": "Apricot",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["apricot", "apricots", "dried apricots"],
    },
    {
        "commodity_slug": "canola",
        "display_name": "Canola",
        "consumption_tier": "daily",
        "ingredient_aliases": ["canola", "canola oil", "rapeseed"],
    },
    {
        "commodity_slug": "nectarine",
        "display_name": "Nectarine",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["nectarine", "nectarines"],
    },
    {
        "commodity_slug": "okra",
        "display_name": "Okra",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["okra"],
    },
    {
        "commodity_slug": "table olives",
        "display_name": "Olives",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["olives", "olive", "table olives"],
    },
    {
        "commodity_slug": "eggplant",
        "display_name": "Eggplant",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["eggplant", "eggplants", "aubergine"],
    },
    {
        "commodity_slug": "cranberry",
        "display_name": "Cranberry",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["cranberry", "cranberries", "cranberry juice"],
    },
    {
        "commodity_slug": "papaya",
        "display_name": "Papaya",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["papaya", "papayas"],
    },
    {
        "commodity_slug": "dates",
        "display_name": "Dates",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["dates", "date"],
    },
    {
        "commodity_slug": "grapefruit",
        "display_name": "Grapefruit",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["grapefruit", "grapefruits"],
    },
    {
        "commodity_slug": "parsley",
        "display_name": "Parsley",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["parsley"],
    },
    {
        "commodity_slug": "walnut",
        "display_name": "Walnut",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["walnut", "walnuts"],
    },
    {
        "commodity_slug": "flaxseed",
        "display_name": "Flaxseed",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["flaxseed", "flax seeds"],
    },
    {
        "commodity_slug": "hazelnut",
        "display_name": "Hazelnut",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["hazelnut", "hazelnuts"],
    },
    {
        "commodity_slug": "mint",
        "display_name": "Mint",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["mint", "peppermint", "spearmint"],
    },
    {
        "commodity_slug": "ginger",
        "display_name": "Ginger",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["ginger"],
    },
    {
        "commodity_slug": "turmeric",
        "display_name": "Turmeric",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["turmeric"],
    },
    {
        "commodity_slug": "quinoa",
        "display_name": "Quinoa",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["quinoa"],
    },
    {
        "commodity_slug": "buckwheat",
        "display_name": "Buckwheat",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["buckwheat"],
    },
    {
        "commodity_slug": "sugar_beets",
        "display_name": "Sugar Beets",
        "consumption_tier": "daily",
        "ingredient_aliases": ["sugar beets", "sugar_beets"],
    },
    # ── Final sweep ────────────────────────────────────────────────────
    {
        "commodity_slug": "brussels sprouts",
        "display_name": "Brussels Sprouts",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["brussels sprouts"],
    },
    {
        "commodity_slug": "pflaume",
        "display_name": "Plum (German)",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["pflaume"],
    },
    {
        "commodity_slug": "rye",
        "display_name": "Rye",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["rye", "rye flour", "rye bread"],
    },
    {
        "commodity_slug": "cassava",
        "display_name": "Cassava",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["cassava", "tapioca", "yuca"],
    },
    {
        "commodity_slug": "artichoke",
        "display_name": "Artichoke",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["artichoke", "artichokes"],
    },
    {
        "commodity_slug": "kiwi",
        "display_name": "Kiwi",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["kiwi", "kiwis"],
    },
    {
        "commodity_slug": "chestnut",
        "display_name": "Chestnut",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["chestnut", "chestnuts"],
    },
    {
        "commodity_slug": "rutabaga",
        "display_name": "Rutabaga",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["rutabaga", "rutabagas", "swede"],
    },
    {
        "commodity_slug": "baby_food",
        "display_name": "Baby Food",
        "consumption_tier": "daily",
        "ingredient_aliases": ["baby food", "baby_food", "infant food"],
    },
    {
        "commodity_slug": "herbs",
        "display_name": "Herbs",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["herbs", "fresh herbs", "dried herbs"],
    },
    {
        "commodity_slug": "fig",
        "display_name": "Fig",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["fig", "figs", "dried figs"],
    },
    {
        "commodity_slug": "persimmon",
        "display_name": "Persimmon",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["persimmon", "persimmons"],
    },
    {
        "commodity_slug": "collard greens",
        "display_name": "Collard Greens",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["collard greens", "collards"],
    },
    {
        "commodity_slug": "currants",
        "display_name": "Currants",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["currants", "currant"],
    },
    {
        "commodity_slug": "rhubarb",
        "display_name": "Rhubarb",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["rhubarb"],
    },
    {
        "commodity_slug": "turnip",
        "display_name": "Turnip",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["turnip", "turnips"],
    },
    {
        "commodity_slug": "watercress",
        "display_name": "Watercress",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["watercress"],
    },
    {
        "commodity_slug": "fennel",
        "display_name": "Fennel",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["fennel"],
    },
    {
        "commodity_slug": "leek",
        "display_name": "Leek",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["leek", "leeks"],
    },
    {
        "commodity_slug": "arugula",
        "display_name": "Arugula",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["arugula", "rocket"],
    },
    {
        "commodity_slug": "chard",
        "display_name": "Chard",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["chard", "swiss chard"],
    },
    {
        "commodity_slug": "kohlrabi",
        "display_name": "Kohlrabi",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["kohlrabi"],
    },
    {
        "commodity_slug": "salsify",
        "display_name": "Salsify",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["salsify"],
    },
    {
        "commodity_slug": "purslane",
        "display_name": "Purslane",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["purslane"],
    },
    {
        "commodity_slug": "horseradish",
        "display_name": "Horseradish",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["horseradish"],
    },
    {
        "commodity_slug": "jerusalem_artichoke",
        "display_name": "Jerusalem Artichoke",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["jerusalem artichoke", "topinambur"],
    },
    {
        "commodity_slug": "parsnip",
        "display_name": "Parsnip",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["parsnip", "parsnips"],
    },
    {
        "commodity_slug": "anise",
        "display_name": "Anise",
        "consumption_tier": "rare",
        "ingredient_aliases": ["anise", "aniseed"],
    },
    {
        "commodity_slug": "tarragon",
        "display_name": "Tarragon",
        "consumption_tier": "rare",
        "ingredient_aliases": ["tarragon"],
    },
    {
        "commodity_slug": "acai",
        "display_name": "Acai",
        "consumption_tier": "occasional",
        "ingredient_aliases": ["acai"],
    },
    {
        "commodity_slug": "algae",
        "display_name": "Algae",
        "consumption_tier": "rare",
        "ingredient_aliases": ["algae", "spirulina", "chlorella"],
    },
    {
        "commodity_slug": "amla",
        "display_name": "Amla",
        "consumption_tier": "rare",
        "ingredient_aliases": ["amla", "indian gooseberry"],
    },
    {
        "commodity_slug": "marjoram",
        "display_name": "Marjoram",
        "consumption_tier": "rare",
        "ingredient_aliases": ["marjoram"],
    },
    {
        "commodity_slug": "ajwain",
        "display_name": "Ajwain",
        "consumption_tier": "rare",
        "ingredient_aliases": ["ajwain"],
    },
    {
        "commodity_slug": "cashew",
        "display_name": "Cashew",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["cashew", "cashews"],
    },
    {
        "commodity_slug": "lamb",
        "display_name": "Lamb",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["lamb", "mutton"],
    },
    {
        "commodity_slug": "acerola",
        "display_name": "Acerola",
        "consumption_tier": "rare",
        "ingredient_aliases": ["acerola"],
    },
    {
        "commodity_slug": "zucchini",
        "display_name": "Zucchini",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["zucchini"],
    },
    {
        "commodity_slug": "infant_cereal",
        "display_name": "Infant Cereal",
        "consumption_tier": "daily",
        "ingredient_aliases": ["infant cereal", "baby cereal"],
    },
    {
        "commodity_slug": "lime",
        "display_name": "Lime",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["lime", "limes"],
    },
    {
        "commodity_slug": "chili pepper",
        "display_name": "Chili Pepper",
        "consumption_tier": "weekly",
        "ingredient_aliases": ["chili pepper", "chili", "jalapeno", "habanero"],
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
