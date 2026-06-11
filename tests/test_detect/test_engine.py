import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from tests.test_detect.conftest import create_test_db, seed_all, seed_regulatory_data
from detect.engine import DetectionEngine
from detect.models import (
    FoodRiskResult,
    ProductResult,
    WaterQualityResult,
    InternationalComparisonResult,
    ProductScanResult,
)


class TestDetectionEngine(unittest.TestCase):
    def setUp(self):
        self.conn = create_test_db()
        seed_all(self.conn)
        seed_regulatory_data(self.conn)
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
        """Test scan_barcode returns ProductScanResult with all fields."""
        mock_client = MagicMock()
        mock_client.lookup.return_value = {
            "barcode": "0001600014588",
            "product_name": "Cheerios",
            "brand": "General Mills",
            "categories": ["breakfast-cereals"],
            "image_url": "",
            "is_organic": False,
            "ingredients_text": "Whole grain oats, corn starch, sugar, salt",
            "ingredients": [
                {"name": "whole grain oats", "text": "whole grain oats", "percent_estimate": 80},
                {"name": "corn starch", "text": "corn starch", "percent_estimate": 10},
                {"name": "sugar", "text": "sugar", "percent_estimate": 5},
                {"name": "salt", "text": "salt", "percent_estimate": 5},
            ],
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
        self.assertIsInstance(result, ProductScanResult)
        self.assertEqual(result.name, "Cheerios")
        self.assertEqual(result.brand, "General Mills")
        self.assertEqual(result.upc, "0001600014588")
        # Risk data
        self.assertIn(result.tier_used, ["product", "ingredient", "category"])
        self.assertIn(result.risk_level, ["none", "low", "medium", "high", "unknown"])
        self.assertIn(result.data_confidence, ["high", "medium", "low"])
        # Ingredients parsed
        self.assertEqual(len(result.ingredients_parsed), 4)
        self.assertIn("whole grain oats", result.ingredients_parsed)
        # Flags and commodities (may be empty if no seed data matches)
        self.assertIsInstance(result.flags, list)
        self.assertIsInstance(result.commodities_matched, list)
        self.assertIsInstance(result.notes, list)
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

    @patch("detect.engine.OpenFoodFactsClient")
    def test_scan_barcode_data_confidence(self, MockOFFClient):
        """Test data_confidence maps correctly from tier_used."""
        mock_client = MagicMock()
        mock_client.lookup.return_value = {
            "barcode": "0001600014588",
            "product_name": "Cheerios",
            "brand": "General Mills",
            "categories": ["breakfast-cereals"],
            "ingredients_text": "Whole grain oats",
            "ingredients": [
                {"name": "whole grain oats", "text": "whole grain oats"},
            ],
            "source": "OpenFoodFacts",
        }
        MockOFFClient.return_value = mock_client

        engine = DetectionEngine(self.tmp.name)
        engine._off_client = mock_client

        # Seed data for tier 1 match
        engine._conn.execute(
            "INSERT INTO product_tests "
            "(source_name, source_url, report_label, published_date, data_year, "
            "food_category, raw_category, contaminant, product_name, measured_ppb, "
            "below_detection, is_grf_certified, confidence, dedup_key) "
            "VALUES ('FDA', 'https://example.com', 'FDA 2023', '2023-01-01', 2023, "
            "'oats', 'Oats', 'glyphosate', 'Cheerios', 730.0, "
            "0, 0, 'high', 'test-scan-cheerios')"
        )
        engine._conn.commit()

        result = engine.scan_barcode("0001600014588")

        self.assertIsNotNone(result)
        self.assertEqual(result.tier_used, "product")
        self.assertEqual(result.data_confidence, "high")
        engine.close()

    def test_biomonitoring(self):
        """Test biomonitoring returns NHANES data."""
        engine = DetectionEngine(self.tmp.name)
        results = engine.biomonitoring(analyte="Glyphosate")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].analyte, "Glyphosate")
        self.assertEqual(results[0].cycle, "2017-2018")
        self.assertAlmostEqual(results[0].detection_rate, 0.825)
        engine.close()

    def test_biomonitoring_all(self):
        """Test biomonitoring returns all data when no filter."""
        engine = DetectionEngine(self.tmp.name)
        results = engine.biomonitoring()
        self.assertGreaterEqual(len(results), 1)
        engine.close()

    def test_scan_all_contaminants(self):
        """Test multi-contaminant scan returns report."""
        engine = DetectionEngine(self.tmp.name)
        report = engine.scan_all_contaminants("oats")
        self.assertIsNotNone(report)
        self.assertEqual(report.food_category, "oats")
        # Should find at least the seeded glyphosate and lead
        self.assertGreaterEqual(report.total_detected, 2)
        self.assertIsInstance(report.contaminants, list)
        # Each contaminant should have required fields
        for c in report.contaminants:
            self.assertIsNotNone(c.contaminant)
            self.assertIsNotNone(c.risk_level)
            self.assertIn(c.risk_level, ["none", "low", "medium", "high", "unknown"])
        engine.close()

    def test_mrl_based_risk_scoring(self):
        """Test that risk scoring uses MRL data when available."""
        engine = DetectionEngine(self.tmp.name)

        # oats/glyphosate: max_ppb=1200, tolerance_ppb=30000 → 4% → low
        result = engine.food_risk("oats", "glyphosate")
        self.assertIsNotNone(result)
        self.assertEqual(result.risk_level, "low")

        # oats/lead: max_ppb=12.0, tolerance_ppb=100 → 12% → low
        result = engine.food_risk("oats", "lead")
        self.assertIsNotNone(result)
        self.assertEqual(result.risk_level, "low")

        engine.close()

    def test_consumption_tier_loaded(self):
        """Test that commodities have consumption_tier."""
        engine = DetectionEngine(self.tmp.name)
        commodities = engine.list_commodities()
        self.assertEqual(len(commodities), 2)
        strawberry = [c for c in commodities if c.commodity_slug == "strawberry"][0]
        oats = [c for c in commodities if c.commodity_slug == "oats"][0]
        # These would need consumption_tier in CommodityDetail model
        # For now, just verify they exist
        self.assertEqual(strawberry.display_name, "Strawberry")
        self.assertEqual(oats.display_name, "Oats")
        engine.close()


if __name__ == "__main__":
    unittest.main()
