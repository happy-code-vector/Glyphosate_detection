"""
detect/ingredient_risk.py

Three-tier risk scoring for products based on ingredients.

Risk hierarchy:
1. Product → Check if specific product is flagged glyphosate-free (score = 0)
2. Ingredient → Map each ingredient to category, use category_summaries data
3. Category → Fall back to product's primary food category aggregate

Uses existing normalize_category() from data/db/database.py for ingredient→category mapping.
"""

import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Add data directory to path for database imports
sys.path.insert(0, str(Path(__file__).parent.parent / "data"))

from detect.ingredient_parser import parse_ingredients


@dataclass
class IngredientScore:
    """Risk score for a single ingredient."""
    ingredient: str
    category: Optional[str]
    detection_rate: Optional[float]
    avg_ppb: Optional[float]
    max_ppb: Optional[float]
    risk_level: str
    source: str
    data_year: Optional[int]


@dataclass
class IngredientRiskResult:
    """Overall risk result for a product based on its ingredients."""
    product_name: str
    contaminant: str
    risk_level: str
    score: float  # 0.0 = safe, 1.0 = highest risk
    tier_used: str  # 'product', 'ingredient', or 'category'
    ingredient_scores: List[IngredientScore] = field(default_factory=list)
    category_fallback: Optional[str] = None
    certified_glyphosate_free: bool = False
    notes: List[str] = field(default_factory=list)


