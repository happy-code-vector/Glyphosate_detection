"""
Tests for regulatory features: ingredient flags, commodities, new engine methods.
"""

import json
import os
import sqlite3
import tempfile
import unittest

from tests.test_detect.conftest import create_test_db, get_schema_sql, seed_regulatory_data
from detect.engine import DetectionEngine
from detect.models import (
    IngredientDetail,
    RegulatoryFlag,
    CommodityDetail,
    CommodityResidue,
)


def _create_engine_db():
    """Create a temporary SQLite DB file with regulatory seed data."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(get_schema_sql())
    seed_regulatory_data(conn)
    conn.close()
    return path


class TestIngredientFlags(unittest.TestCase):
    """Test ingredient_flags engine method."""

    def setUp(self):
        self.tmp_path = _create_engine_db()
        self.engine = DetectionEngine(self.tmp_path)

    def tearDown(self):
        self.engine.close()
        # Small delay for Windows file lock release
        try:
            os.unlink(self.tmp_path)
        except PermissionError:
            pass

    def test_ingredient_flags_by_id(self):
        """Look up ingredient by ID slug."""
        result = self.engine.ingredient_flags("potassium_bromate")
        self.assertIsNotNone(result)
        self.assertEqual(result.ingredient_id, "potassium_bromate")
        self.assertEqual(result.display_name, "Potassium Bromate")
        self.assertEqual(result.iarc_classification, "Group 2B")
        self.assertIsNone(result.ntp_classification)
        self.assertEqual(result.fda_status, "permitted")

    def test_ingredient_flags_by_name(self):
        """Look up ingredient by alias."""
        result = self.engine.ingredient_flags("bromated flour")
        self.assertIsNotNone(result)
        self.assertEqual(result.ingredient_id, "potassium_bromate")

    def test_ingredient_flags_with_flags(self):
        """Verify regulatory flags are loaded."""
        result = self.engine.ingredient_flags("potassium_bromate")
        self.assertIsNotNone(result)
        self.assertGreater(len(result.flags), 0)
        self.assertEqual(result.flags[0].jurisdiction, "EU")
        self.assertEqual(result.flags[0].flag_type, "eu_banned")

    def test_ingredient_flags_not_found(self):
        """Returns None for unknown ingredient."""
        result = self.engine.ingredient_flags("nonexistent_ingredient")
        self.assertIsNone(result)

    def test_ingredient_flags_bvo_banned(self):
        """BVO should show us_banned flag."""
        result = self.engine.ingredient_flags("bvo")
        self.assertIsNotNone(result)
        self.assertIn("us_banned", result.flag_types)
        self.assertEqual(result.fda_status, "banned_final_rule")


class TestCommodityResidues(unittest.TestCase):
    """Test commodity_residues engine method."""

    def setUp(self):
        self.tmp_path = _create_engine_db()
        self.engine = DetectionEngine(self.tmp_path)

    def tearDown(self):
        self.engine.close()
        try:
            os.unlink(self.tmp_path)
        except PermissionError:
            pass

    def test_commodity_found(self):
        """Look up existing commodity."""
        result = self.engine.commodity_residues("strawberry")
        self.assertIsNotNone(result)
        self.assertEqual(result.display_name, "Strawberry")
        self.assertTrue(result.high_residue)

    def test_commodity_aliases(self):
        """Verify ingredient aliases are loaded."""
        result = self.engine.commodity_residues("strawberry")
        self.assertIsNotNone(result)
        self.assertIn("strawberries", result.ingredient_aliases)
        self.assertIn("strawberry puree", result.ingredient_aliases)

    def test_commodity_not_found(self):
        """Returns None for unknown commodity."""
        result = self.engine.commodity_residues("nonexistent")
        self.assertIsNone(result)


class TestListIngredients(unittest.TestCase):
    """Test list_ingredients engine method."""

    def setUp(self):
        self.tmp_path = _create_engine_db()
        self.engine = DetectionEngine(self.tmp_path)

    def tearDown(self):
        self.engine.close()
        try:
            os.unlink(self.tmp_path)
        except PermissionError:
            pass

    def test_list_ingredients_returns_all(self):
        """Should return all seeded ingredients."""
        results = self.engine.list_ingredients()
        self.assertEqual(len(results), 3)
        ids = {r.ingredient_id for r in results}
        self.assertIn("potassium_bromate", ids)
        self.assertIn("red_40", ids)
        self.assertIn("bvo", ids)

    def test_list_ingredients_sorted(self):
        """Results should be sorted by ingredient_id."""
        results = self.engine.list_ingredients()
        ids = [r.ingredient_id for r in results]
        self.assertEqual(ids, sorted(ids))


class TestListCommodities(unittest.TestCase):
    """Test list_commodities engine method."""

    def setUp(self):
        self.tmp_path = _create_engine_db()
        self.engine = DetectionEngine(self.tmp_path)

    def tearDown(self):
        self.engine.close()
        try:
            os.unlink(self.tmp_path)
        except PermissionError:
            pass

    def test_list_commodities_returns_all(self):
        """Should return all seeded commodities."""
        results = self.engine.list_commodities()
        self.assertEqual(len(results), 2)
        slugs = {r.commodity_slug for r in results}
        self.assertIn("strawberry", slugs)
        self.assertIn("oats", slugs)

    def test_list_commodities_high_residue(self):
        """Strawberry should be flagged high_residue, oats should not."""
        results = self.engine.list_commodities()
        strawberry = [r for r in results if r.commodity_slug == "strawberry"][0]
        oats = [r for r in results if r.commodity_slug == "oats"][0]
        self.assertTrue(strawberry.high_residue)
        self.assertFalse(oats.high_residue)


class TestExpandedContaminants(unittest.TestCase):
    """Test that expanded contaminant registry works with detect modules."""

    def setUp(self):
        self.conn = create_test_db()

    def tearDown(self):
        self.conn.close()

    def test_new_contaminants_accepted(self):
        """New contaminants like mercury should be accepted by queries."""
        from detect.water_quality import WaterQualityQuery
        query = WaterQualityQuery(self.conn)
        # Should not raise ValueError for mercury
        results = query.execute(contaminant="mercury")
        self.assertIsInstance(results, list)

    def test_contaminant_registry_size(self):
        """Verify we have expanded beyond 3 contaminants."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "data"))
        from contaminants import CONTAMINANT_KEYS
        self.assertGreater(len(CONTAMINANT_KEYS), 10)

    def test_food_dyes_in_registry(self):
        """Food dyes should be in the contaminant registry."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "data"))
        from contaminants import CONTAMINANTS
        self.assertIn("red_40", CONTAMINANTS)
        self.assertIn("yellow_5", CONTAMINANTS)
        self.assertIn("bvo", CONTAMINANTS)
        self.assertIn("potassium_bromate", CONTAMINANTS)

    def test_heavy_metals_in_registry(self):
        """Heavy metals should be in the contaminant registry."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "data"))
        from contaminants import CONTAMINANTS
        self.assertIn("lead", CONTAMINANTS)
        self.assertIn("inorganic_arsenic", CONTAMINANTS)
        self.assertIn("cadmium", CONTAMINANTS)
        self.assertIn("mercury", CONTAMINANTS)

    def test_addendum_a_data(self):
        """Addendum A IARC/NTP data should be populated."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "data"))
        from contaminants import CONTAMINANTS
        # Per Addendum A
        self.assertEqual(CONTAMINANTS["mei_4"]["iarc_classification"], "Group 2B")
        self.assertEqual(CONTAMINANTS["acrylamide"]["iarc_classification"], "Group 2A")
        self.assertEqual(CONTAMINANTS["sodium_nitrite"]["iarc_classification"], "Group 1")
        self.assertEqual(CONTAMINANTS["potassium_bromate"]["iarc_classification"], "Group 2B")
        self.assertEqual(CONTAMINANTS["styrene"]["iarc_classification"], "Group 2A")


if __name__ == "__main__":
    unittest.main()
