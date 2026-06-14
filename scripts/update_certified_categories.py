"""One-time migration to update certified_products food_category from raw_category."""
import sqlite3

CATEGORY_HINTS = {
    "oats": "oats", "oat milk": "oats", "oat bars": "oats", "oatmeal": "oats",
    "oats and oat ingredients, pulses": "oats", "oats, groats, oat flour": "oats",
    "oat concentrates": "oats", "ready-to-eat oats": "oats",
    "morning oats, overnight oats": "oats",
    "oat milk, oat creamers, nut milks, nut creamers, sour cream": "oats",
    "cereal": "oats", "cereal, granola": "oats", "granola": "oats", "granola, oats": "oats",
    "breakfast biscuits, cookie dough, pie crust, pizza crust, puff pastry": "wheat",
    "biscuits, cookies, gnocchi pizza, ravioli": "wheat", "cookies": "wheat",
    "bread": "wheat", "bagels, bread": "wheat", "sourdough bread": "wheat",
    "flour": "wheat", "wheat": "wheat", "wheat flour and wheat products": "wheat",
    "pasta": "wheat", "pasta, flour, tomatoes": "wheat", "pasta, tomatoes": "wheat",
    "einkorn pasta, einkorn crackers": "wheat", "noodles": "wheat", "crackers": "wheat",
    "pie dough, pastry dough, brownies, cookies, pie shells, apple pie": "wheat",
    "pie shells, pastry dough": "wheat", "brownies": "wheat",
    "snacks": "corn", "chips": "corn", "rice": "rice", "rice crackers": "rice",
    "lentils": "lentils", "lentils, split peas, beans, barley": "lentils",
    "freshwater lentils": "lentils", "chickpeas": "chickpeas",
    "beans": "beans", "beans, chickpeas": "beans",
    "snacks: chickpeas, lentils, fava beans": "chickpeas",
    "wheat, chickpeas, lentils, green split peas, flour": "wheat",
    "quinoa": "quinoa", "peas": "peas", "barley": "barley", "rye": "rye",
    "canola": "canola", "soybeans": "soybeans", "tofu": "soybeans", "corn": "corn",
    "sugar beets": "sugar_beets", "buckwheat": "buckwheat", "sunflower": "sunflower",
    "butter": "dairy", "butter, cheese": "dairy", "ghee": "dairy", "ghee, oils": "dairy",
    "blueberries": "blueberry", "fresh vegetables": None,
    "mushrooms": "mushroom", "mushroom broth": "mushroom",
    "hearts of palm": "palm", "fresh fruit": None,
    "fruit juice": None, "dates": "dates", "jam": None,
    "honey": "honey", "honey, sugar, honey patties": "honey",
    "honey products and others": "honey", "syrup": None,
    "infant food": "infant_cereal", "baby food": "baby_food",
    "plant-based milks, creams and creamers, coffee, refreshers": "oats",
    "coffee creamers, oat milk": "oats", "coffee, creamers": "coffee",
    "coffee, oat milk coffee": "oats", "flaxmilk, plantmilk": "flaxseed",
    "plant milk": None, "plant-based milk, plant-based butter": None,
    "nut milks": None, "nut butters, nut flour": None,
    "dairy free milk ingredients": None, "cream": "dairy",
    "skyr": "dairy", "goat milk powder": "dairy",
    "dietary supplements": None, "dietary supplement": None,
    "supplements": None, "protein": "soybeans",
    "protein bars": "soybeans", "protein bar": "soybeans", "protein shake": "soybeans",
    "plant-based protein": "soybeans", "plant-based meat, protein drinks": "soybeans",
    "plant-based meat": "soybeans", "plant-based meals": "soybeans",
    "pea protein": "peas", "whey protein isolate": "dairy",
    "whey protein": "dairy", "collagen": None,
    "prebiotic fiber": None, "prebiotics / probiotics": None,
    "healthy gut supplements": None, "tinctures, supplements": None,
    "ashwagandha": None, "chicken": "chicken",
    "bone broth": "chicken", "broth": "chicken",
    "pet food": None, "dog food": None,
    "wine": "grape", "beer": "barley", "drinks": None,
    "superfood drinks": None, "gin cocktail": None,
    "avocado products and others": "avocado", "cooking oil": "canola",
    "oil": "canola", "chia, mct oil, avocado oil, sunflower oil": "flaxseed",
    "hemp cbd": "hemp_seeds", "hemp products": "hemp_seeds",
    "hemp products, fruit products, cereal products, legume products": "hemp_seeds",
    "veggie burgers, fries, nuggets": None,
    "tortillas, quesadillas": "wheat", "mac & cheese": "wheat",
    "ready-to-eat meals": None, "indian food": None,
    "indian foods": None, "umami sauce": None,
    "matcha": "tea", "fresh beetroot concentrate powder": "beet",
    "resistant potato starch": "potato", "clary sage seed oil": "canola",
    "pecans and granola": "oats", "snack bars": "oats", "ingredients": None,
    "bioherbicide": None, "plant-based ingredients (pea)": "peas",
    "insect repellent": None, "turmeric extract, pomegranate extract": "pomegranate",
}


def main():
    conn = sqlite3.connect("data/residueiq.db")
    conn.row_factory = sqlite3.Row

    updated = 0
    for raw_cat, canonical in CATEGORY_HINTS.items():
        result = conn.execute(
            "UPDATE certified_products SET food_category = ? "
            "WHERE LOWER(raw_category) = LOWER(?) AND (food_category IS NULL OR food_category != ?)",
            (canonical, raw_cat, canonical),
        )
        updated += result.rowcount

    conn.commit()
    print(f"Updated {updated} rows")

    print()
    print("=== CERTIFIED PRODUCTS BY FOOD CATEGORY ===")
    rows = conn.execute(
        "SELECT food_category, COUNT(*) as count "
        "FROM certified_products GROUP BY food_category ORDER BY count DESC"
    ).fetchall()

    for r in rows:
        print(f"  {r['food_category']:20s} | {r['count']} products")

    print()
    print(f"Total: {sum(r['count'] for r in rows)}")
    conn.close()


if __name__ == "__main__":
    main()
