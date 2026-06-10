"""
Tests for detect/ingredient_risk.py — Three-tier risk scoring.
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.test_detect.conftest import create_test_db, seed_food_data
from detect.ingredient_risk import IngredientRiskQuery, IngredientRiskResult
from db.database import invalidate_alias_cache


class TestIngredientRiskQuery(unittest.TestCase):
    def setUp(self):
        invalidate_alias_cache()  # Clear stale cache from previous test
        self.conn = create_test_db()
        seed_food_data(self.conn)
        self._seed_category_aliases()
        self._seed_ingredient_aliases()
        self.query = IngredientRiskQuery(self.conn)

    def tearDown(self):
        self.conn.close()

    def _seed_category_aliases(self):
        """Seed category aliases for testing."""
        aliases = [
            ("oats", "oats"),
            ("oat flour", "oats"),
            ("whole grain oats", "oats"),
            ("wheat", "wheat"),
            ("wheat flour", "wheat"),
            ("corn", "corn"),
            ("corn starch", "corn"),
            ("sugar", "sugar_beets"),
            ("salt", "fresh_vegetables"),
        ]
        self.conn.executemany(
            "INSERT OR IGNORE INTO category_aliases (alias, canonical_key) VALUES (?, ?)",
            aliases,
        )
        # Seed category_summaries for corn
        self.conn.execute(
            "INSERT INTO category_summaries "
            "(source_name, source_url, report_label, published_date, data_year, "
            "food_category, raw_category, contaminant, samples_total, samples_detected, "
            "detection_rate, avg_ppb, max_ppb, confidence, dedup_key) "
            "VALUES ('FDA', 'https://example.com', 'FDA 2024', '2024-01-01', 2024, "
            "'corn', 'Corn', 'glyphosate', 80, 50, 0.625, 150.0, 800.0, 'high', 'test-cs-corn-gly')"
        )
        self.conn.commit()

    def _seed_ingredient_aliases(self):
        """Seed additional ingredient aliases for testing."""
        # The category_aliases table already serves as ingredient mapping
        pass

    def test_tier1_grf_certified_product(self):
        """Tier 1: GRF-certified product should score 0."""
        # Add a GRF-certified product
        self.conn.execute(
            "INSERT INTO product_tests "
            "(source_name, source_url, report_label, published_date, data_year, "
            "food_category, raw_category, contaminant, product_name, measured_ppb, "
            "below_detection, is_grf_certified, confidence, dedup_key) "
            "VALUES ('DetoxProject', 'https://example.com', 'GRF 2024', '2024-01-01', 2024, "
            "'oats', 'Oats', 'glyphosate', 'Safe Oats Cereal', 0.0, "
            "1, 1, 'high', 'test-pt-grf-oats')"
        )
        self.conn.commit()

        result = self.query.execute(
            "Safe Oats Cereal",
            "whole grain oats, sugar, salt",
        )

        self.assertEqual(result.risk_level, "none")
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.tier_used, "product")
        self.assertTrue(result.certified_glyphosate_free)

    def test_tier1_below_detection_product(self):
        """Tier 1: Product tested below detection should score 0."""
        self.conn.execute(
            "INSERT INTO product_tests "
            "(source_name, source_url, report_label, published_date, data_year, "
            "food_category, raw_category, contaminant, product_name, measured_ppb, "
            "below_detection, is_grf_certified, confidence, dedup_key) "
            "VALUES ('FDA', 'https://example.com', 'FDA 2024', '2024-01-01', 2024, "
            "'oats', 'Oats', 'glyphosate', 'Clean Oats', NULL, "
            "1, 0, 'high', 'test-pt-clean-oats')"
        )
        self.conn.commit()

        result = self.query.execute(
            "Clean Oats",
            "whole grain oats, sugar",
        )

        self.assertEqual(result.risk_level, "none")
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.tier_used, "product")

    def test_tier1_detected_product(self):
        """Tier 1: Product with detection should use product data."""
        result = self.query.execute(
            "Cheerios Original",
            "whole grain oats, corn starch, sugar, salt",
        )

        self.assertEqual(result.tier_used, "product")
        # 730 ppb is well below EPA tolerance of 30,000 ppb for oats/glyphosate
        self.assertEqual(result.risk_level, "low")
        self.assertIn("730", result.notes[0])

    def test_tier2_ingredient_scoring(self):
        """Tier 2: Should score ingredients when no product match."""
        result = self.query.execute(
            "Unknown Cereal",
            "whole grain oats, corn starch, sugar, salt",
        )

        self.assertEqual(result.tier_used, "ingredient")
        self.assertGreater(len(result.ingredient_scores), 0)
        # Oats should be scored (80% detection rate)
        oat_scores = [s for s in result.ingredient_scores if s.category == "oats"]
        self.assertGreater(len(oat_scores), 0)
        self.assertEqual(oat_scores[0].risk_level, "high")  # 80% >= 66%

    def test_tier2_mixed_ingredients(self):
        """Tier 2: Should handle mix of known and unknown ingredients."""
        result = self.query.execute(
            "Mixed Product",
            "whole grain oats, mystery ingredient, corn starch",
        )

        self.assertEqual(result.tier_used, "ingredient")
        # Should have scores for oats and corn starch, but not mystery ingredient
        scored_ingredients = [s.ingredient for s in result.ingredient_scores]
        self.assertIn("whole grain oats", scored_ingredients)
        self.assertIn("corn starch", scored_ingredients)
        self.assertNotIn("mystery ingredient", scored_ingredients)

    def test_tier3_category_fallback(self):
        """Tier 3: Should fall back to category when no ingredient matches."""
        result = self.query.execute(
            "Unknown Product",
            "unknown ingredient 1, unknown ingredient 2",
            food_category="oats",
        )

        self.assertEqual(result.tier_used, "category")
        self.assertEqual(result.category_fallback, "oats")
        self.assertEqual(result.risk_level, "high")  # 80% detection rate

    def test_no_data_available(self):
        """Should return unknown when no data at any tier."""
        result = self.query.execute(
            "Mystery Product",
            "unknown ingredient",
        )

        self.assertEqual(result.tier_used, "none")
        self.assertEqual(result.risk_level, "unknown")
        self.assertEqual(result.score, 0.5)

    def test_empty_ingredients(self):
        """Should handle empty ingredients text."""
        result = self.query.execute(
            "Some Product",
            "",
            food_category="oats",
        )

        self.assertEqual(result.tier_used, "category")
        self.assertEqual(result.category_fallback, "oats")

    def test_invalid_contaminant(self):
        """Should return unknown risk level for invalid contaminant (no data)."""
        result = self.query.execute("Product", "oats", contaminant="invalid")
        self.assertEqual(result.risk_level, "unknown")

    def test_risk_level_to_score(self):
        """Test risk level to score conversion."""
        self.assertEqual(IngredientRiskQuery._risk_level_to_score("none"), 0.0)
        self.assertEqual(IngredientRiskQuery._risk_level_to_score("low"), 0.33)
        self.assertEqual(IngredientRiskQuery._risk_level_to_score("medium"), 0.66)
        self.assertEqual(IngredientRiskQuery._risk_level_to_score("high"), 1.0)
        self.assertEqual(IngredientRiskQuery._risk_level_to_score("unknown"), 0.5)

    def test_score_to_risk_level(self):
        """Test score to risk level conversion."""
        self.assertEqual(IngredientRiskQuery._score_to_risk_level(0.0), "none")
        self.assertEqual(IngredientRiskQuery._score_to_risk_level(0.1), "none")
        self.assertEqual(IngredientRiskQuery._score_to_risk_level(0.2), "low")
        self.assertEqual(IngredientRiskQuery._score_to_risk_level(0.5), "medium")
        self.assertEqual(IngredientRiskQuery._score_to_risk_level(0.8), "high")

    def test_detection_rate_to_risk_level(self):
        """Test detection rate to risk level conversion."""
        self.assertEqual(IngredientRiskQuery._detection_rate_to_risk_level(0.0), "none")
        self.assertEqual(IngredientRiskQuery._detection_rate_to_risk_level(0.1), "low")
        self.assertEqual(IngredientRiskQuery._detection_rate_to_risk_level(0.5), "medium")
        self.assertEqual(IngredientRiskQuery._detection_rate_to_risk_level(0.8), "high")


class TestIngredientRiskResult(unittest.TestCase):
    """Test the IngredientRiskResult dataclass."""

    def test_result_creation(self):
        """Test creating a result object."""
        result = IngredientRiskResult(
            product_name="Test Product",
            contaminant="glyphosate",
            risk_level="medium",
            score=0.66,
            tier_used="ingredient",
        )

        self.assertEqual(result.product_name, "Test Product")
        self.assertEqual(result.contaminant, "glyphosate")
        self.assertEqual(result.risk_level, "medium")
        self.assertEqual(result.score, 0.66)
        self.assertEqual(result.tier_used, "ingredient")
        self.assertEqual(result.ingredient_scores, [])
        self.assertIsNone(result.category_fallback)
        self.assertFalse(result.certified_glyphosate_free)
        self.assertEqual(result.notes, [])


if __name__ == "__main__":
    unittest.main()
