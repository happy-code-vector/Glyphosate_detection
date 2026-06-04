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
    "butter": "butter", "butter, cheese": "butter", "ghee": "butter", "ghee, oils": "butter",
    "blueberries": "blueberries", "fresh vegetables": "fresh_vegetables",
    "mushrooms": "fresh_vegetables", "mushroom broth": "fresh_vegetables",
    "hearts of palm": "fresh_vegetables", "fresh fruit": "fresh_fruit",
    "fruit juice": "fresh_fruit", "dates": "fresh_fruit", "jam": "fresh_fruit",
    "honey": "fresh_fruit", "honey, sugar, honey patties": "fresh_fruit",
    "honey products and others": "fresh_fruit", "syrup": "fresh_fruit",
    "infant food": "infant_cereal", "baby food": "infant_cereal",
    "plant-based milks, creams and creamers, coffee, refreshers": "oats",
    "coffee creamers, oat milk": "oats", "coffee, creamers": "oats",
    "coffee, oat milk coffee": "oats", "flaxmilk, plantmilk": "fresh_fruit",
    "plant milk": "fresh_fruit", "plant-based milk, plant-based butter": "fresh_fruit",
    "nut milks": "fresh_fruit", "nut butters, nut flour": "fresh_fruit",
    "dairy free milk ingredients": "fresh_fruit", "cream": "fresh_fruit",
    "skyr": "fresh_fruit", "goat milk powder": "fresh_fruit",
    "dietary supplements": "fresh_vegetables", "dietary supplement": "fresh_vegetables",
    "supplements": "fresh_vegetables", "protein": "soybeans",
    "protein bars": "soybeans", "protein bar": "soybeans", "protein shake": "soybeans",
    "plant-based protein": "soybeans", "plant-based meat, protein drinks": "soybeans",
    "plant-based meat": "soybeans", "plant-based meals": "soybeans",
    "pea protein": "peas", "whey protein isolate": "fresh_fruit",
    "whey protein": "fresh_fruit", "collagen": "fresh_fruit",
    "prebiotic fiber": "fresh_fruit", "prebiotics / probiotics": "fresh_fruit",
    "healthy gut supplements": "fresh_fruit", "tinctures, supplements": "fresh_vegetables",
    "ashwagandha": "fresh_vegetables", "chicken": "fresh_vegetables",
    "bone broth": "fresh_vegetables", "broth": "fresh_vegetables",
    "pet food": "fresh_vegetables", "dog food": "fresh_vegetables",
    "wine": "fresh_fruit", "beer": "fresh_fruit", "drinks": "fresh_fruit",
    "superfood drinks": "fresh_fruit", "gin cocktail": "fresh_fruit",
    "avocado products and others": "fresh_vegetables", "cooking oil": "canola",
    "oil": "canola", "chia, mct oil, avocado oil, sunflower oil": "canola",
    "hemp cbd": "fresh_vegetables", "hemp products": "fresh_vegetables",
    "hemp products, fruit products, cereal products, legume products": "fresh_vegetables",
    "veggie burgers, fries, nuggets": "fresh_vegetables",
    "tortillas, quesadillas": "wheat", "mac & cheese": "wheat",
    "ready-to-eat meals": "fresh_vegetables", "indian food": "fresh_vegetables",
    "indian foods": "fresh_vegetables", "umami sauce": "fresh_vegetables",
    "matcha": "fresh_vegetables", "fresh beetroot concentrate powder": "fresh_vegetables",
    "resistant potato starch": "fresh_vegetables", "clary sage seed oil": "canola",
    "pecans and granola": "oats", "snack bars": "oats", "ingredients": "fresh_vegetables",
    "bioherbicide": "fresh_vegetables", "plant-based ingredients (pea)": "peas",
    "insect repellent": "fresh_vegetables", "turmeric extract, pomegranate extract": "fresh_vegetables",
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
