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
    resolve_benchmark,
    extract_forms,
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
            "high_residue, consumption_tier) VALUES (?, ?, ?, 0, 'weekly')",
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


class TestLeadingFormQualifier(unittest.TestCase):
    """(D) Uniform form resolution: a leading dried/fresh/juice qualifier is
    stripped so the base commodity resolves. The form is preserved in the raw
    string for form-aware benchmark lookup (TestFormAwareBenchmark). This makes
    'dried basil' -> basil consistent with 'dried apples' -> apple."""

    def setUp(self):
        self.conn = create_test_db()
        self.conn.executemany(
            "INSERT INTO category_aliases (alias, canonical_key) VALUES (?, ?)",
            [
                ("basil", "basil"), ("dill", "dill"),
                ("apple", "apple"), ("apples", "apple"),
                ("plum", "plum"), ("plums", "plum"),
                ("water", "water"),  # decoy: must not be reached by form-strip
            ],
        )
        self.conn.commit()
        load_index(self.conn)

    def tearDown(self):
        self.conn.close()
        invalidate_index()

    def test_dried_fresh_juice_strip_to_base(self):
        self.assertEqual(resolve_commodity("Dried Basil", self.conn), "basil")
        self.assertEqual(resolve_commodity("Fresh Basil", self.conn), "basil")
        self.assertEqual(resolve_commodity("dill, dried", self.conn), "dill")
        self.assertEqual(resolve_commodity("dried plum", self.conn), "plum")
        self.assertEqual(resolve_commodity("Juice - Apple", self.conn), "apple")

    def test_strip_only_when_remainder_resolves(self):
        # 'fresh water bass': strip 'fresh' -> 'water bass' does NOT resolve,
        # and 'water' must not be guessed -> None (precision preserved).
        self.assertIsNone(resolve_commodity("fresh water bass", self.conn))
        # 'dried or paste' -> remainder 'or paste' resolves to nothing -> None
        self.assertIsNone(resolve_commodity("dried or paste", self.conn))

    def test_buried_form_token_not_stripped(self):
        # 'apple, dried' group-string: head is 'apple' (resolves directly);
        # the form strip is only a fallback, so the primary head match wins.
        self.assertEqual(resolve_commodity("Apple, Dried", self.conn), "apple")


class TestFormAwareBenchmark(unittest.TestCase):
    """(A) Form-aware benchmark resolution: tolerance_limits distinguishes
    'basil, dried leaves' from 'basil, fresh leaves' (real EPA data diverges up
    to 6.7x). Given the raw, resolve_benchmark must rank the form-specific key
    first; with no raw it returns the generic key (current behavior)."""

    def setUp(self):
        self.conn = create_test_db()
        self.conn.executemany(
            "INSERT INTO category_aliases (alias, canonical_key) VALUES (?, ?)",
            [("basil", "basil")],
        )
        # Mirrors real tolerance_limits rows for basil.
        self.conn.executemany(
            "INSERT INTO tolerance_limits "
            "(food_category, tolerance_ppm, tolerance_ppb, contaminant, source, dedup_key) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("basil", 0.05, 50.0, "mandipropamid", "EPA", "t-basil"),
                ("basil, dried leaves", 200.0, 200000.0, "mandipropamid", "EPA", "t-basil-dried"),
                ("basil, fresh leaves", 30.0, 30000.0, "mandipropamid", "EPA", "t-basil-fresh"),
            ],
        )
        self.conn.commit()
        load_index(self.conn)

    def tearDown(self):
        self.conn.close()
        invalidate_index()

    def test_extract_forms_whole_word(self):
        self.assertEqual(extract_forms("Dried Basil"), {"dried"})
        self.assertEqual(extract_forms("Fresh basil leaves"), {"fresh"})
        self.assertEqual(extract_forms("basil"), set())
        # 'refreshing' must not yield 'fresh' (whole-word match)
        self.assertEqual(extract_forms("refreshing drink"), set())

    def test_no_raw_returns_generic_first(self):
        ranked = resolve_benchmark("basil", self.conn)
        self.assertEqual(ranked[0], "basil")
        self.assertIn("basil, dried leaves", ranked)
        self.assertIn("basil, fresh leaves", ranked)

    def test_dried_raw_prefers_dried_form(self):
        ranked = resolve_benchmark("basil", self.conn, raw="Dried Basil")
        self.assertEqual(ranked[0], "basil, dried leaves")

    def test_fresh_raw_prefers_fresh_form(self):
        ranked = resolve_benchmark("basil", self.conn, raw="Fresh Basil")
        self.assertEqual(ranked[0], "basil, fresh leaves")

    def test_no_form_in_raw_falls_back_generic(self):
        # raw present but carries no form token -> generic, never a wrong form
        ranked = resolve_benchmark("basil", self.conn, raw="basil")
        self.assertEqual(ranked[0], "basil")

    def test_more_specific_form_wins_tie(self):
        # Both 'basil, dried' and 'basil, dried leaves' match raw 'Dried Basil';
        # the MORE specific form (longer suffix) must rank first so the tighter
        # tolerance is applied.
        self.conn.executemany(
            "INSERT INTO tolerance_limits "
            "(food_category, tolerance_ppm, tolerance_ppb, contaminant, source, dedup_key) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [("basil, dried", 0.24, 240000.0, "mandipropamid", "EPA", "t-basil-dried-only")],
        )
        self.conn.commit()
        ranked = resolve_benchmark("basil", self.conn, raw="Dried Basil")
        self.assertEqual(ranked[0], "basil, dried leaves")


