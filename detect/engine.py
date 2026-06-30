import json
import os
import re
import sqlite3
from typing import Optional

from detect.open_food_facts import OpenFoodFactsClient
from detect.ingredient_parser import parse_ingredients
from detect.models import (
    FoodRiskResult,
    ProductResult,
    WaterQualityResult,
    InternationalComparisonResult,
    InternationalComparisonEntry,
    RegulatoryEntry,
    IngredientDetail,
    RegulatoryFlag,
    CommodityDetail,
    CommodityResidue,
    ProductScanResult,
    ContaminantReport,
    ContaminantDetail,
    BiomonitoringResult,
    PLUResult,
    CodeScanResult,
)

from data.contaminants import divergence_type_for


class DetectionEngine:
    def __init__(self, db_path: str):
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database file not found: {db_path}")
        # Verify it's a valid SQLite database
        test_conn = sqlite3.connect(db_path)
        try:
            test_conn.execute("SELECT 1")
        except sqlite3.DatabaseError:
            raise FileNotFoundError(f"Invalid SQLite database: {db_path}")
        finally:
            test_conn.close()

        from data.datastore import create_datastore
        self._store = create_datastore(backend="sqlite", db_path=db_path)
        self._off_client = OpenFoodFactsClient()
        self._commodity_alias_cache = None  # Instance-level cache

    @classmethod
    def from_datastore(cls, store):
        """Create a DetectionEngine from any DataStore implementation.

        Args:
            store: A DataStore (SqliteDataStore, FirestoreDataStore, etc.)

        Returns:
            DetectionEngine instance backed by the given store.
        """
        # Bypass __init__ — set attributes directly
        instance = cls.__new__(cls)
        instance._store = store
        instance._off_client = OpenFoodFactsClient()
        instance._commodity_alias_cache = None
        return instance

    @property
    def _conn(self):
        """Backwards-compat: expose the underlying sqlite3.Connection when using SQLite backend."""
        if hasattr(self._store, '_conn'):
            return self._store._conn
        raise AttributeError("No sqlite3.Connection available — engine is using a non-SQLite backend")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._store.close()

    # ═══════════════════════════════════════════════
    # FOOD RISK
    # ═══════════════════════════════════════════════

    def food_risk(
        self, food_category: str, contaminant: str | None = None
    ) -> FoodRiskResult | list[FoodRiskResult] | None:
        rows = self._store.get_food_overview(food_category, contaminant)
        if not rows:
            return None if contaminant is not None else []
        if contaminant is not None:
            return self._build_food_risk_result(rows[0])
        return [self._build_food_risk_result(r) for r in rows]

    def _build_food_risk_result(self, d: dict) -> FoodRiskResult:
        reg_entries = self._get_regulatory_comparison(
            d["food_category"], d["contaminant"], d.get("max_ppb")
        )
        return FoodRiskResult(
            food_category=d["food_category"],
            contaminant=d["contaminant"],
            best_source=d["best_source"],
            data_year=d["best_data_year"],
            detection_rate=d["detection_rate"],
            avg_ppb=d.get("avg_ppb"),
            max_ppb=d.get("max_ppb"),
            samples_total=d["samples_total"],
            samples_detected=d["samples_detected"],
            risk_level=d["risk_level"],
            confidence=d["confidence"],
            total_products_tested=d.get("total_products_tested", 0),
            products_with_detection=d.get("products_with_detection", 0),
            certified_products_available=d.get("certified_products_available", 0),
            regulatory_comparison=reg_entries,
        )

    def _get_regulatory_comparison(
        self, food_category: str, contaminant: str, max_ppb: float | None = None
    ) -> list[RegulatoryEntry]:
        rows = self._store.get_all_tolerance_limits(contaminant, food_category)
        entries = []
        for r in rows:
            tol = r["tolerance_ppb"]
            pct = None
            if max_ppb is not None and tol and tol > 0:
                pct = round(max_ppb / tol * 100, 1)
            entries.append(RegulatoryEntry(
                source=r["source"],
                tolerance_ppb=tol,
                regulation_reference=r["regulation_reference"],
                pct_of_tolerance=pct,
            ))
        return entries

    # ═══════════════════════════════════════════════
    # PRODUCT LOOKUP
    # ═══════════════════════════════════════════════

    def product_lookup(
        self, query: str, contaminant: str | None = None
    ) -> list[ProductResult]:
        rows = self._store.get_product_lookup(query, contaminant)
        return [self._build_product_result(r) for r in rows]

    def _build_product_result(self, d: dict) -> ProductResult:
        return ProductResult(
            product_name=d["product_name"],
            food_category=d["food_category"],
            contaminant=d["contaminant"],
            source_name=d["source_name"],
            report_label=d["report_label"],
            data_year=d["data_year"],
            measured_ppb=d.get("measured_ppb"),
            below_detection=bool(d["below_detection"]),
            is_organic=bool(d["is_organic"]),
            is_grf_certified=bool(d["is_grf_certified"]),
            risk_level=d.get("risk_level", "unknown"),
            confidence=d["confidence"],
            source_url=d.get("source_url"),
        )

    # ═══════════════════════════════════════════════
    # WATER QUALITY
    # ═══════════════════════════════════════════════

    def water_quality(
        self,
        state: str | None = None,
        contaminant: str | None = None,
        water_type: str | None = None,
        zip_code: str | None = None,
    ) -> list[WaterQualityResult] | dict:
        # If zip code provided, resolve to state
        if zip_code and not state:
            from detect.zip_to_state import zip_to_state, is_us_zip
            if not is_us_zip(zip_code):
                return {"error": f"Invalid zip code: {zip_code}", "data": []}
            resolved_state = zip_to_state(zip_code)
            if not resolved_state:
                return {"error": f"Could not resolve zip code: {zip_code}", "data": []}
            state = resolved_state.replace("_", " ")

        rows = self._store.get_water_overview(state, contaminant, water_type)
        results = [self._build_water_result(r) for r in rows]

        if zip_code and not results:
            return {
                "error": f"No water quality data available for zip code {zip_code} ({state})",
                "data": [],
                "suggestion": "Water quality data is currently available for US states only. International coverage coming soon.",
            }
        return results

    def _build_water_result(self, d: dict) -> WaterQualityResult:
        return WaterQualityResult(
            state=d["state"],
            contaminant=d["contaminant"],
            water_type=d["water_type"],
            source_name=d["source_name"],
            data_year=d["data_year"],
            detection_rate=d.get("detection_rate"),
            avg_ppb=d.get("avg_ppb"),
            max_ppb=d.get("max_ppb"),
            samples_total=d.get("samples_total"),
            epa_mcl_ppb=d.get("epa_mcl_ppb"),
            pct_of_mcl=d.get("pct_of_mcl"),
        )

    # ═══════════════════════════════════════════════
    # INTERNATIONAL COMPARISON
    # ═══════════════════════════════════════════════

    def international_comparison(
        self, food_category: str, contaminant: str = "glyphosate"
    ) -> InternationalComparisonResult:
        rows = self._store.get_international_comparison(food_category, contaminant)
        entries = [
            InternationalComparisonEntry(
                country_region=r["country_region"],
                mrl_ppb=r["mrl_ppb"],
                regulatory_body=r["regulatory_body"] if r["regulatory_body"] is not None else None,
                measured_max_ppb=r["measured_max_ppb"] if r["measured_max_ppb"] is not None else None,
                pct_of_mrl=r["pct_of_mrl"] if r["pct_of_mrl"] is not None else None,
            )
            for r in rows
        ]
        return InternationalComparisonResult(
            food_category=food_category,
            contaminant=contaminant,
            entries=entries,
        )

    # ═══════════════════════════════════════════════
    # BIOMONITORING
    # ═══════════════════════════════════════════════

    def biomonitoring(
        self, analyte: str | None = None, cycle: str | None = None
    ) -> list[BiomonitoringResult]:
        rows = self._store.get_biomonitoring(analyte, cycle)
        return [
            BiomonitoringResult(
                analyte=r["analyte"],
                cycle=r["cycle"],
                population_group=r["population_group"],
                sample_size=r["sample_size"],
                detected_count=r["detected_count"],
                detection_rate=r["detection_rate"],
                geometric_mean=r["geometric_mean"],
                percentile_50=r["percentile_50"],
                percentile_75=r["percentile_75"],
                percentile_90=r["percentile_90"],
                percentile_95=r["percentile_95"],
                unit=r["unit"],
                lod=r["lod"],
            )
            for r in rows
        ]

    # ═══════════════════════════════════════════════
    # INGREDIENT RISK (three-tier scoring)
    # ═══════════════════════════════════════════════

    # Tier → data_confidence mapping per handoff spec
    _TIER_TO_CONFIDENCE = {
        "product": "high",      # Direct lab test match
        "ingredient": "medium", # Commodity inference
        "category": "low",      # Category-level fallback
        "none": "low",          # No data
    }

    _HEAVY_METALS = frozenset({
        "lead", "inorganic_arsenic", "cadmium", "mercury", "arsenic",
    })

    _CONSUMPTION_MULTIPLIERS = {
        "daily": 1.0,
        "weekly": 0.6,
        "occasional": 0.3,
        "rare": 0.1,
    }

    def ingredient_risk(
        self,
        product_name: str,
        ingredients: list[dict] | str,
        contaminant: str = "glyphosate",
        food_category: str | None = None,
    ):
        """Three-tier risk scoring based on ingredients."""
        from detect.ingredient_risk import IngredientRiskResult, IngredientScore
        notes = []

        # ── Tier 1: Product-level check ──
        product_result = self._check_product(product_name, contaminant)
        if product_result:
            if product_result.get("is_grf_certified"):
                return IngredientRiskResult(
                    product_name=product_name, contaminant=contaminant,
                    risk_level="none", score=0.0, tier_used="product",
                    certified_glyphosate_free=True,
                    notes=["Product is Glyphosate Residue Free certified"],
                )
            if product_result.get("below_detection"):
                return IngredientRiskResult(
                    product_name=product_name, contaminant=contaminant,
                    risk_level="none", score=0.0, tier_used="product",
                    notes=["Product tested below detection limit"],
                )
            risk_level = product_result.get("risk_level", "unknown")
            score = self._risk_level_to_score(risk_level)
            return IngredientRiskResult(
                product_name=product_name, contaminant=contaminant,
                risk_level=risk_level, score=score, tier_used="product",
                notes=[f"Product tested at {product_result.get('measured_ppb', 'N/A')} ppb"],
            )

        # ── Tier 2: Ingredient-level check ──
        if isinstance(ingredients, str):
            parsed = parse_ingredients(ingredients)
            ingredient_dicts = [{"name": ing, "text": ing, "percent": None} for ing in parsed]
        else:
            ingredient_dicts = ingredients

        if ingredient_dicts:
            ingredient_scores = []
            for ing in ingredient_dicts:
                name = ing.get("name", "") or ing.get("text", "")
                score = self._score_ingredient(name, contaminant)
                if score:
                    ingredient_scores.append(score)

            if ingredient_scores:
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
                final_score = 0.7 * max_score + 0.3 * avg_score
                risk_level = self._score_to_risk_level(final_score)
                notes.append(f"Scored {len(ingredient_scores)} of {len(ingredient_dicts)} ingredients")
                return IngredientRiskResult(
                    product_name=product_name, contaminant=contaminant,
                    risk_level=risk_level, score=final_score, tier_used="ingredient",
                    ingredient_scores=ingredient_scores, notes=notes,
                )

        # ── Tier 3: Category fallback ──
        if food_category:
            category_result = self._check_category(food_category, contaminant)
            if category_result:
                risk_level = category_result.get("risk_level", "unknown")
                score = self._risk_level_to_score(risk_level)
                return IngredientRiskResult(
                    product_name=product_name, contaminant=contaminant,
                    risk_level=risk_level, score=score, tier_used="category",
                    category_fallback=food_category,
                    notes=[f"Fell back to category '{food_category}'"],
                )

        return IngredientRiskResult(
            product_name=product_name, contaminant=contaminant,
            risk_level="unknown", score=0.5, tier_used="none",
            notes=["No data available at any tier"],
        )

    def _check_product(self, product_name: str, contaminant: str) -> Optional[dict]:
        d = self._store.get_product_tests(product_name, contaminant)
        if not d:
            return None
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

    def _score_ingredient(self, ingredient: str, contaminant: str):
        from detect.ingredient_risk import IngredientScore
        category = self._store.get_category_alias(ingredient.lower().strip())
        if not category:
            # Try substring match via aliases
            aliases = self._store.get_category_aliases()
            cleaned = ingredient.lower().strip()
            for a in aliases:
                if a["alias"] in cleaned:
                    category = a["canonical_key"]
                    break
        if not category:
            return None

        d = self._store.get_category_summaries(category, contaminant)
        if not d:
            return None

        max_ppb = d.get("max_ppb")
        consumption_tier = self._store.get_consumption_tier(category)
        risk_level = self._ppb_to_risk_level(max_ppb, contaminant, category, consumption_tier, raw=ingredient)
        return IngredientScore(
            ingredient=ingredient, category=category,
            detection_rate=d["detection_rate"], avg_ppb=d.get("avg_ppb"),
            max_ppb=max_ppb, risk_level=risk_level,
            source=d["source_name"], data_year=d.get("data_year"),
        )

    def _check_category(self, food_category: str, contaminant: str) -> Optional[dict]:
        d = self._store.get_category_summaries(food_category, contaminant)
        if not d:
            return None
        consumption_tier = self._store.get_consumption_tier(food_category)
        d["risk_level"] = self._ppb_to_risk_level(
            d.get("max_ppb"), contaminant, food_category, consumption_tier
        )
        return d

    # ── Multi-contaminant scan ──────────────────────────────────────────

    def scan_all_contaminants(
        self, food_category: str, origin_region: str | None = None
    ) -> ContaminantReport:
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

        rows = self._store.get_all_contaminants_for_category(food_category, source_priority)
        consumption_tier = self._store.get_consumption_tier(food_category)

        contaminants = []
        for d in rows:
            contam = d["contaminant"]
            max_ppb = d.get("max_ppb") or 0
            avg_ppb = d.get("avg_ppb")
            contam_type = self._store.get_contaminant_type(contam) or "pesticide"

            risk_level, risk_reason, mrl, mrl_src, tol, tol_src = \
                self._ppb_to_risk_detail(max_ppb, contam, food_category, consumption_tier)

            pct_of_mrl = (max_ppb / mrl * 100) if mrl and mrl > 0 and max_ppb else None
            pct_of_tol = (max_ppb / tol * 100) if tol and tol > 0 and max_ppb else None

            contaminants.append(ContaminantDetail(
                contaminant=contam, contaminant_type=contam_type,
                food_category=food_category,
                measured_avg_ppb=avg_ppb,
                measured_max_ppb=max_ppb if max_ppb > 0 else None,
                detection_rate=d["detection_rate"],
                samples_total=d["samples_total"],
                samples_detected=d["samples_detected"],
                source_name=d["source_name"], data_year=d.get("data_year"),
                mrl_ppb=mrl, mrl_source=mrl_src,
                tolerance_ppb=tol, tolerance_source=tol_src,
                pct_of_mrl=pct_of_mrl, pct_of_tolerance=pct_of_tol,
                risk_level=risk_level, risk_reason=risk_reason,
                confidence="high" if mrl or tol else "medium",
                detection_frequency=self._detection_rate_to_frequency(d["detection_rate"]),
            ))

        risk_order = {"high": 0, "medium": 1, "low": 2, "none": 3, "unknown": 4}
        contaminants.sort(key=lambda c: (risk_order.get(c.risk_level, 4), -c.detection_rate))

        high = sum(1 for c in contaminants if c.risk_level == "high")
        medium = sum(1 for c in contaminants if c.risk_level == "medium")
        low = sum(1 for c in contaminants if c.risk_level == "low")

        if high > 0:
            overall, overall_score = "high", 1.0
        elif medium > 0:
            overall, overall_score = "medium", 0.66
        elif low > 0:
            overall, overall_score = "low", 0.33
        else:
            overall, overall_score = "none", 0.0

        return ContaminantReport(
            food_category=food_category, contaminant=None,
            contaminants=contaminants, total_detected=len(contaminants),
            high_risk_count=high, medium_risk_count=medium, low_risk_count=low,
            overall_risk_level=overall, overall_score=overall_score,
        )

    # ── Risk level helpers ──────────────────────────────────────────────

    @staticmethod
    def _detection_rate_to_frequency(detection_rate: float) -> str:
        if detection_rate >= 0.66:
            return "high"
        elif detection_rate >= 0.31:
            return "medium"
        elif detection_rate > 0.0:
            return "low"
        return "none"

    def _ppb_to_risk_level(
        self, ppb: float, contaminant: str, food_category: str | None = None,
        consumption_tier: str | None = None, raw: str | None = None,
    ) -> str:
        if ppb is None or ppb <= 0:
            return "none"
        multiplier = self._CONSUMPTION_MULTIPLIERS.get(consumption_tier, 1.0)
        adjusted_ppb = ppb * multiplier

        tol_data = self._store.get_tolerance_limit(contaminant, food_category, raw=raw) if food_category else None
        if tol_data and (tol := tol_data.get("tolerance_ppb")) and tol > 0:
            pct = adjusted_ppb / tol
            if pct >= 2.0: return "high"
            elif pct >= 1.0: return "medium"
            elif ppb > 0: return "low"
            return "none"

        mrl_data = self._store.get_strictest_mrl(contaminant, food_category, raw=raw) if food_category else None
        if mrl_data and (mrl := mrl_data.get("mrl_ppb")) and mrl > 0:
            pct = adjusted_ppb / mrl
            if pct >= 2.0: return "high"
            elif pct >= 1.0: return "medium"
            elif ppb > 0: return "low"
            return "none"

        return "unknown"

    def _ppb_to_risk_detail(
        self, ppb: float, contaminant: str, food_category: str | None = None,
        consumption_tier: str | None = None, raw: str | None = None,
    ) -> tuple[str, str, float | None, str | None, float | None, str | None]:
        if ppb is None or ppb <= 0:
            return "none", "Not detected", None, None, None, None

        multiplier = self._CONSUMPTION_MULTIPLIERS.get(consumption_tier, 1.0)
        adjusted_ppb = ppb * multiplier
        is_heavy_metal = contaminant.lower() in self._HEAVY_METALS

        tol_data = self._store.get_tolerance_limit(contaminant, food_category, raw=raw) if food_category else None
        if tol_data and (tol := tol_data.get("tolerance_ppb")) and tol > 0:
            tol_source = tol_data.get("source", "EPA")
            pct = adjusted_ppb / tol * 100
            if pct >= 200:
                reason = f"Exceeds {tol_source} limit ({pct:.0f}%)"
                if is_heavy_metal: reason += " — heavy metal, no established safe level"
                return "high", reason, None, None, tol, tol_source
            elif pct >= 100:
                reason = f"At {tol_source} limit ({pct:.0f}%)"
                if is_heavy_metal: reason += " — heavy metal, no established safe level"
                return "medium", reason, None, None, tol, tol_source
            else:
                reason = f"Below {tol_source} limit ({pct:.0f}%)"
                if is_heavy_metal: reason += " — low confidence, consult regulatory guidance"
                return "low", reason, None, None, tol, tol_source

        mrl_data = self._store.get_strictest_mrl(contaminant, food_category, raw=raw) if food_category else None
        if mrl_data and (mrl := mrl_data.get("mrl_ppb")) and mrl > 0:
            mrl_src = mrl_data.get("country_region", "Unknown")
            pct = adjusted_ppb / mrl * 100
            if pct >= 200:
                reason = f"Exceeds {mrl_src} MRL ({pct:.0f}%)"
                if is_heavy_metal: reason += " — heavy metal, no established safe level"
                return "high", reason, mrl, mrl_src, None, None
            elif pct >= 100:
                reason = f"At {mrl_src} MRL ({pct:.0f}%)"
                if is_heavy_metal: reason += " — heavy metal, no established safe level"
                return "medium", reason, mrl, mrl_src, None, None
            else:
                reason = f"Below {mrl_src} MRL ({pct:.0f}%)"
                if is_heavy_metal: reason += " — low confidence, consult regulatory guidance"
                return "low", reason, mrl, mrl_src, None, None

        reason = "No regulatory benchmark available for comparison"
        if is_heavy_metal: reason += " — heavy metal, no established safe level"
        return "unknown", reason, None, None, None, None

    @staticmethod
    def _risk_level_to_score(risk_level: str) -> float:
        return {"none": 0.0, "low": 0.33, "medium": 0.66, "high": 1.0, "unknown": 0.5}.get(risk_level, 0.5)

    @staticmethod
    def _score_to_risk_level(score: float) -> str:
        if score <= 0.1: return "none"
        elif score <= 0.4: return "low"
        elif score <= 0.7: return "medium"
        else: return "high"

    # ═══════════════════════════════════════════════
    # BARCODE SCAN
    # ═══════════════════════════════════════════════

    # Commodity alias cache (instance-level)
    _commodity_alias_cache: dict | None = None

    def _load_commodity_aliases(self) -> dict:
        if self._commodity_alias_cache is not None:
            return self._commodity_alias_cache
        rows = self._store.get_all_commodities_with_aliases()
        cache = {}
        for row in rows:
            slug = row["commodity_slug"]
            aliases_raw = row["ingredient_aliases"]
            aliases = json.loads(aliases_raw) if isinstance(aliases_raw, str) else (aliases_raw or [])
            for alias in aliases:
                alias_lower = alias.lower().strip()
                if alias_lower not in cache or len(alias_lower) > len(cache[alias_lower]):
                    cache[alias_lower] = slug
        DetectionEngine._commodity_alias_cache = cache
        return cache

    def _match_ingredients_to_commodities(self, ingredients: list[dict] | list[str]) -> list[str]:
        alias_cache = self._load_commodity_aliases()
        matched = set()
        for ing in ingredients:
            name = (ing.get("name") or ing.get("text") or str(ing)).lower().strip()
            if not name:
                continue
            if name in alias_cache:
                matched.add(alias_cache[name])
                continue
            for alias, slug in alias_cache.items():
                if alias in name:
                    matched.add(slug)
                    break
        return sorted(matched)

    def scan_barcode(
        self, barcode: str, contaminant: str = "glyphosate",
    ) -> Optional[ProductScanResult]:
        product = self._off_client.lookup(barcode)
        if not product:
            return None

        food_category = None
        if product.get("categories"):
            for cat in product["categories"]:
                mapped = self._store.get_category_alias(cat)
                if mapped:
                    food_category = mapped
                    break

        origin_region = self._detect_origin_region(product)

        risk_result = self.ingredient_risk(
            product_name=product["product_name"],
            ingredients=product["ingredients"],
            contaminant=contaminant,
            food_category=food_category,
        )

        flagged_ingredients = []
        all_flags = []
        ingredient_list = product.get("ingredients", [])
        for ing in ingredient_list:
            name = ing.get("name") or ing.get("text") or ""
            if not name:
                continue
            detail = self.ingredient_flags(name)
            if detail and detail.flags:
                flagged_ingredients.append(detail)
                all_flags.extend(detail.flags)

        commodities_matched = self._match_ingredients_to_commodities(ingredient_list)

        contaminant_report = None
        if food_category:
            try:
                contaminant_report = self.scan_all_contaminants(food_category, origin_region=origin_region)
            except Exception:
                pass

        bio_results = []
        try:
            bio_analyte = self._contaminant_to_analyte(contaminant)
            if bio_analyte:
                bio_results = self.biomonitoring(analyte=bio_analyte)
        except Exception:
            pass

        data_confidence = self._TIER_TO_CONFIDENCE.get(
            risk_result.tier_used if risk_result else "none", "low"
        )

        ingredients_parsed = [
            (ing.get("name") or ing.get("text") or "").strip()
            for ing in ingredient_list
        ]

        if contaminant_report and contaminant_report.overall_risk_level != "none":
            effective_risk = contaminant_report.overall_risk_level
            effective_score = contaminant_report.overall_score
        else:
            effective_risk = risk_result.risk_level if risk_result else "unknown"
            effective_score = risk_result.score if risk_result else 0.5

        return ProductScanResult(
            upc=barcode,
            name=product["product_name"],
            brand=product.get("brand"),
            ingredients_raw=product.get("ingredients_text", ""),
            ingredients_parsed=ingredients_parsed,
            commodities_matched=commodities_matched,
            flags=all_flags,
            data_confidence=data_confidence,
            risk_level=effective_risk,
            score=effective_score,
            tier_used=risk_result.tier_used if risk_result else "none",
            contaminant=contaminant,
            ingredient_scores=risk_result.ingredient_scores if risk_result else [],
            notes=risk_result.notes if risk_result else [],
            contaminant_report=contaminant_report,
            biomonitoring=bio_results,
        )

    _CONTAMINANT_TO_ANALYTE = {
        "glyphosate": "Glyphosate", "lead": "Lead", "cadmium": "Cadmium",
        "mercury": "Mercury", "inorganic_arsenic": "Arsenic", "arsenic": "Arsenic",
    }

    def _contaminant_to_analyte(self, contaminant: str) -> str | None:
        return self._CONTAMINANT_TO_ANALYTE.get(contaminant.lower())

    _EU_COUNTRIES = frozenset({
        "en:france", "en:germany", "en:italy", "en:spain", "en:netherlands",
        "en:belgium", "en:poland", "en:austria", "en:portugal", "en:sweden",
        "en:denmark", "en:finland", "en:ireland", "en:greece", "en:czechia",
        "en:romania", "en:hungary", "en:bulgaria", "en:croatia", "en:slovakia",
        "en:slovenia", "en:estonia", "en:latvia", "en:lithuania", "en:luxembourg",
        "en:malta", "en:cyprus",
    })

    def _detect_origin_region(self, product: dict) -> str | None:
        countries = product.get("countries_tags", [])
        origins = product.get("origins_tags", [])
        all_tags = set(countries) | set(origins)
        if not all_tags:
            return None
        if any(tag in self._EU_COUNTRIES for tag in all_tags):
            return "EU"
        if "en:united-states" in all_tags or "en:usa" in all_tags:
            return "US"
        return None

    # ═══════════════════════════════════════════════
    # REGULATORY QUERY METHODS
    # ═══════════════════════════════════════════════

    def ingredient_flags(self, ingredient_name: str) -> Optional[IngredientDetail]:
        # Try direct ID match first, then alias match
        row = self._store.get_ingredient(
            ingredient_id=ingredient_name.lower().replace(" ", "_")
        )
        if not row:
            row = self._store.get_ingredient(name=ingredient_name)
        if not row:
            return None

        flag_rows = self._store.get_regulatory_flags(row["ingredient_id"])
        flags = [
            RegulatoryFlag(
                flag_id=r["flag_id"], ingredient_id=r["ingredient_id"],
                jurisdiction=r["jurisdiction"], flag_type=r["flag_type"],
                regulatory_body=r["regulatory_body"],
                regulation_citation=r["regulation_citation"],
                source_url=r["source_url"],
                effective_date=r["effective_date"],
                compliance_date=r["compliance_date"],
                notes=r["notes"],
                divergence_type=divergence_type_for(r["flag_type"]),
            )
            for r in flag_rows
        ]

        aliases = json.loads(row["aliases"]) if row["aliases"] else []
        flag_types = json.loads(row["flag_types"]) if row["flag_types"] else []

        return IngredientDetail(
            ingredient_id=row["ingredient_id"],
            display_name=row["display_name"],
            aliases=aliases, flag_types=flag_types, flags=flags,
            ntp_classification=row["ntp_classification"],
            iarc_classification=row["iarc_classification"],
            fda_status=row["fda_status"],
            fda_cfr_citation=row["fda_cfr_citation"],
        )

    def commodity_residues(self, commodity_slug: str) -> Optional[CommodityDetail]:
        row = self._store.get_commodity(commodity_slug)
        if not row:
            return None
        aliases = json.loads(row["ingredient_aliases"]) if row["ingredient_aliases"] else []
        raw_residues = json.loads(row["residues"]) if row["residues"] else []
        residues = [
            CommodityResidue(
                pesticide_name=r.get("pesticide_name") or r.get("pesticide", ""),
                pct_samples_detected=r.get("pct_samples_detected") or r.get("detection_rate", 0),
                median_detected_ppb=r.get("median_detected_ppb") or r.get("avg_ppb", 0),
                max_detected_ppb=r.get("max_detected_ppb") or r.get("max_ppb", 0),
                epa_tolerance_ppb=r.get("epa_tolerance_ppb", 0),
                tolerance_revoked=r.get("tolerance_revoked", False),
                pdp_year=r.get("pdp_year", 0),
            )
            for r in raw_residues
        ]
        return CommodityDetail(
            commodity_slug=row["commodity_slug"],
            display_name=row["display_name"],
            ingredient_aliases=aliases,
            pdp_commodity_code=row["pdp_commodity_code"],
            pdp_year_latest=row["pdp_year_latest"],
            residues=residues,
            dirty_dozen=bool(row["dirty_dozen"]),
            pdp_covered=bool(row.get("pdp_covered", 0)),
        )

    def lookup_plu(self, plu_code: str) -> Optional[PLUResult]:
        """Resolve an IFPS Price Look-Up code (bulk produce) to its commodity
        and any USDA PDP residue data (Layer 2). Produce carries no UPC barcode,
        so PLU is the produce equivalent of a barcode lookup."""
        row = self._store.get_plu(plu_code)
        if not row:
            return None

        slug = row.get("commodity_slug")
        commodity = self.commodity_residues(slug) if slug else None
        pdp_covered = bool(commodity.pdp_covered) if commodity else False

        notes = None
        if commodity and commodity.residues and not pdp_covered:
            # Addendum B 2.2: PDP narrowed its rotation; this commodity's data is stale.
            notes = ("USDA PDP no longer tests this commodity in its current rotation; "
                     "the residue data shown is from earlier PDP cycles.")
        elif slug and not (commodity and commodity.residues):
            notes = "No USDA PDP residue data is available for this commodity."

        return PLUResult(
            plu=row["plu"],
            commodity_display=row["commodity_display"],
            variety=row.get("variety"),
            size=row.get("size"),
            category=row.get("category"),
            commodity=commodity,
            pdp_covered=pdp_covered,
            notes=notes,
        )

    def scan_code(
        self, code: str, contaminant: str = "glyphosate"
    ) -> CodeScanResult:
        """Scan a code of unknown type and route it automatically.

        A 4-5 digit numeric code is an IFPS PLU -> bulk produce (``lookup_plu``);
        any longer numeric code is a UPC/EAN -> packaged product
        (``scan_barcode``). Non-digit characters are stripped first so typed or
        spaced codes ('PLU-3000', '3 0 0 0') still resolve.
        """
        digits = re.sub(r"\D", "", str(code or ""))
        if not digits:
            return CodeScanResult(code=str(code), code_type="unknown")
        if len(digits) in (4, 5):
            return CodeScanResult(
                code=str(code), code_type="plu",
                plu_result=self.lookup_plu(digits),
            )
        return CodeScanResult(
            code=str(code), code_type="barcode",
            product_result=self.scan_barcode(digits, contaminant=contaminant),
        )

    def lookup_alternatives(self, product_name: str, brand: str = None) -> Optional[dict]:
        # 1. Exact match on product name + brand
        if brand:
            row = self._store.get_alternatives(product_name, brand)
            if row:
                return self._build_alternatives_result(row)

        # 2. Exact match on product name only
        row = self._store.get_alternatives(product_name)
        if row:
            return self._build_alternatives_result(row)

        # 3. Case-insensitive exact match
        row = self._store.get_alternatives_case_insensitive(product_name)
        if row:
            return self._build_alternatives_result(row)

        # 4. Brand + word match
        if brand:
            brand_lower = brand.lower().strip()
            name_words = [w for w in product_name.lower().split() if len(w) > 2]
            for word in name_words:
                row = self._store.get_alternatives_by_brand_word(brand, word)
                if row:
                    return self._build_alternatives_result(row)

        # 5. Partial word match
        name_words = [w for w in product_name.lower().split() if len(w) > 3]
        for word in name_words:
            row = self._store.get_alternatives_by_word(word)
            if row:
                return self._build_alternatives_result(row)

        # 6. Brand-only match
        if brand:
            row = self._store.get_alternatives_by_brand(brand)
            if row:
                return self._build_alternatives_result(row)

        # 7. Category-based fallback
        return self._category_fallback(product_name)

    def _category_fallback(self, product_name: str) -> Optional[dict]:
        name_words = set(w.lower() for w in product_name.split() if len(w) > 3)
        stop_words = {"with", "from", "this", "that", "have", "been", "your", "their",
                      "original", "classic", "natural", "organic", "conventional"}
        name_words -= stop_words
        if not name_words:
            return None

        rows = self._store.get_certified_products()
        if not rows:
            return None

        scored = []
        for row in rows:
            cert_name = row[0].lower() if isinstance(row, (list, tuple)) else row.get("product_name", "").lower()
            cert_brand = (row[1] or "").lower() if isinstance(row, (list, tuple)) else (row.get("brand") or "").lower()
            raw_cat = (row[3] or "").lower() if isinstance(row, (list, tuple)) else (row.get("raw_category") or "").lower()
            cert_text = f"{cert_name} {cert_brand} {raw_cat}"

            skip_keywords = ["supplement", "wine", "vitamin", "protein powder",
                             "bone broth", "pet food", "personal care"]
            if any(sk in raw_cat for sk in skip_keywords):
                continue

            name_matches = sum(1 for w in name_words if w in cert_text)
            cat_matches = sum(1 for w in name_words if w in raw_cat)
            total_score = name_matches + cat_matches * 2

            if total_score > 0:
                scored.append((total_score, row))

        scored.sort(key=lambda x: -x[0])

        alternatives = []
        for score, row in scored[:5]:
            if isinstance(row, (list, tuple)):
                alternatives.append({
                    "name": row[0], "brand": row[1] or "",
                    "why_better": f"{row[2]} certified", "certification": row[2],
                    "affiliate_eligible": False,
                })
            else:
                alternatives.append({
                    "name": row.get("product_name", ""),
                    "brand": row.get("brand") or "",
                    "why_better": f"{row.get('certification', '')} certified",
                    "certification": row.get("certification", ""),
                    "affiliate_eligible": False,
                })

        if not alternatives:
            return None

        return {
            "lookup_key": "certified_fallback",
            "flagged_product_name": product_name,
            "flagged_brand": None,
            "risk_label": "CAUTION",
            "flag_summary": "Certified product alternatives",
            "alternatives": alternatives,
        }

    def _build_alternatives_result(self, row) -> dict:
        return {
            "lookup_key": row["lookup_key"],
            "flagged_product_name": row["flagged_product_name"],
            "flagged_brand": row.get("flagged_brand"),
            "risk_label": row["risk_label"],
            "flag_summary": row["flag_summary"],
            "alternatives": json.loads(row["alternatives"]) if row["alternatives"] else [],
        }

    def list_ingredients(self) -> list[IngredientDetail]:
        rows = self._store.get_all_ingredients()
        results = []
        for row in rows:
            flag_rows = self._store.get_regulatory_flags(row["ingredient_id"])
            flags = [
                RegulatoryFlag(
                    flag_id=r["flag_id"], ingredient_id=r["ingredient_id"],
                    jurisdiction=r["jurisdiction"], flag_type=r["flag_type"],
                    regulatory_body=r["regulatory_body"],
                    regulation_citation=r["regulation_citation"],
                    source_url=r["source_url"],
                    effective_date=r["effective_date"],
                    compliance_date=r["compliance_date"],
                    notes=r["notes"],
                    divergence_type=divergence_type_for(r["flag_type"]),
                )
                for r in flag_rows
            ]
            aliases = json.loads(row["aliases"]) if row["aliases"] else []
            flag_types = json.loads(row["flag_types"]) if row["flag_types"] else []
            results.append(IngredientDetail(
                ingredient_id=row["ingredient_id"],
                display_name=row["display_name"],
                aliases=aliases, flag_types=flag_types, flags=flags,
                ntp_classification=row["ntp_classification"],
                iarc_classification=row["iarc_classification"],
                fda_status=row["fda_status"],
                fda_cfr_citation=row["fda_cfr_citation"],
            ))
        return results

    def list_commodities(self) -> list[CommodityDetail]:
        rows = self._store.get_all_commodities()
        results = []
        for row in rows:
            aliases = json.loads(row["ingredient_aliases"]) if row["ingredient_aliases"] else []
            results.append(CommodityDetail(
                commodity_slug=row["commodity_slug"],
                display_name=row["display_name"],
                ingredient_aliases=aliases,
                pdp_commodity_code=row["pdp_commodity_code"],
                pdp_year_latest=row["pdp_year_latest"],
                residues=[],
                dirty_dozen=bool(row["dirty_dozen"]),
                pdp_covered=bool(row.get("pdp_covered", 0)),
            ))
        return results
