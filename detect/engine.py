import os
import sqlite3

from detect.food_risk import FoodRiskQuery
from detect.product_lookup import ProductLookupQuery
from detect.water_quality import WaterQualityQuery
from detect.comparison import ComparisonQuery
from detect.ingredient_risk import IngredientRiskQuery, IngredientRiskResult
from detect.models import (
    FoodRiskResult,
    ProductResult,
    WaterQualityResult,
    InternationalComparisonResult,
)


class DetectionEngine:
    def __init__(self, db_path: str):
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database file not found: {db_path}")
        if not sqlite3.connect(db_path).execute("SELECT 1"):
            raise FileNotFoundError(f"Invalid SQLite database: {db_path}")
        try:
            self._conn = sqlite3.connect(db_path)
            self._conn.row_factory = sqlite3.Row
        except sqlite3.OperationalError:
            raise FileNotFoundError(f"Cannot open database: {db_path}")

        self._food_risk = FoodRiskQuery(self._conn)
        self._product_lookup = ProductLookupQuery(self._conn)
        self._water_quality = WaterQualityQuery(self._conn)
        self._comparison = ComparisonQuery(self._conn)
        self._ingredient_risk = IngredientRiskQuery(self._conn)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._conn.close()

    def food_risk(
        self, food_category: str, contaminant: str | None = None
    ) -> FoodRiskResult | list[FoodRiskResult] | None:
        return self._food_risk.execute(food_category, contaminant)

    def product_lookup(
        self, query: str, contaminant: str | None = None
    ) -> list[ProductResult]:
        return self._product_lookup.execute(query, contaminant)

    def water_quality(
        self,
        state: str | None = None,
        contaminant: str | None = None,
        water_type: str | None = None,
    ) -> list[WaterQualityResult]:
        return self._water_quality.execute(state, contaminant, water_type)

    def international_comparison(
        self, food_category: str, contaminant: str = "glyphosate"
    ) -> InternationalComparisonResult:
        return self._comparison.execute(food_category, contaminant)

    def ingredient_risk(
        self,
        product_name: str,
        ingredients_text: str,
        contaminant: str = "glyphosate",
        food_category: str | None = None,
    ) -> IngredientRiskResult:
        """
        Three-tier risk scoring based on ingredients.

        Risk hierarchy:
        1. Product → Check if specific product is flagged glyphosate-free
        2. Ingredient → Map each ingredient to category, use category data
        3. Category → Fall back to product's primary food category

        Args:
            product_name: Name of the product (for Tier 1 lookup)
            ingredients_text: Raw ingredients string from Open Food Facts
            contaminant: Contaminant to check (default: glyphosate)
            food_category: Optional fallback category if ingredient mapping fails
        """
        return self._ingredient_risk.execute(
            product_name, ingredients_text, contaminant, food_category
        )