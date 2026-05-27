import sqlite3
import unittest

from tests.test_detect.conftest import create_test_db, seed_food_data
from detect.comparison import ComparisonQuery
from detect.models import InternationalComparisonResult


class TestComparisonQuery(unittest.TestCase):
    def setUp(self):
        self.conn = create_test_db()
        seed_food_data(self.conn)
        self.query = ComparisonQuery(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_comparison_glyphosate(self):
        result = self.query.execute("oats", contaminant="glyphosate")
        self.assertIsInstance(result, InternationalComparisonResult)
        self.assertEqual(result.food_category, "oats")
        self.assertEqual(result.contaminant, "glyphosate")
        self.assertGreaterEqual(len(result.entries), 2)
        countries = {e.country_region for e in result.entries}
        self.assertIn("EU", countries)
        self.assertIn("Canada", countries)

    def test_comparison_entry_values(self):
        result = self.query.execute("oats", contaminant="glyphosate")
        eu_entry = [e for e in result.entries if e.country_region == "EU"][0]
        self.assertAlmostEqual(eu_entry.mrl_ppb, 20000.0)
        self.assertEqual(eu_entry.regulatory_body, "EFSA")

    def test_comparison_not_found(self):
        result = self.query.execute("nonexistent", contaminant="glyphosate")
        self.assertEqual(len(result.entries), 0)

    def test_invalid_contaminant(self):
        with self.assertRaises(ValueError):
            self.query.execute("oats", contaminant="dioxin")


if __name__ == "__main__":
    unittest.main()