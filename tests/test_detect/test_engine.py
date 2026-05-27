import os
import sqlite3
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()