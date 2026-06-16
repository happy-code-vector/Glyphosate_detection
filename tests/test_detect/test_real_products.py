"""
Test the detection engine with actual product JSON files from OpenFoodFacts.
Uses the real SQLite database (residueiq.db) for data lookups.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from tests.test_detect.conftest import create_test_db, seed_all, seed_regulatory_data

DB_PATH = Path(__file__).parent.parent.parent / "data" / "residueiq.db"
PRODUCTS_DIR = Path(__file__).parent.parent.parent / "data" / "raw_data" / "openfoodfacts"
SKIP = not DB_PATH.exists() or not PRODUCTS_DIR.exists()


def load_product_json(filename: str) -> dict:
    with open(PRODUCTS_DIR / filename, "r", encoding="utf-8") as f:
        return json.load(f)


def load_all_products() -> list[dict]:
    products = []
    for f in PRODUCTS_DIR.glob("*.json"):
        try:
            products.append(load_product_json(f.name))
        except (json.JSONDecodeError, KeyError):
            pass
    return products


@unittest.skipIf(SKIP, "Real database or product JSONs not found")
class TestRealProductScan(unittest.TestCase):
    """Test scan_barcode with actual product JSON against real database."""

    @classmethod
    def setUpClass(cls):
        # Use the real database
        cls.engine = None

    def setUp(self):
        from detect.engine import DetectionEngine
        self.engine = DetectionEngine(str(DB_PATH))

    def tearDown(self):
        self.engine.close()

    def _mock_off_client(self, product_data: dict):
        """Create a mocked OpenFoodFacts client returning the given product."""
        mock_client = MagicMock()
        mock_client.lookup.return_value = product_data
        self.engine._off_client = mock_client
        return mock_client

    def test_pringles_original(self):
        """Pringles Original Potato Crisps — has corn, wheat starch, rice."""
        product = load_product_json("0038000138416.json")
        self._mock_off_client(product)

        result = self.engine.scan_barcode(product["barcode"])

        self.assertIsNotNone(result, f"scan_barcode returned None for {product['barcode']}")
        self.assertEqual(result.name, "Original Potato Crisps")
        self.assertEqual(result.brand, "Pringles")
        self.assertIn(result.risk_level, ["none", "low", "medium", "high", "unknown"])
        self.assertIn(result.tier_used, ["product", "ingredient", "category", "none"])
        self.assertIn(result.data_confidence, ["high", "medium", "low"])
        # Should have parsed ingredients
        self.assertGreater(len(result.ingredients_parsed), 0)
        print(f"\n  Pringles: risk={result.risk_level}, tier={result.tier_used}, "
              f"confidence={result.data_confidence}, ingredients={len(result.ingredients_parsed)}")

    def test_coca_cola(self):
        """Coca-Cola — mostly water/sugar, low risk ingredients."""
        product = load_product_json("5000112637922.json")
        self._mock_off_client(product)

        result = self.engine.scan_barcode(product["barcode"])

        self.assertIsNotNone(result)
        self.assertEqual(result.name, "Coca Cola")
        self.assertIn(result.risk_level, ["none", "low", "medium", "high", "unknown"])
        print(f"\n  Coca-Cola: risk={result.risk_level}, tier={result.tier_used}, "
              f"confidence={result.data_confidence}")

    def test_nutella(self):
        """Nutella — has palm oil, sugar, cocoa."""
        product = load_product_json("3017620422003.json")
        self._mock_off_client(product)

        result = self.engine.scan_barcode(product["barcode"])

        self.assertIsNotNone(result)
        self.assertEqual(result.name, "Nutella")
        self.assertIn(result.risk_level, ["none", "low", "medium", "high", "unknown"])
        print(f"\n  Nutella: risk={result.risk_level}, tier={result.tier_used}, "
              f"confidence={result.data_confidence}, flags={len(result.flags)}")

    def test_ritz_crackers(self):
        """Ritz Bits — wheat, dairy ingredients."""
        product = load_product_json("0044000032159.json")
        self._mock_off_client(product)

        result = self.engine.scan_barcode(product["barcode"])

        self.assertIsNotNone(result)
        self.assertIn(result.risk_level, ["none", "low", "medium", "high", "unknown"])
        print(f"\n  Ritz: risk={result.risk_level}, tier={result.tier_used}, "
              f"confidence={result.data_confidence}")

    def test_twix(self):
        """Twix glacé — wheat, dairy, sugar."""
        product = load_product_json("5000159484695.json")
        self._mock_off_client(product)

        result = self.engine.scan_barcode(product["barcode"])

        self.assertIsNotNone(result)
        self.assertIn(result.risk_level, ["none", "low", "medium", "high", "unknown"])
        print(f"\n  Twix: risk={result.risk_level}, tier={result.tier_used}, "
              f"confidence={result.data_confidence}")

    def test_all_products_scan_without_crash(self):
        """All product JSONs should scan without exceptions."""
        products = load_all_products()
        self.assertGreater(len(products), 0, "No product JSONs found")

        results = []
        for product in products:
            self._mock_off_client(product)
            try:
                result = self.engine.scan_barcode(product["barcode"])
                results.append((product["product_name"], result))
            except Exception as e:
                self.fail(f"scan_barcode crashed on {product['product_name']}: {e}")

        print(f"\n  Scanned {len(results)} products:")
        for name, result in results:
            if result:
                print(f"    {name}: risk={result.risk_level}, tier={result.tier_used}, "
                      f"confidence={result.data_confidence}, "
                      f"contaminants={result.contaminant_report.total_detected if result.contaminant_report else '?'}, "
                      f"bio={len(result.biomonitoring)}")
            else:
                print(f"    {name}: NOT FOUND")

    def test_ingredient_risk_with_real_ingredients(self):
        """Test ingredient_risk directly with real ingredient lists."""
        product = load_product_json("0038000138416.json")  # Pringles
        ingredients = product.get("ingredients", [])

        result = self.engine.ingredient_risk(
            product_name=product["product_name"],
            ingredients=ingredients,
            contaminant="glyphosate",
        )

        self.assertIsNotNone(result)
        self.assertIn(result.risk_level, ["none", "low", "medium", "high", "unknown"])
        self.assertIn(result.tier_used, ["product", "ingredient", "category", "none"])
        print(f"\n  Pringles ingredient_risk: risk={result.risk_level}, tier={result.tier_used}, "
              f"score={result.score:.2f}, notes={result.notes}")

    def test_food_category_risk_lookup(self):
        """Test food_risk for categories that real products map to."""
        # These are common food categories from the product ingredients
        categories = ["oats", "wheat", "corn", "rice", "soybean", "sugar"]

        for cat in categories:
            result = self.engine.food_risk(cat, contaminant="glyphosate")
            if result:
                self.assertIn(result.risk_level, ["none", "low", "medium", "high", "unknown"])
                print(f"\n  {cat}/glyphosate: risk={result.risk_level}, "
                      f"detection_rate={result.detection_rate}, max_ppb={result.max_ppb}")
            else:
                print(f"\n  {cat}/glyphosate: no data")


@unittest.skipIf(SKIP, "Real database or product JSONs not found")
class TestRealProductIngredientParsing(unittest.TestCase):
    """Test ingredient parsing with real product data."""

    def test_parse_pringles_ingredients(self):
        product = load_product_json("0038000138416.json")
        from detect.ingredient_parser import parse_ingredients
        parsed = parse_ingredients(product["ingredients_text"])
        self.assertGreater(len(parsed), 0)
        print(f"\n  Pringles parsed {len(parsed)} ingredients: {parsed[:5]}...")

    def test_parse_coca_cola_ingredients(self):
        product = load_product_json("5000112637922.json")
        from detect.ingredient_parser import parse_ingredients
        parsed = parse_ingredients(product["ingredients_text"])
        self.assertGreater(len(parsed), 0)
        print(f"\n  Coca-Cola parsed {len(parsed)} ingredients: {parsed}")

    def test_parse_nutella_ingredients(self):
        product = load_product_json("3017620422003.json")
        from detect.ingredient_parser import parse_ingredients
        parsed = parse_ingredients(product["ingredients_text"])
        self.assertGreater(len(parsed), 0)
        print(f"\n  Nutella parsed {len(parsed)} ingredients: {parsed}")


if __name__ == "__main__":
    unittest.main()
