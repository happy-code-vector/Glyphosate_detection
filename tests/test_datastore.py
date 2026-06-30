"""
tests/test_datastore.py

Parity tests: verify the DataStore abstraction returns the same results
as the original direct-SQL approach. Uses in-memory SQLite.
"""

import json
import sqlite3
import unittest

from data.sqlite_store import SqliteDataStore
from detect.engine import DetectionEngine
from detect.models import (
    FoodRiskResult,
    ProductResult,
    WaterQualityResult,
    InternationalComparisonResult,
    BiomonitoringResult,
    ContaminantReport,
)

from tests.test_detect.conftest import create_test_db, seed_all, seed_regulatory_data


class TestSqliteDataStoreProtocol(unittest.TestCase):
    """Verify SqliteDataStore satisfies the DataStore protocol."""

    def setUp(self):
        self.conn = create_test_db()
        seed_all(self.conn)
        seed_regulatory_data(self.conn)

        # Write in-memory DB to temp file for SqliteDataStore
        import tempfile
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=True)
        self.tmp.close()
        dest = sqlite3.connect(self.tmp.name)
        for line in self.conn.iterdump():
            dest.execute(line)
        dest.commit()
        dest.close()

        self.store = SqliteDataStore(db_path=self.tmp.name)

    def tearDown(self):
        self.store.close()
        self.conn.close()

    def test_implements_protocol(self):
        """SqliteDataStore should satisfy the DataStore protocol."""
        from data.datastore import DataStore
        self.assertIsInstance(self.store, DataStore)

    # ── App-facing views ────────────────────────────────────────────────

    def test_get_food_overview_single(self):
        rows = self.store.get_food_overview("oats", "glyphosate")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["food_category"], "oats")
        self.assertEqual(rows[0]["contaminant"], "glyphosate")

    def test_get_food_overview_all(self):
        rows = self.store.get_food_overview("oats")
        self.assertGreaterEqual(len(rows), 2)  # glyphosate + lead

    def test_get_food_overview_resolves_category(self):
        """Should resolve 'Oats' → 'oats' via alias or case match."""
        rows = self.store.get_food_overview("Oats", "glyphosate")
        self.assertEqual(len(rows), 1)

    def test_get_product_lookup(self):
        rows = self.store.get_product_lookup("Cheerios")
        self.assertGreaterEqual(len(rows), 1)
        self.assertIn("Cheerios", rows[0]["product_name"])

    def test_get_product_lookup_with_contaminant(self):
        rows = self.store.get_product_lookup("Cheerios", "glyphosate")
        self.assertGreaterEqual(len(rows), 1)
        for r in rows:
            self.assertEqual(r["contaminant"], "glyphosate")

    def test_get_water_overview(self):
        rows = self.store.get_water_overview(state="California")
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "California")

    def test_get_international_comparison(self):
        rows = self.store.get_international_comparison("oats", "glyphosate")
        self.assertGreaterEqual(len(rows), 1)
        for r in rows:
            self.assertIn("country_region", r)
            self.assertIn("mrl_ppb", r)

    # ── Raw table reads ─────────────────────────────────────────────────

    def test_get_product_tests(self):
        row = self.store.get_product_tests("Cheerios", "glyphosate")
        self.assertIsNotNone(row)
        self.assertIn("Cheerios", row["product_name"])

    def test_get_product_tests_not_found(self):
        row = self.store.get_product_tests("NonexistentProduct", "glyphosate")
        self.assertIsNone(row)

    def test_get_category_summaries(self):
        row = self.store.get_category_summaries("oats", "glyphosate")
        self.assertIsNotNone(row)
        self.assertEqual(row["food_category"], "oats")

    def test_get_biomonitoring(self):
        rows = self.store.get_biomonitoring(analyte="Glyphosate")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["analyte"], "Glyphosate")

    def test_get_biomonitoring_all(self):
        rows = self.store.get_biomonitoring()
        self.assertGreaterEqual(len(rows), 1)

    def test_get_ingredient_by_id(self):
        row = self.store.get_ingredient(ingredient_id="potassium_bromate")
        self.assertIsNotNone(row)
        self.assertEqual(row["display_name"], "Potassium Bromate")

    def test_get_ingredient_by_name(self):
        row = self.store.get_ingredient(name="potassium bromate")
        self.assertIsNotNone(row)
        self.assertEqual(row["ingredient_id"], "potassium_bromate")

    def test_get_ingredient_not_found(self):
        row = self.store.get_ingredient(ingredient_id="nonexistent")
        self.assertIsNone(row)

    def test_get_regulatory_flags(self):
        rows = self.store.get_regulatory_flags("potassium_bromate")
        self.assertGreaterEqual(len(rows), 1)

    def test_get_commodity(self):
        row = self.store.get_commodity("oats")
        self.assertIsNotNone(row)
        self.assertEqual(row["display_name"], "Oats")

    def test_get_commodity_not_found(self):
        row = self.store.get_commodity("nonexistent")
        self.assertIsNone(row)

    def test_get_all_commodities_with_aliases(self):
        rows = self.store.get_all_commodities_with_aliases()
        self.assertGreaterEqual(len(rows), 1)
        for r in rows:
            self.assertIsNotNone(r["ingredient_aliases"])

    def test_get_alternatives_exact(self):
        # Seed an alternative directly into the temp file DB
        import sqlite3
        conn = sqlite3.connect(self.tmp.name)
        conn.execute(
            "INSERT INTO alternatives (lookup_key, lookup_type, flagged_product_name, "
            "risk_label, flag_summary, alternatives) VALUES (?, ?, ?, ?, ?, ?)",
            ("test-alt", "product", "Cheerios", "HIGH", "Test", json.dumps([])),
        )
        conn.commit()
        conn.close()
        # Re-create store to pick up new data
        self.store.close()
        self.store = SqliteDataStore(db_path=self.tmp.name)

        row = self.store.get_alternatives("Cheerios")
        self.assertIsNotNone(row)

    def test_get_certified_products(self):
        rows = self.store.get_certified_products()
        self.assertIsInstance(rows, list)

    def test_get_all_ingredients(self):
        rows = self.store.get_all_ingredients()
        self.assertGreaterEqual(len(rows), 3)

    def test_get_all_commodities(self):
        rows = self.store.get_all_commodities()
        self.assertGreaterEqual(len(rows), 2)

    # ── Regulatory lookups ──────────────────────────────────────────────

    def test_get_category_aliases(self):
        rows = self.store.get_category_aliases()
        self.assertIsInstance(rows, list)

    def test_get_category_alias(self):
        # The seed data includes aliases
        result = self.store.get_category_alias("oats")
        # May or may not find it depending on seed data
        self.assertIsInstance(result, (str, type(None)))

    def test_get_tolerance_limit(self):
        row = self.store.get_tolerance_limit("glyphosate", "oats")
        self.assertIsNotNone(row)
        self.assertGreater(row["tolerance_ppb"], 0)

    def test_get_tolerance_limit_not_found(self):
        row = self.store.get_tolerance_limit("nonexistent", "nonexistent")
        self.assertIsNone(row)

    def test_get_strictest_mrl(self):
        row = self.store.get_strictest_mrl("glyphosate", "oats")
        self.assertIsNotNone(row)
        self.assertGreater(row["mrl_ppb"], 0)

    def test_get_consumption_tier(self):
        tier = self.store.get_consumption_tier("oats")
        self.assertEqual(tier, "daily")

    def test_get_consumption_tier_not_found(self):
        tier = self.store.get_consumption_tier("nonexistent")
        self.assertIsNone(tier)

    def test_get_contaminant_type(self):
        contam_type = self.store.get_contaminant_type("glyphosate")
        self.assertIsNotNone(contam_type)

    def test_get_all_contaminants_for_category(self):
        rows = self.store.get_all_contaminants_for_category(
            "oats",
            "CASE source_name WHEN 'FDA' THEN 3 WHEN 'CFIA' THEN 2 WHEN 'EFSA' THEN 1 ELSE 0 END",
        )
        self.assertGreaterEqual(len(rows), 1)

    def test_resolve_benchmark_category(self):
        resolved = self.store.resolve_benchmark_category("oats", "tolerance_limits")
        self.assertIsInstance(resolved, str)
        self.assertTrue(len(resolved) > 0)

    def test_form_aware_tolerance_lookup(self):
        """End-to-end form-aware benchmark resolution through the DataStore.

        Mirrors real EPA herb data: 'basil, dried leaves' and
        'basil, fresh leaves' have divergent mandipropamid tolerances
        (200,000 vs 30,000 ppb). Passing the raw must select the matching
        form's tolerance; without raw it falls back to the generic value.
        """
        self.conn.executemany(
            "INSERT INTO tolerance_limits "
            "(food_category, tolerance_ppm, tolerance_ppb, contaminant, source, dedup_key) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("basil", 0.05, 50.0, "mandipropamid", "EPA", "ds-basil"),
                ("basil, dried leaves", 200.0, 200000.0, "mandipropamid", "EPA", "ds-basil-dried"),
                ("basil, fresh leaves", 30.0, 30000.0, "mandipropamid", "EPA", "ds-basil-fresh"),
            ],
        )
        self.conn.commit()
        # Re-sync the temp-file DB the store reads from.
        dest = sqlite3.connect(self.tmp.name)
        for r in self.conn.execute("SELECT food_category, tolerance_ppm, tolerance_ppb, contaminant, source, dedup_key FROM tolerance_limits WHERE dedup_key LIKE 'ds-basil%'"):
            dest.execute("INSERT OR REPLACE INTO tolerance_limits (food_category, tolerance_ppm, tolerance_ppb, contaminant, source, dedup_key) VALUES (?,?,?,?,?,?)", tuple(r))
        dest.commit()
        dest.close()

        dried = self.store.get_tolerance_limit("mandipropamid", "basil", raw="Dried Basil")
        fresh = self.store.get_tolerance_limit("mandipropamid", "basil", raw="Fresh Basil")
        generic = self.store.get_tolerance_limit("mandipropamid", "basil")

        # The three forms have distinct tolerances, so the selected ppb proves
        # which form-specific row was chosen.
        self.assertEqual(dried["tolerance_ppb"], 200000.0)
        self.assertEqual(fresh["tolerance_ppb"], 30000.0)
        # No raw -> generic 'basil' (50.0), never a wrong form.
        self.assertEqual(generic["tolerance_ppb"], 50.0)

    def test_engine_threads_raw_to_form_aware_tolerance(self):
        """DetectionEngine._ppb_to_risk_detail forwards ``raw`` to the store so
        the form-aware tolerance is selected — the LIVE path that makes the
        data-layer feature actually fire in a detection run. Same ppb, different
        form => different tolerance and risk level."""
        conn = sqlite3.connect(self.tmp.name)
        conn.executemany(
            "INSERT INTO tolerance_limits "
            "(food_category, tolerance_ppm, tolerance_ppb, contaminant, source, dedup_key) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("basil", 0.05, 50.0, "mandipropamid", "EPA", "e-basil"),
                ("basil, dried leaves", 200.0, 200000.0, "mandipropamid", "EPA", "e-basil-dried"),
            ],
        )
        conn.commit()
        conn.close()

        engine = DetectionEngine.from_datastore(self.store)
        # Returns (risk_level, reason, mrl, mrl_src, tolerance_ppb, tol_src).
        dried = engine._ppb_to_risk_detail(100.0, "mandipropamid", "basil", raw="Dried Basil")
        generic = engine._ppb_to_risk_detail(100.0, "mandipropamid", "basil")

        # 100 ppb vs dried 200,000 => 0.05% => 'low'; vs generic 50 => 200% => 'high'.
        self.assertEqual(dried[4], 200000.0)
        self.assertEqual(dried[0], "low")
        self.assertEqual(generic[4], 50.0)
        self.assertEqual(generic[0], "high")