class TestResolveBenchmarkAliasAndTable(unittest.TestCase):
    """resolve_benchmark must be a strict SUPERSET of the per-table resolvers
    (ingredient_risk._resolve_benchmark_category) so they can delegate to it
    without losing behavior: (1) reverse-alias expansion — a benchmark key that
    is an ALIAS of the canonical must match; (2) a ``table`` kwarg that
    restricts the query to one benchmark table instead of both."""

    def setUp(self):
        self.conn = create_test_db()
        self.conn.executemany(
            "INSERT INTO category_aliases (alias, canonical_key) VALUES (?, ?)",
            [("basil", "basil"), ("sweet basil", "basil")],
        )
        self.conn.commit()
        load_index(self.conn)

    def tearDown(self):
        self.conn.close()
        invalidate_index()

    def test_reverse_alias_expands_candidates(self):
        # 'sweet basil' is an alias of canonical 'basil'. A benchmark row filed
        # under the alias (not the canonical) must still be found — without
        # reverse-alias awareness the candidate set is only {basil, basils} and
        # this returns [].
        self.conn.execute(
            "INSERT INTO tolerance_limits "
            "(food_category, tolerance_ppm, tolerance_ppb, contaminant, source, dedup_key) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("sweet basil", 0.05, 50.0, "mandipropamid", "EPA", "t-sweetbasil"),
        )
        self.conn.commit()
        ranked = resolve_benchmark("basil", self.conn)
        self.assertIn("sweet basil", ranked)

    def test_table_param_restricts_to_one_table(self):
        # 'basil, dried leaves' exists ONLY in tolerance_limits; 'basil, eu
        # specialty' exists ONLY in international_mrls. Both share head 'basil'.
        self.conn.execute(
            "INSERT INTO tolerance_limits "
            "(food_category, tolerance_ppm, tolerance_ppb, contaminant, source, dedup_key) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("basil, dried leaves", 200.0, 200000.0, "mandipropamid", "EPA", "tbl-basil"),
        )
        self.conn.execute(
            "INSERT INTO international_mrls "
            "(food_category, pesticide, country_region, mrl_ppm, mrl_ppb, regulatory_body, dedup_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("basil, eu specialty", "mandipropamid", "EU", 10.0, 10000.0, "EFSA", "imrl-basil"),
        )
        self.conn.commit()

        both = resolve_benchmark("basil", self.conn)
        self.assertIn("basil, dried leaves", both)
        self.assertIn("basil, eu specialty", both)

        tl_only = resolve_benchmark("basil", self.conn, table="tolerance_limits")
        self.assertIn("basil, dried leaves", tl_only)
        self.assertNotIn("basil, eu specialty", tl_only)

        imrl_only = resolve_benchmark("basil", self.conn, table="international_mrls")
        self.assertIn("basil, eu specialty", imrl_only)
        self.assertNotIn("basil, dried leaves", imrl_only)


if __name__ == "__main__":
    unittest.main()
