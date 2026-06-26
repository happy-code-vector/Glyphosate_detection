"""
Tests for the PLU (Price Look-Up) feature: lookup_plu engine method,
get_plu / get_plu_by_commodity DataStore methods, and the pdp_covered /
Addendum-B-2.2 honest-note behavior.
"""

import json
import os
import sqlite3
import tempfile
import unittest

from tests.test_detect.conftest import get_schema_sql
from detect.engine import DetectionEngine
from detect.models import PLUResult


def _residues(*items):
    """Build a commodities.residues JSON array like enrich_commodities produces."""
    return json.dumps([
        {
            "pesticide": name,
            "detection_rate": det,
            "avg_ppb": avg,
            "max_ppb": mx,
            "samples_total": 100,
            "samples_detected": int(100 * det),
            "data_year": year,
        }
        for (name, det, avg, mx, year) in items
    ])


def _seed(conn):
    """Commodities (with residues JSON + pdp_covered) + plu_codes rows."""
    # commodity: current PDP cycle, has residues -> happy path (no note)
    conn.execute(
        "INSERT INTO commodities "
        "(commodity_slug, display_name, ingredient_aliases, dirty_dozen, "
        "consumption_tier, residues, pdp_year_latest, pdp_covered) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("oats", "Oats", json.dumps(["oats", "oat flour"]), 0, "daily",
         _residues(("glyphosate", 0.80, 250.0, 1200.0, 2024)), 2024, 1),
    )
    # commodity: stale PDP data, has residues, pdp_covered=0 -> stale note
    conn.execute(
        "INSERT INTO commodities "
        "(commodity_slug, display_name, ingredient_aliases, dirty_dozen, "
        "consumption_tier, residues, pdp_year_latest, pdp_covered) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("strawberry", "Strawberry", json.dumps(["strawberries"]), 1, "weekly",
         _residues(("captan", 0.50, 80.0, 400.0, 2014)), 2014, 0),
    )
    # commodity: mapped but no residue data -> "no residue data" note
    conn.execute(
        "INSERT INTO commodities "
        "(commodity_slug, display_name, ingredient_aliases, dirty_dozen, "
        "consumption_tier, residues, pdp_covered) "
        "VALUES (?, ?, ?, ?, ?, NULL, ?)",
        ("apple", "Apple", json.dumps(["apples"]), 1, "weekly", 1),
    )

    # PLU rows
    def _plu(plu, slug, display, variety=None, size=None):
        conn.execute(
            "INSERT INTO plu_codes "
            "(plu, commodity_slug, commodity_display, variety, size, category, "
            "source_file, dedup_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (plu, slug, display, variety, size, "Fruits", "test", f"test-plu-{plu}"),
        )

    _plu("3000", "oats", "Oats", variety="Rolled", size="All Sizes")
    _plu("4001", "strawberry", "Strawberry")
    _plu("4080", "apple", "Apple")
    _plu("3042", None, "Mangosteen")  # unmapped exotic
    conn.commit()


def _create_engine_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(get_schema_sql())
    _seed(conn)
    conn.close()
    return path


class TestLookupPlu(unittest.TestCase):
    """Tests for DetectionEngine.lookup_plu."""

    def setUp(self):
        self.tmp_path = _create_engine_db()
        self.engine = DetectionEngine(self.tmp_path)

    def tearDown(self):
        self.engine.close()
        try:
            os.unlink(self.tmp_path)
        except PermissionError:
            pass

    def test_mapped_current_pdp_no_note(self):
        """Mapped PLU, current PDP cycle, has residues -> no caveat note."""
        result = self.engine.lookup_plu("3000")
        self.assertIsInstance(result, PLUResult)
        self.assertEqual(result.plu, "3000")
        self.assertEqual(result.commodity_display, "Oats")
        self.assertEqual(result.variety, "Rolled")
        self.assertIsNotNone(result.commodity)
        self.assertEqual(result.commodity.commodity_slug, "oats")
        self.assertGreaterEqual(len(result.commodity.residues), 1)
        self.assertTrue(result.pdp_covered)
        self.assertIsNone(result.notes)  # current data -> honest, no caveat

    def test_mapped_stale_pdp_note(self):
        """Mapped PLU with stale PDP data (pdp_covered=0) -> Addendum B 2.2 note."""
        result = self.engine.lookup_plu("4001")
        self.assertIsNotNone(result)
        self.assertEqual(result.commodity.commodity_slug, "strawberry")
        self.assertFalse(result.pdp_covered)
        self.assertGreaterEqual(len(result.commodity.residues), 1)
        self.assertIsNotNone(result.notes)
        self.assertIn("no longer tests", result.notes.lower())

    def test_mapped_no_residues_note(self):
        """Mapped PLU whose commodity has no PDP residue data -> 'no data' note."""
        result = self.engine.lookup_plu("4080")
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.commodity)
        self.assertEqual(result.commodity.commodity_slug, "apple")
        self.assertEqual(len(result.commodity.residues), 0)
        self.assertEqual(
            result.notes,
            "No USDA PDP residue data is available for this commodity.",
        )

    def test_unmapped_exotic(self):
        """PLU for exotic produce (no slug) -> commodity None, no note."""
        result = self.engine.lookup_plu("3042")
        self.assertIsInstance(result, PLUResult)
        self.assertEqual(result.commodity_display, "Mangosteen")
        self.assertIsNone(result.commodity)
        self.assertFalse(result.pdp_covered)
        self.assertIsNone(result.notes)

    def test_unknown_plu_returns_none(self):
        """Unknown PLU code -> None."""
        self.assertIsNone(self.engine.lookup_plu("99999"))

    def test_get_plu_by_commodity(self):
        """DataStore.get_plu_by_commodity returns PLUs for a slug."""
        rows = self.engine._store.get_plu_by_commodity("oats")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["plu"], "3000")
        self.assertEqual(rows[0]["commodity_slug"], "oats")

        # unmapped slug / empty result
        self.assertEqual(self.engine._store.get_plu_by_commodity("oats_unknown"), [])


if __name__ == "__main__":
    unittest.main()
