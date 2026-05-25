CATEGORY_MAP = {
    # Oats
    "oat": "oats", "oats": "oats", "oat cereal": "oats",
    "oat-based": "oats", "oatmeal": "oats", "oat flour": "oats",
    "rolled oats": "oats", "oat bran": "oats", "oat grain": "oats",
    # Wheat
    "wheat": "wheat", "wheat grain": "wheat", "wheat flour": "wheat",
    "whole wheat": "wheat", "bread wheat": "wheat", "wheat bran": "wheat",
    "pasta": "wheat", "bread": "wheat", "flour": "wheat",
    # Soy
    "soy": "soybeans", "soya": "soybeans", "soybean": "soybeans",
    "soy-based": "soybeans", "soy products": "soybeans", "tofu": "soybeans",
    # Corn
    "corn": "corn", "maize": "corn", "cornstarch": "corn",
    "corn flour": "corn", "corn grain": "corn",
    # Legumes
    "chickpea": "chickpeas", "garbanzo": "chickpeas", "hummus": "chickpeas",
    "lentil": "lentils", "dried lentils": "lentils",
    "bean": "beans", "pinto bean": "beans", "kidney bean": "beans",
    "pea": "peas", "dried peas": "peas", "split peas": "peas",
    # Grains
    "barley": "barley", "barley grain": "barley",
    "canola": "canola", "rapeseed": "canola", "rape": "canola",
    "buckwheat": "buckwheat",
    "quinoa": "quinoa",
    "rye": "rye", "rye grain": "rye",
    "rice": "rice", "white rice": "rice", "brown rice": "rice",
    # Produce
    "fresh vegetables": "fresh_vegetables", "vegetables": "fresh_vegetables",
    "lettuce": "fresh_vegetables", "spinach": "fresh_vegetables",
    "fresh fruit": "fresh_fruit", "fruit": "fresh_fruit", "apple": "fresh_fruit",
    # Infant
    "infant food": "infant_cereal", "baby food": "infant_cereal",
    "infant cereal": "infant_cereal", "children cereal": "infant_cereal",
    # Sugar
    "sugar beet": "sugar_beets", "beet sugar": "sugar_beets", "sugar": "sugar_beets",
}


def normalize_category(raw: str) -> str | None:
    if not raw:
        return None
    raw_lower = raw.lower().strip()
    if raw_lower in CATEGORY_MAP:
        return CATEGORY_MAP[raw_lower]
    for key, val in CATEGORY_MAP.items():
        if key in raw_lower:
            return val
    return None
