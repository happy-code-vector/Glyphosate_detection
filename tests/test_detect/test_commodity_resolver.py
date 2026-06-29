"""
Tests for the shared commodity resolver (data.commodity_resolver).

Covers: exact/variant matching, the unified alias vocabulary (category_aliases
UNION commodities.ingredient_aliases), and the first-segment prefix rule that
replaces the old longest-substring matcher.
"""

import json
import unittest

from tests.test_detect.conftest import create_test_db
from data.commodity_resolver import (
    resolve_commodity,
    load_index,
    invalidate_index,
)


class TestResolveCommodity(unittest.TestCase):
    def setUp(self):
        self.conn = create_test_db()
        self.conn.executemany(
            "INSERT INTO category_aliases (alias, canonical_key) VALUES (?, ?)",
            [
                ("apple", "apple"), ("apples", "apple"),
                ("oats", "oats"), ("oat", "oats"),
                ("beans", "beans"), ("bean", "beans"),
                ("ackee", "ackee"),
                ("dairy", "dairy"), ("milk", "dairy"), ("butter", "dairy"),
            ],
        )
        self.conn.execute(
            "INSERT INTO commodities (commodity_slug, display_name, ingredient_aliases, "
            "dirty_dozen, consumption_tier) VALUES (?, ?, ?, 0, 'weekly')",
            ("apple", "Apple", json.dumps(["apple sauce", "apple juice"])),
        )
        self.conn.commit()
        load_index(self.conn)

    def tearDown(self):
        self.conn.close()
        invalidate_index()

    def test_exact(self):
        self.assertEqual(resolve_commodity("apple", self.conn), "apple")

    def test_case_and_punct_normalization(self):
        self.assertEqual(resolve_commodity("  Apple ", self.conn), "apple")
        self.assertEqual(resolve_commodity("Apple;", self.conn), "apple")

    def test_singular_plural_variant(self):
        self.assertEqual(resolve_commodity("Apples", self.conn), "apple")
        self.assertEqual(resolve_commodity("oat", self.conn), "oats")

    def test_ingredient_alias_vocab_shared(self):
        # "apple sauce" comes from commodities.ingredient_aliases,
        # not category_aliases — proves the two vocabularies are unified.
        self.assertEqual(resolve_commodity("apple sauce", self.conn), "apple")

    def test_group_string_first_segment(self):
        self.assertEqual(
            resolve_commodity("Apple, Juice - Apple", self.conn), "apple")
        self.assertEqual(
            resolve_commodity("Bean, Bean - Black, Bean - Kidney", self.conn),
            "beans",
        )

    def test_group_string_leads_with_primary(self):
        self.assertEqual(
            resolve_commodity(
                "APPLE, JAM, JELLY, PRESERVES, MARMALADE, BUTTER AND CANDIED",
                self.conn),
            "apple",
        )

    def test_miss_returns_none(self):
        self.assertIsNone(resolve_commodity("some unknown thing", self.conn))

    def test_empty_input(self):
        self.assertIsNone(resolve_commodity("", self.conn))
        self.assertIsNone(resolve_commodity(None, self.conn))


class TestDairyFalsePositiveRegression(unittest.TestCase):
    """Issue C: fruit/jam group strings carrying a dairy token must NOT collapse
    to 'dairy'. The first-segment prefix rule fixes this without per-string
    curation, while genuine dairy groups still resolve to dairy."""

    def setUp(self):
        self.conn = create_test_db()
        self.conn.executemany(
            "INSERT INTO category_aliases (alias, canonical_key) VALUES (?, ?)",
            [
                ("apple", "apple"), ("ackee", "ackee"), ("citrus", "citrus"),
                ("berries", "berries"),
                ("dairy", "dairy"), ("milk", "dairy"), ("butter", "dairy"),
                ("cream", "dairy"), ("cheese", "dairy"),
            ],
        )
        self.conn.commit()
        load_index(self.conn)

    def tearDown(self):
        self.conn.close()
        invalidate_index()

    def test_apple_jam_butter_is_apple(self):
        self.assertEqual(
            resolve_commodity(
                "APPLE, JAM, JELLY, PRESERVES, MARMALADE, BUTTER AND CANDIED",
                self.conn),
            "apple",
        )

    def test_ackees_juice_milk_creme_is_ackee(self):
        self.assertEqual(
            resolve_commodity(
                "Ackees, Juice, Milk, Creme, Drink or Nectar, Sub/Tropical Fruit",
                self.conn),
            "ackee",
        )

    def test_astragalus_milk_vetch_is_unknown(self):
        # buried 'milk' is not the head token -> no match -> None (triage)
        self.assertIsNone(
            resolve_commodity("ASTRAGALUS (MILK VETCH ROOT)", self.conn))

    def test_genuine_dairy_group_still_dairy(self):
        self.assertEqual(
            resolve_commodity("Butter, Cheese, Milk", self.conn), "dairy")


if __name__ == "__main__":
    unittest.main()
