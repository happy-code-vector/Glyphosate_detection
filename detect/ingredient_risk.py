"""
detect/ingredient_risk.py

Three-tier risk scoring for products based on ingredients.

Risk hierarchy:
1. Product → Check if specific product is flagged glyphosate-free (score = 0)
2. Ingredient → Map each ingredient to category, use category_summaries data
3. Category → Fall back to product's primary food category aggregate

Risk assessment uses regulatory data (international_mrls, tolerance_limits)
instead of hardcoded thresholds. Heavy metals have special handling (no safe level).
"""

import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Add data directory to path for database imports
sys.path.insert(0, str(Path(__file__).parent.parent / "data"))

from detect.ingredient_parser import parse_ingredients
from detect.models import ContaminantDetail, ContaminantReport


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
                # Aggregate ingredient scores — exclude unknown from calculation
                # to avoid inflating risk when data is simply absent
                known_scores = [
                    self._risk_level_to_score(s.risk_level)
                    for s in ingredient_scores
                    if s.risk_level != "unknown"
                ]
                if known_scores:
                    avg_score = sum(known_scores) / len(known_scores)
                    max_score = max(known_scores)
                else:
                    avg_score = 0.0
                    max_score = 0.0
                # Use weighted average: 70% max risk, 30% average risk
                final_score = 0.7 * max_score + 0.3 * avg_score
                risk_level = self._score_to_risk_level(final_score)

                notes.append(f"Scored {len(ingredient_scores)} of {len(ingredient_dicts)} ingredients")
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
                d["risk_level"] = self._ppb_to_risk_level(
                    d["measured_ppb"], contaminant, d.get("food_category")
                )
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
        max_ppb = d.get("max_ppb")
        # Look up consumption tier for this category
        consumption_tier = self._get_consumption_tier(category)
        risk_level = self._ppb_to_risk_level(max_ppb, contaminant, category, consumption_tier)

        return IngredientScore(
            ingredient=ingredient,
            category=category,
            detection_rate=d["detection_rate"],
            avg_ppb=d.get("avg_ppb"),
            max_ppb=max_ppb,
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
        max_ppb = d.get("max_ppb")
        consumption_tier = self._get_consumption_tier(category)
        risk_level = self._ppb_to_risk_level(max_ppb, contaminant, category, consumption_tier)

        return IngredientScore(
            ingredient=ingredient,
            category=category,
            detection_rate=d["detection_rate"],
            avg_ppb=d.get("avg_ppb"),
            max_ppb=max_ppb,
            risk_level=risk_level,
            source=d["source_name"],
            data_year=d.get("data_year"),
        )

    def _check_category(self, food_category: str, contaminant: str) -> Optional[dict]:
        """Check category_summaries for category-level data.

        Uses ppb-vs-MRL for risk_level (consistent with Tier 1 and Tier 2).
        Detection rate is returned as a data point but does not drive risk_level.
        """
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
            (food_category, contaminant),
        ).fetchone()

        if not row:
            return None

        d = dict(row)
        consumption_tier = self._get_consumption_tier(food_category)
        d["risk_level"] = self._ppb_to_risk_level(
            d.get("max_ppb"), contaminant, food_category, consumption_tier
        )
        return d

    # ── Multi-contaminant scan ───────────────────────────────────────────

    def scan_all_contaminants(
        self, food_category: str, origin_region: str | None = None
    ) -> ContaminantReport:
        """Scan ALL contaminants for a food category using regulatory data.

        Args:
            food_category: Canonical food category
            origin_region: 'EU' or 'US' — adjusts source priority for best-source selection.
                           EU products prefer EFSA/BVL data, US products prefer FDA.
        """
        # Source priority: EU products prefer European monitoring data
        if origin_region == "EU":
            source_priority = """
                CASE source_name
                    WHEN 'EFSA' THEN 5
                    WHEN 'Germany_BVL' THEN 4
                    WHEN 'UK_FSA' THEN 3
                    WHEN 'CFIA' THEN 2
                    WHEN 'FDA' THEN 1
                    ELSE 0
                END
            """
        else:
            source_priority = """
                CASE source_name
                    WHEN 'FDA' THEN 5
                    WHEN 'CFIA' THEN 4
                    WHEN 'EFSA' THEN 3
                    WHEN 'UK_FSA' THEN 2
                    WHEN 'Germany_BVL' THEN 1
                    ELSE 0
                END
            """

        # Get all contaminants with detections for this category
        # Use source priority to pick the best source per contaminant
        rows = self._conn.execute(
            f"""
            SELECT contaminant, detection_rate, avg_ppb, max_ppb,
                   samples_total, samples_detected, source_name, data_year
            FROM (
                SELECT contaminant, detection_rate, avg_ppb, max_ppb,
                       samples_total, samples_detected, source_name, data_year,
                       ROW_NUMBER() OVER (
                           PARTITION BY contaminant
                           ORDER BY {source_priority} DESC, data_year DESC
                       ) AS rn
                FROM category_summaries
                WHERE food_category = ?
                AND detection_rate > 0
            )
            WHERE rn = 1
            ORDER BY detection_rate DESC
            """,
            (food_category,),
        ).fetchall()

        # Look up consumption tier once for this food category
        consumption_tier = self._get_consumption_tier(food_category)

        contaminants = []
        for row in rows:
            d = dict(row)
            contam = d["contaminant"]
            max_ppb = d.get("max_ppb") or 0
            avg_ppb = d.get("avg_ppb")

            # Get contaminant type
            contam_type = self._get_contaminant_type(contam)

            # Get risk assessment using regulatory data
            risk_level, risk_reason, mrl, mrl_src, tol, tol_src = \
                self._ppb_to_risk_detail(max_ppb, contam, food_category, consumption_tier)

            # Calculate percentages
            pct_of_mrl = (max_ppb / mrl * 100) if mrl and mrl > 0 and max_ppb else None
            pct_of_tol = (max_ppb / tol * 100) if tol and tol > 0 and max_ppb else None

            contaminants.append(ContaminantDetail(
                contaminant=contam,
                contaminant_type=contam_type,
                food_category=food_category,
                measured_avg_ppb=avg_ppb,
                measured_max_ppb=max_ppb if max_ppb > 0 else None,
                detection_rate=d["detection_rate"],
                samples_total=d["samples_total"],
                samples_detected=d["samples_detected"],
                source_name=d["source_name"],
                data_year=d.get("data_year"),
                mrl_ppb=mrl,
                mrl_source=mrl_src,
                tolerance_ppb=tol,
                tolerance_source=tol_src,
                pct_of_mrl=pct_of_mrl,
                pct_of_tolerance=pct_of_tol,
                risk_level=risk_level,
                risk_reason=risk_reason,
                confidence="high" if mrl or tol else "medium",
                detection_frequency=self._detection_rate_to_frequency(d["detection_rate"]),
            ))

        # Sort: high first, then medium, then low
        risk_order = {"high": 0, "medium": 1, "low": 2, "none": 3, "unknown": 4}
        contaminants.sort(key=lambda c: (risk_order.get(c.risk_level, 4), -c.detection_rate))

        high = sum(1 for c in contaminants if c.risk_level == "high")
        medium = sum(1 for c in contaminants if c.risk_level == "medium")
        low = sum(1 for c in contaminants if c.risk_level == "low")

        if high > 0:
            overall = "high"
            overall_score = 1.0
        elif medium > 0:
            overall = "medium"
            overall_score = 0.66
        elif low > 0:
            overall = "low"
            overall_score = 0.33
        else:
            overall = "none"
            overall_score = 0.0

        return ContaminantReport(
            food_category=food_category,
            contaminant=None,
            contaminants=contaminants,
            total_detected=len(contaminants),
            high_risk_count=high,
            medium_risk_count=medium,
            low_risk_count=low,
            overall_risk_level=overall,
            overall_score=overall_score,
        )

    def _get_contaminant_type(self, contaminant: str) -> str:
        """Get contaminant type from ingredients table or contaminants registry."""
        # Try ingredients table first
        row = self._conn.execute(
            "SELECT contaminant_type FROM ingredients WHERE ingredient_id = ?",
            (contaminant.lower().replace(" ", "_"),),
        ).fetchone()
        if row and row["contaminant_type"]:
            return row["contaminant_type"]

        # Try contaminants.py registry
        try:
            from contaminants import CONTAMINANTS
            config = CONTAMINANTS.get(contaminant.lower())
            if config:
                return config.get("type", "unknown")
        except ImportError:
            pass

        # Infer from name
        if contaminant.lower() in self._HEAVY_METALS:
            return "heavy_metal"
        return "pesticide"  # Default assumption

    def _get_consumption_tier(self, food_category: str) -> str | None:
        """Look up consumption tier for a food category from commodities table."""
        if not food_category:
            return None
        row = self._conn.execute(
            "SELECT consumption_tier FROM commodities WHERE commodity_slug = ?",
            (food_category,),
        ).fetchone()
        return row["consumption_tier"] if row else None

    @staticmethod
    def _detection_rate_to_frequency(detection_rate: float) -> str:
        """Convert detection rate to a frequency label (not risk)."""
        if detection_rate >= 0.66:
            return "high"
        elif detection_rate >= 0.31:
            return "medium"
        elif detection_rate > 0.0:
            return "low"
        return "none"

    # ── Risk level helpers ───────────────────────────────────────────────

    # Heavy metals — FDA says "no safe level" for lead in baby food specifically.
    # For general food, we note low confidence rather than auto-escalating.
    _HEAVY_METALS = frozenset({
        "lead", "inorganic_arsenic", "cadmium", "mercury", "arsenic",
    })

    # Consumption tier multipliers — adjusts ppb by how much of this food
    # a typical person eats. Daily staples get full weight, rare items get 0.1x.
    _CONSUMPTION_MULTIPLIERS = {
        "daily": 1.0,       # wheat, rice, oats, milk, eggs, corn, potato, tomato
        "weekly": 0.6,      # apple, orange, strawberry, spinach, lettuce, broccoli
        "occasional": 0.3,  # barley, herbs, specialty vegetables
        "rare": 0.1,        # saffron, vanilla, specialty spices
    }

    def _ppb_to_risk_level(
        self, ppb: float, contaminant: str, food_category: str | None = None,
        consumption_tier: str | None = None,
    ) -> str:
        """Convert ppb measurement to risk level using regulatory data.

        Priority:
        1. EPA tolerance_limits (US regulatory standard)
        2. International MRLs (EFSA, Codex, Japan, etc.)
        3. Return 'unknown' if no regulatory data exists

        Thresholds:
        - ≥ 200% of limit → HIGH (well above regulatory limit)
        - ≥ 100% of limit → MEDIUM (at or above limit)
        - > 0%            → LOW (detected but below limit)
        """
        if ppb is None or ppb <= 0:
            return "none"

        # Apply consumption multiplier if tier is known
        multiplier = self._CONSUMPTION_MULTIPLIERS.get(consumption_tier, 1.0)
        adjusted_ppb = ppb * multiplier

        # 1. Try EPA tolerance_limits first (US standard)
        tolerance = self._get_lowest_tolerance(contaminant, food_category)
        if tolerance and tolerance > 0:
            pct = adjusted_ppb / tolerance
            if pct >= 2.0:
                return "high"
            elif pct >= 1.0:
                return "medium"
            elif ppb > 0:
                return "low"
            return "none"

        # 2. Try international MRLs (EFSA, Codex, Japan, etc.)
        mrl = self._get_strictest_mrl(contaminant, food_category)
        if mrl and mrl > 0:
            pct = adjusted_ppb / mrl
            if pct >= 2.0:
                return "high"
            elif pct >= 1.0:
                return "medium"
            elif ppb > 0:
                return "low"
            return "none"

        # 3. No regulatory data — return 'unknown' honestly
        return "unknown"

    def _ppb_to_risk_detail(
        self, ppb: float, contaminant: str, food_category: str | None = None,
        consumption_tier: str | None = None,
    ) -> tuple[str, str, float | None, str | None, float | None, str | None]:
        """Return (risk_level, risk_reason, mrl_ppb, mrl_source, tolerance_ppb, tolerance_source).

        Thresholds: ≥200% of limit = HIGH, ≥100% = MEDIUM, >0% = LOW.
        No benchmark = 'unknown' (honest, not fabricated).
        Heavy metals: low confidence note, not auto-escalation.
        """
        if ppb is None or ppb <= 0:
            return "none", "Not detected", None, None, None, None

        # Apply consumption multiplier
        multiplier = self._CONSUMPTION_MULTIPLIERS.get(consumption_tier, 1.0)
        adjusted_ppb = ppb * multiplier

        contaminant_lower = contaminant.lower()
        is_heavy_metal = contaminant_lower in self._HEAVY_METALS

        # 1. Try EPA tolerance_limits first (US standard)
        tolerance, tol_source = self._get_lowest_tolerance_with_source(contaminant, food_category)
        if tolerance and tolerance > 0:
            pct = adjusted_ppb / tolerance * 100
            if pct >= 200:
                reason = f"Exceeds {tol_source} limit ({pct:.0f}%)"
                if is_heavy_metal:
                    reason += " — heavy metal, no established safe level"
                return "high", reason, None, None, tolerance, tol_source
            elif pct >= 100:
                reason = f"At {tol_source} limit ({pct:.0f}%)"
                if is_heavy_metal:
                    reason += " — heavy metal, no established safe level"
                return "medium", reason, None, None, tolerance, tol_source
            else:
                reason = f"Below {tol_source} limit ({pct:.0f}%)"
                if is_heavy_metal:
                    reason += " — low confidence, consult regulatory guidance"
                return "low", reason, None, None, tolerance, tol_source

        # 2. Try international MRLs (EFSA, Codex, Japan, etc.)
        mrl, mrl_source = self._get_strictest_mrl_with_source(contaminant, food_category)
        if mrl and mrl > 0:
            pct = adjusted_ppb / mrl * 100
            if pct >= 200:
                reason = f"Exceeds {mrl_source} MRL ({pct:.0f}%)"
                if is_heavy_metal:
                    reason += " — heavy metal, no established safe level"
                return "high", reason, mrl, mrl_source, None, None
            elif pct >= 100:
                reason = f"At {mrl_source} MRL ({pct:.0f}%)"
                if is_heavy_metal:
                    reason += " — heavy metal, no established safe level"
                return "medium", reason, mrl, mrl_source, None, None
            else:
                reason = f"Below {mrl_source} MRL ({pct:.0f}%)"
                if is_heavy_metal:
                    reason += " — low confidence, consult regulatory guidance"
                return "low", reason, mrl, mrl_source, None, None

        # 3. No regulatory data — return 'unknown' honestly
        reason = "No regulatory benchmark available for comparison"
        if is_heavy_metal:
            reason += " — heavy metal, no established safe level"
        return "unknown", reason, None, None, None, None

    def _resolve_benchmark_category(
        self, food_category: str, table: str
    ) -> str:
        """Resolve a canonical key to the actual food_category in a benchmark table.

        Tries: exact match, plural/singular, underscore/space variants,
        and reverse alias lookup (aliases that map TO this canonical key).
        Returns the matched food_category or the original if no match.
        """
        fc = food_category.strip()
        candidates = [fc]

        # Plural/singular variations
        if fc.endswith("s"):
            candidates.append(fc[:-1])  # "kales" -> "kale"
        else:
            candidates.append(fc + "s")  # "kale" -> "kales"
        if fc.endswith("ies"):
            candidates.append(fc[:-3] + "y")  # "cherries" -> "cherry"
        elif fc.endswith("es"):
            candidates.append(fc[:-2])  # "oranges" -> "orange"

        # Underscore/space variations
        if "_" in fc:
            candidates.append(fc.replace("_", " "))
        if " " in fc:
            candidates.append(fc.replace(" ", "_"))

        # Reverse alias lookup: find aliases that map TO this canonical key
        # and try them as benchmark food_category values
        alias_rows = self._conn.execute(
            "SELECT alias FROM category_aliases WHERE canonical_key = ?",
            (fc,),
        ).fetchall()
        for r in alias_rows:
            candidates.append(r["alias"])

        # Check which candidates exist in the benchmark table
        # Use LOWER() for case-insensitive matching
        lower_set = set()
        final_candidates = []
        for c in candidates:
            cl = c.lower()
            if cl not in lower_set:
                lower_set.add(cl)
                final_candidates.append(c)

        placeholders = ",".join("?" * len(final_candidates))
        row = self._conn.execute(
            f"SELECT DISTINCT food_category FROM {table} "
            f"WHERE LOWER(food_category) IN ({placeholders}) "
            f"LIMIT 1",
            [c.lower() for c in final_candidates],
        ).fetchone()

        return row["food_category"] if row else fc

    def _get_strictest_mrl(
        self, contaminant: str, food_category: str | None = None
    ) -> float | None:
        """Get the strictest (lowest) MRL from international_mrls.

        Only returns category-specific MRLs. No cross-category fallback —
        using an MRL from a different food is worse than having no MRL at all.
        """
        if not food_category:
            return None
        resolved = self._resolve_benchmark_category(
            food_category, "international_mrls"
        )
        row = self._conn.execute(
            "SELECT MIN(mrl_ppb) as min_mrl FROM international_mrls "
            "WHERE LOWER(pesticide) = ? AND LOWER(food_category) = ? "
            "AND mrl_ppb > 0",
            (contaminant.lower(), resolved.lower()),
        ).fetchone()
        return row["min_mrl"] if row and row["min_mrl"] else None

    def _get_strictest_mrl_with_source(
        self, contaminant: str, food_category: str | None = None
    ) -> tuple[float | None, str | None]:
        """Get the strictest MRL and which country set it.

        Only returns category-specific MRLs. No cross-category fallback.
        """
        if not food_category:
            return None, None
        resolved = self._resolve_benchmark_category(
            food_category, "international_mrls"
        )
        row = self._conn.execute(
            "SELECT mrl_ppb, country_region FROM international_mrls "
            "WHERE LOWER(pesticide) = ? AND LOWER(food_category) = ? "
            "AND mrl_ppb > 0 "
            "ORDER BY mrl_ppb ASC LIMIT 1",
            (contaminant.lower(), resolved.lower()),
        ).fetchone()
        if row and row["mrl_ppb"]:
            return row["mrl_ppb"], row["country_region"]
        return None, None

    def _get_lowest_tolerance(
        self, contaminant: str, food_category: str | None = None
    ) -> float | None:
        """Get the lowest tolerance from tolerance_limits.

        Only returns category-specific tolerances. No cross-category fallback.
        """
        if not food_category:
            return None
        resolved = self._resolve_benchmark_category(
            food_category, "tolerance_limits"
        )
        row = self._conn.execute(
            "SELECT MIN(tolerance_ppb) as min_tol FROM tolerance_limits "
            "WHERE LOWER(contaminant) = ? AND LOWER(food_category) = ? "
            "AND tolerance_ppb > 0",
            (contaminant.lower(), resolved.lower()),
        ).fetchone()
        return row["min_tol"] if row and row["min_tol"] else None

    def _get_lowest_tolerance_with_source(
        self, contaminant: str, food_category: str | None = None
    ) -> tuple[float | None, str | None]:
        """Get the lowest tolerance and its source.

        Only returns category-specific tolerances. No cross-category fallback.
        """
        if not food_category:
            return None, None
        resolved = self._resolve_benchmark_category(
            food_category, "tolerance_limits"
        )
        row = self._conn.execute(
            "SELECT tolerance_ppb, source FROM tolerance_limits "
            "WHERE LOWER(contaminant) = ? AND LOWER(food_category) = ? "
            "AND tolerance_ppb > 0 "
            "ORDER BY tolerance_ppb ASC LIMIT 1",
            (contaminant.lower(), resolved.lower()),
        ).fetchone()
        if row and row["tolerance_ppb"]:
            return row["tolerance_ppb"], row["source"]
        return None, None

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