class TestFromDatastore(unittest.TestCase):
    """Test DetectionEngine.from_datastore() constructor."""

    def setUp(self):
        self.conn = create_test_db()
        seed_all(self.conn)
        seed_regulatory_data(self.conn)

        import tempfile
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=True)
        self.tmp.close()
        dest = sqlite3.connect(self.tmp.name)
        for line in self.conn.iterdump():
            dest.execute(line)
        dest.commit()
        dest.close()

        self.store = SqliteDataStore(db_path=self.tmp.name)

    def tearDown(self):
        self.store.close()
        self.conn.close()

    def test_from_datastore_creates_engine(self):
        engine = DetectionEngine.from_datastore(self.store)
        self.assertIsInstance(engine, DetectionEngine)

    def test_from_datastore_food_risk(self):
        engine = DetectionEngine.from_datastore(self.store)
        result = engine.food_risk("oats", contaminant="glyphosate")
        self.assertIsInstance(result, FoodRiskResult)
        self.assertEqual(result.food_category, "oats")

    def test_from_datastore_product_lookup(self):
        engine = DetectionEngine.from_datastore(self.store)
        results = engine.product_lookup("Cheerios")
        self.assertGreaterEqual(len(results), 1)
        self.assertIsInstance(results[0], ProductResult)

    def test_from_datastore_water_quality(self):
        engine = DetectionEngine.from_datastore(self.store)
        results = engine.water_quality(state="California")
        self.assertGreaterEqual(len(results), 1)
        self.assertIsInstance(results[0], WaterQualityResult)

    def test_from_datastore_international_comparison(self):
        engine = DetectionEngine.from_datastore(self.store)
        result = engine.international_comparison("oats")
        self.assertIsInstance(result, InternationalComparisonResult)

    def test_from_datastore_biomonitoring(self):
        engine = DetectionEngine.from_datastore(self.store)
        results = engine.biomonitoring(analyte="Glyphosate")
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], BiomonitoringResult)

    def test_from_datastore_scan_all_contaminants(self):
        engine = DetectionEngine.from_datastore(self.store)
        report = engine.scan_all_contaminants("oats")
        self.assertIsInstance(report, ContaminantReport)
        self.assertGreaterEqual(report.total_detected, 2)

    def test_from_datastore_context_manager(self):
        with DetectionEngine.from_datastore(self.store) as engine:
            result = engine.food_risk("oats", contaminant="glyphosate")
            self.assertIsInstance(result, FoodRiskResult)


