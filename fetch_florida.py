FLORIDA_SEED_DATA = [
    {"product_name": "Nature's Own Butter Bread", "brand": "Nature's Own",
     "food_category": "wheat", "ppb_value": 190.23, "published_date": "2026-02-01"},
    {"product_name": "Nature's Own Perfectly Crafted White", "brand": "Nature's Own",
     "food_category": "wheat", "ppb_value": 132.34, "published_date": "2026-02-01"},
    {"product_name": "Wonder Bread Classic White", "brand": "Wonder",
     "food_category": "wheat", "ppb_value": 45.0, "published_date": "2026-02-01"},
    {"product_name": "Sara Lee Honey Wheat", "brand": "Sara Lee",
     "food_category": "wheat", "ppb_value": 38.0, "published_date": "2026-02-01"},
    {"product_name": "Dave's Killer Bread 21 Whole Grains", "brand": "Dave's Killer Bread",
     "food_category": "wheat", "ppb_value": 75.5, "published_date": "2026-02-01"},
    {"product_name": "Dave's Killer Bread White Bread Done Right", "brand": "Dave's Killer Bread",
     "food_category": "wheat", "ppb_value": 52.0, "published_date": "2026-02-01"},
    {"product_name": "Pepperidge Farm Farmhouse Hearty White", "brand": "Pepperidge Farm",
     "food_category": "wheat", "ppb_value": 28.0, "published_date": "2026-02-01"},
    {"product_name": "Arnold Whole Grains 100% Whole Wheat", "brand": "Arnold",
     "food_category": "wheat", "ppb_value": 61.0, "published_date": "2026-02-01"},
    {"product_name": "Oroweat Country Buttermilk Bread", "brand": "Oroweat",
     "food_category": "wheat", "ppb_value": 33.0, "published_date": "2026-02-01"},
    {"product_name": "Martin's Potato Bread", "brand": "Martin's",
     "food_category": "wheat", "ppb_value": 19.0, "published_date": "2026-02-01"},
]


def fetch() -> list[dict]:
    rows = []
    for item in FLORIDA_SEED_DATA:
        rows.append({
            "tier": 1,
            "source_name": "Florida Healthy Florida First",
            "source_url": "https://www.floridahealth.gov/newsroom/2026/02/bread-glyphosate-testing.pr.html",
            "published_date": item["published_date"],
            "data_year": int(item["published_date"][:4]),
            "product_name": item["product_name"],
            "brand": item.get("brand"),
            "food_category": item["food_category"],
            "raw_category": item["food_category"],
            "ppb_value": item.get("ppb_value"),
            "detection_rate": None,
            "confidence": "high",
            "methodology_note": "Florida Dept of Health lab test. Note: full methodology not publicly disclosed.",
            "is_organic": "organic" in item["product_name"].lower(),
        })
    return rows
