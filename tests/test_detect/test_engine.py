import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from tests.test_detect.conftest import create_test_db, seed_all
from detect.engine import DetectionEngine
from detect.models import (
    FoodRiskResult,
    ProductResult,
    WaterQualityResult,
    InternationalComparisonResult,
)


class TestDetectionEngine(unittest.TestCase):
    def setUp(self):
        self.conn = create_test_db()
        seed_all(self.conn)
        # Save in-memory DB to temp file so DetectionEngine can open it
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=True)
        self.tmp.close()
        dest = sqlite3.connect(self.tmp.name)
        for line in self.conn.iterdump():
            dest.execute(line)
        dest.commit()
        dest.close()
        self.engine = DetectionEngine(self.tmp.name)
        self.db_path = self.tmp.name

    def tearDown(self):
        self.engine.close()
        self.conn.close()

    def test_food_risk(self):
        result = self.engine.food_risk("oats", contaminant="glyphosate")
        self.assertIsInstance(result, FoodRiskResult)
        self.assertEqual(result.food_category, "oats")

    def test_product_lookup(self):
        results = self.engine.product_lookup("Cheerios")
        self.assertIsInstance(results, list)
        self.assertGreaterEqual(len(results), 1)
        self.assertIsInstance(results[0], ProductResult)

    def test_water_quality(self):
        results = self.engine.water_quality(state="California")
        self.assertIsInstance(results, list)
        self.assertGreaterEqual(len(results), 1)
        self.assertIsInstance(results[0], WaterQualityResult)

    def test_international_comparison(self):
        result = self.engine.international_comparison("oats")
        self.assertIsInstance(result, InternationalComparisonResult)

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            DetectionEngine("/nonexistent/path.db")

    def test_context_manager(self):
        with DetectionEngine(self.tmp.name) as engine:
            result = engine.food_risk("oats", contaminant="glyphosate")
            self.assertIsInstance(result, FoodRiskResult)

    @patch("detect.engine.OpenFoodFactsClient")
    def test_scan_barcode_product_found(self, MockOFFClient):
        """Test scan_barcode when product is found in Open Food Facts."""
        # Mock the OFF client to return a test product
        mock_client = MagicMock()
        mock_client.lookup.return_value = {
            "barcode": "0001600014588",
            "product_name": "Cheerios",
            "brand": "General Mills",
            "categories": ["breakfast-cereals"],
            "image_url": "",
            "is_organic": False,
            "ingredients": "Whole grain oats, corn starch, sugar, salt",
            "countries": "United States",
            "source": "OpenFoodFacts",
        }
        MockOFFClient.return_value = mock_client

        # Create engine with mocked client
        engine = DetectionEngine(self.tmp.name)
        engine._off_client = mock_client

        # Seed category aliases for ingredient mapping
        engine._conn.execute(
            "INSERT OR IGNORE INTO category_aliases (alias, canonical_key) VALUES (?, ?)",
            ("whole grain oats", "oats"),
        )
        engine._conn.execute(
            "INSERT OR IGNORE INTO category_aliases (alias, canonical_key) VALUES (?, ?)",
            ("corn starch", "corn"),
        )
        engine._conn.commit()

        result = engine.scan_barcode("0001600014588")

        self.assertIsNotNone(result)
        self.assertEqual(result.product_name, "Cheerios")
        self.assertIn(result.tier_used, ["product", "ingredient", "category"])
        engine.close()

    @patch("detect.engine.OpenFoodFactsClient")
    def test_scan_barcode_product_not_found(self, MockOFFClient):
        """Test scan_barcode when product is not found in Open Food Facts."""
        mock_client = MagicMock()
        mock_client.lookup.return_value = None
        MockOFFClient.return_value = mock_client

        engine = DetectionEngine(self.tmp.name)
        engine._off_client = mock_client

        result = engine.scan_barcode("9999999999999")

        self.assertIsNone(result)
        engine.close()


if __name__ == "__main__":
    unittest.main()