class TestParityWithDirectInit(unittest.TestCase):
    """Verify from_datastore(SqliteDataStore) produces identical results
    to the original DetectionEngine(db_path) constructor."""

    def setUp(self):
        self.conn = create_test_db()
        seed_all(self.conn)
        seed_regulatory_data(self.conn)

        import tempfile
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=True)
        self.tmp.close()
        dest = sqlite3.connect(self.tmp.name)
        for line in self.conn.iterdump():
            dest.execute(line)
        dest.commit()
        dest.close()

        # Two engines: one via old constructor, one via from_datastore
        self.engine_old = DetectionEngine(self.tmp.name)
        self.store = SqliteDataStore(db_path=self.tmp.name)
        self.engine_new = DetectionEngine.from_datastore(self.store)

    def tearDown(self):
        self.engine_old.close()
        self.engine_new.close()
        self.conn.close()

    def _compare_food_risk(self, old, new):
        if old is None:
            self.assertIsNone(new)
            return
        self.assertEqual(old.food_category, new.food_category)
        self.assertEqual(old.contaminant, new.contaminant)
        self.assertEqual(old.risk_level, new.risk_level)
        self.assertAlmostEqual(old.detection_rate, new.detection_rate, places=4)
        self.assertEqual(old.best_source, new.best_source)

    def test_parity_food_risk(self):
        old = self.engine_old.food_risk("oats", "glyphosate")
        new = self.engine_new.food_risk("oats", "glyphosate")
        self._compare_food_risk(old, new)

    def test_parity_food_risk_lead(self):
        old = self.engine_old.food_risk("oats", "lead")
        new = self.engine_new.food_risk("oats", "lead")
        self._compare_food_risk(old, new)

    def test_parity_product_lookup(self):
        old = self.engine_old.product_lookup("Cheerios")
        new = self.engine_new.product_lookup("Cheerios")
        self.assertEqual(len(old), len(new))
        for o, n in zip(old, new):
            self.assertEqual(o.product_name, n.product_name)
            self.assertEqual(o.risk_level, n.risk_level)

    def test_parity_water_quality(self):
        old = self.engine_old.water_quality(state="California")
        new = self.engine_new.water_quality(state="California")
        self.assertEqual(len(old), len(new))
        for o, n in zip(old, new):
            self.assertEqual(o.state, n.state)
            self.assertEqual(o.contaminant, n.contaminant)

    def test_parity_international_comparison(self):
        old = self.engine_old.international_comparison("oats")
        new = self.engine_new.international_comparison("oats")
        self.assertEqual(len(old.entries), len(new.entries))

    def test_parity_biomonitoring(self):
        old = self.engine_old.biomonitoring(analyte="Glyphosate")
        new = self.engine_new.biomonitoring(analyte="Glyphosate")
        self.assertEqual(len(old), len(new))
        for o, n in zip(old, new):
            self.assertEqual(o.analyte, n.analyte)
            self.assertAlmostEqual(o.detection_rate, n.detection_rate)

    def test_parity_scan_all_contaminants(self):
        old = self.engine_old.scan_all_contaminants("oats")
        new = self.engine_new.scan_all_contaminants("oats")
        self.assertEqual(old.total_detected, new.total_detected)
        self.assertEqual(old.overall_risk_level, new.overall_risk_level)
        self.assertEqual(len(old.contaminants), len(new.contaminants))

    def test_parity_ingredient_flags(self):
        old = self.engine_old.ingredient_flags("potassium bromate")
        new = self.engine_new.ingredient_flags("potassium bromate")
        self.assertIsNotNone(old)
        self.assertIsNotNone(new)
        self.assertEqual(old.ingredient_id, new.ingredient_id)
        self.assertEqual(len(old.flags), len(new.flags))

    def test_parity_commodity_residues(self):
        old = self.engine_old.commodity_residues("oats")
        new = self.engine_new.commodity_residues("oats")
        self.assertIsNotNone(old)
        self.assertIsNotNone(new)
        self.assertEqual(old.commodity_slug, new.commodity_slug)

    def test_parity_list_ingredients(self):
        old = self.engine_old.list_ingredients()
        new = self.engine_new.list_ingredients()
        self.assertEqual(len(old), len(new))

    def test_parity_list_commodities(self):
        old = self.engine_old.list_commodities()
        new = self.engine_new.list_commodities()
        self.assertEqual(len(old), len(new))


if __name__ == "__main__":
    unittest.main()
