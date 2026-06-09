import sqlite3
import unittest

from tests.test_detect.conftest import create_test_db, seed_food_data
from detect.product_lookup import ProductLookupQuery
from detect.models import ProductResult


class TestProductLookupQuery(unittest.TestCase):
    def setUp(self):
        self.conn = create_test_db()
        seed_food_data(self.conn)
        self.query = ProductLookupQuery(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_lookup_by_name(self):
        results = self.query.execute("Cheerios")
        self.assertIsInstance(results, list)
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].product_name, "Cheerios Original")
        self.assertEqual(results[0].contaminant, "glyphosate")
        self.assertAlmostEqual(results[0].measured_ppb, 730.0)

    def test_lookup_case_insensitive(self):
        results = self.query.execute("cheerios")
        self.assertGreaterEqual(len(results), 1)

    def test_lookup_with_contaminant_filter(self):
        results = self.query.execute("Cheerios", contaminant="lead")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].contaminant, "lead")
        self.assertAlmostEqual(results[0].measured_ppb, 5.2)

    def test_lookup_returns_multiple_products(self):
        results = self.query.execute("")
        self.assertGreaterEqual(len(results), 2)

    def test_lookup_no_results(self):
        results = self.query.execute("NonexistentProduct12345")
        self.assertEqual(results, [])

    def test_invalid_contaminant(self):
        results = self.query.execute("Cheerios", contaminant="arsenic")
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()