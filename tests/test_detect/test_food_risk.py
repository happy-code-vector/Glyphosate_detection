import sqlite3
import unittest

from tests.test_detect.conftest import create_test_db, seed_food_data
from detect.food_risk import FoodRiskQuery
from detect.models import FoodRiskResult


class TestFoodRiskQuery(unittest.TestCase):
    def setUp(self):
        self.conn = create_test_db()
        seed_food_data(self.conn)
        self.query = FoodRiskQuery(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_food_risk_single_contaminant(self):
        result = self.query.execute("oats", contaminant="glyphosate")
        self.assertIsInstance(result, FoodRiskResult)
        self.assertEqual(result.food_category, "oats")
        self.assertEqual(result.contaminant, "glyphosate")
        self.assertEqual(result.best_source, "FDA")
        self.assertEqual(result.data_year, 2024)
        self.assertAlmostEqual(result.detection_rate, 0.8)
        self.assertEqual(result.max_ppb, 1200.0)
        self.assertEqual(result.risk_level, "high")
        self.assertGreaterEqual(result.total_products_tested, 2)

    def test_food_risk_all_contaminants(self):
        results = self.query.execute("oats")
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 2)
        contaminants = {r.contaminant for r in results}
        self.assertEqual(contaminants, {"glyphosate", "lead"})

    def test_food_risk_with_regulatory_comparison(self):
        result = self.query.execute("oats", contaminant="glyphosate")
        self.assertIsInstance(result.regulatory_comparison, list)
        self.assertGreaterEqual(len(result.regulatory_comparison), 1)
        entry = result.regulatory_comparison[0]
        self.assertEqual(entry.source, "EPA_40CFR180.364")
        self.assertEqual(entry.tolerance_ppb, 30000.0)

    def test_food_risk_not_found(self):
        result = self.query.execute("nonexistent", contaminant="glyphosate")
        self.assertIsNone(result)

    def test_food_risk_not_found_all_contaminants(self):
        results = self.query.execute("nonexistent")
        self.assertEqual(results, [])

    def test_invalid_contaminant(self):
        with self.assertRaises(ValueError):
            self.query.execute("oats", contaminant="invalid")


if __name__ == "__main__":
    unittest.main()