import os
import sqlite3
from typing import Optional

from detect.food_risk import FoodRiskQuery
from detect.product_lookup import ProductLookupQuery
from detect.water_quality import WaterQualityQuery
from detect.comparison import ComparisonQuery
from detect.ingredient_risk import IngredientRiskQuery, IngredientRiskResult
from detect.open_food_facts import OpenFoodFactsClient
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
        self._off_client = OpenFoodFactsClient()

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
        ingredients: list[dict] | str,
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
            ingredients: Either:
                - List of dicts with 'id', 'name', 'text', 'percent' (from OFF API)
                - Raw ingredients string (fallback, will be parsed)
            contaminant: Contaminant to check (default: glyphosate)
            food_category: Optional fallback category if ingredient mapping fails
        """
        return self._ingredient_risk.execute(
            product_name, ingredients, contaminant, food_category
        )

    def scan_barcode(
        self,
        barcode: str,
        contaminant: str = "glyphosate",
    ) -> Optional[IngredientRiskResult]:
        """
        Scan a barcode and return ingredient-based risk assessment.

        Complete flow:
        1. Look up product via Open Food Facts API
        2. Run three-tier risk scoring (product → ingredient → category)

        Args:
            barcode: Product barcode (EAN-13, UPC, etc.)
            contaminant: Contaminant to check (default: glyphosate)

        Returns:
            IngredientRiskResult with risk_level, score, and breakdown
            None if product not found in Open Food Facts
        """
        # Step 1: Look up product from Open Food Facts
        product = self._off_client.lookup(barcode)
        if not product:
            return None

        # Step 2: Run ingredient risk scoring
        # Use first OFF category as fallback food_category
        food_category = None
        if product.get("categories"):
            # Try to map first OFF category to our canonical categories
            from db.database import normalize_category
            for cat in product["categories"]:
                mapped = normalize_category(cat, conn=self._conn)
                if mapped:
                    food_category = mapped
                    break

        return self._ingredient_risk.execute(
            product_name=product["product_name"],
            ingredients=product["ingredients"],  # Now structured list from OFF API
            contaminant=contaminant,
            food_category=food_category,
        )