class IngredientRiskQuery:
    """
    Three-tier risk scoring for products based on ingredients.

    Uses existing category_aliases mapping for ingredient→category resolution.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(
        self,
        product_name: str,
        ingredients: list[dict] | str,
        contaminant: str = "glyphosate",
        food_category: Optional[str] = None,
    ) -> IngredientRiskResult:
        """
        Calculate risk score for a product using three-tier hierarchy.

        Args:
            product_name: Name of the product (for Tier 1 lookup)
            ingredients: Either:
                - List of dicts with 'id', 'name', 'text', 'percent' (from OFF API)
                - Raw ingredients string (fallback, will be parsed)
            contaminant: Contaminant to check (default: glyphosate)
            food_category: Optional fallback category if ingredient mapping fails

        Returns:
            IngredientRiskResult with risk level and breakdown
        """
        notes = []

        # ── Tier 1: Product-level check ──────────────────────────────────
        product_result = self._check_product(product_name, contaminant)
        if product_result:
            if product_result.get("is_grf_certified"):
                return IngredientRiskResult(
                    product_name=product_name,
                    contaminant=contaminant,
                    risk_level="none",
                    score=0.0,
                    tier_used="product",
                    certified_glyphosate_free=True,
                    notes=["Product is Glyphosate Residue Free certified"],
                )
            if product_result.get("below_detection"):
                return IngredientRiskResult(
                    product_name=product_name,
                    contaminant=contaminant,
                    risk_level="none",
                    score=0.0,
                    tier_used="product",
                    notes=["Product tested below detection limit"],
                )
            # Product has detection data — use it
            risk_level = product_result.get("risk_level", "unknown")
            score = self._risk_level_to_score(risk_level)
            return IngredientRiskResult(
                product_name=product_name,
                contaminant=contaminant,
                risk_level=risk_level,
                score=score,
                tier_used="product",
                notes=[f"Product tested at {product_result.get('measured_ppb', 'N/A')} ppb"],
            )

        # ── Tier 2: Ingredient-level check ───────────────────────────────
        # Normalize ingredients to list of dicts
        if isinstance(ingredients, str):
            # Flat text fallback - parse into structured format
            parsed = parse_ingredients(ingredients)
            ingredient_dicts = [{"name": ing, "text": ing, "percent": None} for ing in parsed]
        else:
            # Already structured from OFF API
            ingredient_dicts = ingredients

        if ingredient_dicts:
            ingredient_scores = []
            for ing in ingredient_dicts:
                # Use English name from OFF id (e.g., "wheat flour") if available
                name = ing.get("name", "") or ing.get("text", "")
                score = self._score_ingredient(name, contaminant)
                if score:
                    ingredient_scores.append(score)

            if ingredient_scores:
                # Aggregate ingredient scores
                avg_score = sum(
                    self._risk_level_to_score(s.risk_level) for s in ingredient_scores
                ) / len(ingredient_scores)
                max_score = max(
                    self._risk_level_to_score(s.risk_level) for s in ingredient_scores
                )
                # Use weighted average: 70% max risk, 30% average risk
                final_score = 0.7 * max_score + 0.3 * avg_score
                risk_level = self._score_to_risk_level(final_score)

                notes.append(f"Scored {len(ingredient_scores)} of {len(ingredients)} ingredients")
                return IngredientRiskResult(
                    product_name=product_name,
                    contaminant=contaminant,
                    risk_level=risk_level,
                    score=final_score,
                    tier_used="ingredient",
                    ingredient_scores=ingredient_scores,
                    notes=notes,
                )

        # ── Tier 3: Category fallback ────────────────────────────────────
        if food_category:
            category_result = self._check_category(food_category, contaminant)
            if category_result:
                risk_level = category_result.get("risk_level", "unknown")
                score = self._risk_level_to_score(risk_level)
                return IngredientRiskResult(
                    product_name=product_name,
                    contaminant=contaminant,
                    risk_level=risk_level,
                    score=score,
                    tier_used="category",
                    category_fallback=food_category,
                    notes=[f"Fell back to category '{food_category}'"],
                )

        # No data available
        return IngredientRiskResult(
            product_name=product_name,
            contaminant=contaminant,
            risk_level="unknown",
            score=0.5,  # Default to medium risk when unknown
            tier_used="none",
            notes=["No data available at any tier"],
        )

    def _check_product(self, product_name: str, contaminant: str) -> Optional[dict]:
        """Check product_tests for exact product match."""
        row = self._conn.execute(
            """
            SELECT product_name, measured_ppb, below_detection, is_grf_certified,
                   is_organic, food_category, source_name, data_year
            FROM product_tests
            WHERE product_name LIKE ? AND contaminant = ?
            ORDER BY data_year DESC
            LIMIT 1
            """,
            (f"%{product_name}%", contaminant),
        ).fetchone()

        if row:
            d = dict(row)
            # Calculate risk level
            if d["is_grf_certified"]:
                d["risk_level"] = "none"
            elif d["below_detection"]:
                d["risk_level"] = "none"
            elif d["measured_ppb"] is not None:
                d["risk_level"] = self._ppb_to_risk_level(d["measured_ppb"], contaminant)
            else:
                d["risk_level"] = "unknown"
            return d
        return None

    def _score_ingredient(self, ingredient: str, contaminant: str) -> Optional[IngredientScore]:
        """
        Score a single ingredient by mapping to category and looking up data.
        Uses normalize_category() from data/db/database.py.
        """
        # Import normalize_category from database module
        try:
            from db.database import normalize_category
        except ImportError:
            # Fallback: direct SQL lookup
            return self._score_ingredient_direct(ingredient, contaminant)

        # Map ingredient to canonical category
        category = normalize_category(ingredient, conn=self._conn)
        if not category:
            return None

        # Get best category summary for this category
        row = self._conn.execute(
            """
            SELECT food_category, detection_rate, avg_ppb, max_ppb,
                   source_name, data_year, confidence
            FROM category_summaries
            WHERE food_category = ? AND contaminant = ?
            ORDER BY
                CASE source_name
                    WHEN 'FDA' THEN 3
                    WHEN 'CFIA' THEN 2
                    WHEN 'EFSA' THEN 1
                    ELSE 0
                END DESC,
                data_year DESC
            LIMIT 1
            """,
            (category, contaminant),
        ).fetchone()

        if not row:
            return None

        d = dict(row)
        risk_level = self._detection_rate_to_risk_level(d["detection_rate"])

        return IngredientScore(
            ingredient=ingredient,
            category=category,
            detection_rate=d["detection_rate"],
            avg_ppb=d.get("avg_ppb"),
            max_ppb=d.get("max_ppb"),
            risk_level=risk_level,
            source=d["source_name"],
            data_year=d.get("data_year"),
        )

    def _score_ingredient_direct(self, ingredient: str, contaminant: str) -> Optional[IngredientScore]:
        """
        Fallback: score ingredient directly via SQL when database module not available.
        """
        cleaned = ingredient.lower().strip()

        # Try exact match first
        row = self._conn.execute(
            """
            SELECT ca.canonical_key
            FROM category_aliases ca
            WHERE ca.alias = ?
            """,
            (cleaned,),
        ).fetchone()

        if not row:
            # Try substring match
            row = self._conn.execute(
                """
                SELECT ca.canonical_key
                FROM category_aliases ca
                WHERE ? LIKE '%' || ca.alias || '%'
                LIMIT 1
                """,
                (cleaned,),
            ).fetchone()

        if not row:
            return None

        category = row[0]

        # Get category summary
        row = self._conn.execute(
            """
            SELECT food_category, detection_rate, avg_ppb, max_ppb,
                   source_name, data_year, confidence
            FROM category_summaries
            WHERE food_category = ? AND contaminant = ?
            ORDER BY
                CASE source_name
                    WHEN 'FDA' THEN 3
                    WHEN 'CFIA' THEN 2
                    WHEN 'EFSA' THEN 1
                    ELSE 0
                END DESC,
                data_year DESC
            LIMIT 1
            """,
            (category, contaminant),
        ).fetchone()

        if not row:
            return None

        d = dict(row)
        risk_level = self._detection_rate_to_risk_level(d["detection_rate"])

        return IngredientScore(
            ingredient=ingredient,
            category=category,
            detection_rate=d["detection_rate"],
            avg_ppb=d.get("avg_ppb"),
            max_ppb=d.get("max_ppb"),
            risk_level=risk_level,
            source=d["source_name"],
            data_year=d.get("data_year"),
        )

    def _check_category(self, food_category: str, contaminant: str) -> Optional[dict]:
        """Check category_summaries for category-level data."""
        row = self._conn.execute(
            """
            SELECT food_category, detection_rate, avg_ppb, max_ppb,
                   source_name, data_year, confidence,
                   CASE
                       WHEN detection_rate >= 0.66 THEN 'high'
                       WHEN detection_rate >= 0.31 THEN 'medium'
                       WHEN detection_rate > 0.0 THEN 'low'
                       ELSE 'none'
                   END AS risk_level
            FROM category_summaries
            WHERE food_category = ? AND contaminant = ?
            ORDER BY
                CASE source_name
                    WHEN 'FDA' THEN 3
                    WHEN 'CFIA' THEN 2
                    WHEN 'EFSA' THEN 1
                    ELSE 0
                END DESC,
                data_year DESC
            LIMIT 1
            """,
            (food_category, contaminant),
        ).fetchone()

        return dict(row) if row else None

    # ── Risk level helpers ───────────────────────────────────────────────

    @staticmethod
    def _ppb_to_risk_level(ppb: float, contaminant: str) -> str:
        """Convert ppb measurement to risk level.

        Uses contaminant-specific thresholds from CONTAMINANTS registry
        if available. For unknown pesticides, uses generic thresholds
        based on detection rate (tier 2/3) rather than ppb.
        """
        try:
            from contaminants import CONTAMINANTS
            config = CONTAMINANTS.get(contaminant)
            if config and "risk_thresholds" in config:
                t = config["risk_thresholds"]
                if ppb >= t["high"]:
                    return "high"
                elif ppb >= t["medium"]:
                    return "medium"
                elif ppb > 0:
                    return "low"
                return "none"
        except ImportError:
            pass

        # Fallback for unknown contaminants — use generic thresholds
        # These are intentionally conservative (low thresholds)
        if ppb >= 500:
            return "high"
        elif ppb >= 100:
            return "medium"
        elif ppb > 0:
            return "low"
        return "none"

    @staticmethod
    def _detection_rate_to_risk_level(detection_rate: float) -> str:
        """Convert detection rate to risk level."""
        if detection_rate >= 0.66:
            return "high"
        elif detection_rate >= 0.31:
            return "medium"
        elif detection_rate > 0.0:
            return "low"
        return "none"

    @staticmethod
    def _risk_level_to_score(risk_level: str) -> float:
        """Convert risk level to numeric score (0.0 = safe, 1.0 = highest risk)."""
        scores = {
            "none": 0.0,
            "low": 0.33,
            "medium": 0.66,
            "high": 1.0,
            "unknown": 0.5,
        }
        return scores.get(risk_level, 0.5)

    @staticmethod
    def _score_to_risk_level(score: float) -> str:
        """Convert numeric score back to risk level."""
        if score <= 0.1:
            return "none"
        elif score <= 0.4:
            return "low"
        elif score <= 0.7:
            return "medium"
        else:
            return "high"
