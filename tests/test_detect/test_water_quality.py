import sqlite3
import unittest

from tests.test_detect.conftest import create_test_db, seed_water_data
from detect.water_quality import WaterQualityQuery
from detect.models import WaterQualityResult


class TestWaterQualityQuery(unittest.TestCase):
    def setUp(self):
        self.conn = create_test_db()
        seed_water_data(self.conn)
        self.query = WaterQualityQuery(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_all_water_data(self):
        results = self.query.execute()
        self.assertIsInstance(results, list)
        self.assertGreaterEqual(len(results), 2)

    def test_filter_by_state(self):
        results = self.query.execute(state="California")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].state, "California")

    def test_filter_by_contaminant(self):
        results = self.query.execute(contaminant="lead")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].contaminant, "lead")
        self.assertAlmostEqual(results[0].avg_ppb, 8.0)

    def test_filter_by_state_and_contaminant(self):
        results = self.query.execute(state="California", contaminant="glyphosate")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].contaminant, "glyphosate")
        self.assertAlmostEqual(results[0].max_ppb, 500.0)

    def test_epa_mcl_populated(self):
        results = self.query.execute(state="California", contaminant="glyphosate")
        self.assertIsNotNone(results[0].epa_mcl_ppb)
        self.assertAlmostEqual(results[0].epa_mcl_ppb, 700.0)

    def test_no_results(self):
        results = self.query.execute(state="NonexistentState")
        self.assertEqual(results, [])

    def test_invalid_contaminant(self):
        with self.assertRaises(ValueError):
            self.query.execute(contaminant="dioxin")

    def test_filter_by_water_type(self):
        results = self.query.execute(water_type="surface")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].water_type, "surface")


if __name__ == "__main__":
    unittest.main()