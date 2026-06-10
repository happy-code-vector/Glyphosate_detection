import json
import os
import sqlite3
from typing import Optional

from detect.food_risk import FoodRiskQuery
from detect.product_lookup import ProductLookupQuery
from detect.water_quality import WaterQualityQuery
from detect.comparison import ComparisonQuery
from detect.ingredient_risk import IngredientRiskQuery, IngredientRiskResult
from detect.open_food_facts import OpenFoodFactsClient
from detect.models import (
    FoodRiskResult,
    ProductResult,
    WaterQualityResult,
    InternationalComparisonResult,
    IngredientDetail,
    RegulatoryFlag,
    CommodityDetail,
    CommodityResidue,
    ProductScanResult,
    ContaminantReport,
)


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
        try:
            self._conn = sqlite3.connect(db_path)
            self._conn.row_factory = sqlite3.Row
        except sqlite3.OperationalError:
            raise FileNotFoundError(f"Cannot open database: {db_path}")

        self._food_risk = FoodRiskQuery(self._conn)
        self._product_lookup = ProductLookupQuery(self._conn)
        self._water_quality = WaterQualityQuery(self._conn)
        self._comparison = ComparisonQuery(self._conn)
        self._ingredient_risk = IngredientRiskQuery(self._conn)
        self._off_client = OpenFoodFactsClient()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._conn.close()

    def food_risk(
        self, food_category: str, contaminant: str | None = None
    ) -> FoodRiskResult | list[FoodRiskResult] | None:
        return self._food_risk.execute(food_category, contaminant)

    def product_lookup(
        self, query: str, contaminant: str | None = None
    ) -> list[ProductResult]:
        return self._product_lookup.execute(query, contaminant)

    def water_quality(
        self,
        state: str | None = None,
        contaminant: str | None = None,
        water_type: str | None = None,
        zip_code: str | None = None,
    ) -> list[WaterQualityResult] | dict:
        """
        Query water quality data by state or zip code.

        Args:
            state: US state name (e.g. 'California')
            contaminant: Specific contaminant to filter by
            water_type: 'surface' or 'groundwater'
            zip_code: US zip code (e.g. '90210') — resolved to state automatically

        Returns:
            list[WaterQualityResult] if data found
            dict with 'error' key if zip code not resolvable or no data
        """
        # If zip code provided, resolve to state
        if zip_code and not state:
            from detect.zip_to_state import zip_to_state, is_us_zip
            if not is_us_zip(zip_code):
                return {"error": f"Invalid zip code: {zip_code}", "data": []}
            resolved_state = zip_to_state(zip_code)
            if not resolved_state:
                return {"error": f"Could not resolve zip code: {zip_code}", "data": []}
            state = resolved_state.replace("_", " ")

        results = self._water_quality.execute(state, contaminant, water_type)

        # If zip code was used and no results, return helpful message
        if zip_code and not results:
            return {
                "error": f"No water quality data available for zip code {zip_code} ({state})",
                "data": [],
                "suggestion": "Water quality data is currently available for US states only. International coverage coming soon.",
            }

        return results

    def international_comparison(
        self, food_category: str, contaminant: str = "glyphosate"
    ) -> InternationalComparisonResult:
        return self._comparison.execute(food_category, contaminant)

    def ingredient_risk(
        self,
        product_name: str,
        ingredients: list[dict] | str,
        contaminant: str = "glyphosate",
        food_category: str | None = None,
    ) -> IngredientRiskResult:
        """
        Three-tier risk scoring based on ingredients.

        Risk hierarchy:
        1. Product → Check if specific product is flagged glyphosate-free
        2. Ingredient → Map each ingredient to category, use category data
        3. Category → Fall back to product's primary food category
        """
        return self._ingredient_risk.execute(
            product_name, ingredients, contaminant, food_category
        )

    def scan_all_contaminants(self, food_category: str) -> "ContaminantReport":
        """
        Scan ALL contaminants for a food category using regulatory data.

        Compares measured levels (from category_summaries) against MRLs
        (from international_mrls) and tolerances (from tolerance_limits).

        Returns a ContaminantReport with per-contaminant risk assessment,
        sorted by risk level (high first).

        Args:
            food_category: Canonical food category (e.g., 'oats', 'wheat')

        Returns:
            ContaminantReport with list of ContaminantDetail entries
        """
        from detect.ingredient_risk import IngredientRiskQuery
        query = IngredientRiskQuery(self._conn)
        return query.scan_all_contaminants(food_category)

    # Tier → data_confidence mapping per handoff spec
    _TIER_TO_CONFIDENCE = {
        "product": "high",      # Direct lab test match
        "ingredient": "medium", # Commodity inference
        "category": "low",      # Category-level fallback
        "none": "low",          # No data
    }

    # Commodity alias cache (loaded once)
    _commodity_alias_cache: dict | None = None  # alias -> commodity_slug

    def _load_commodity_aliases(self) -> dict:
        """Load commodity ingredient_aliases into a cached dict."""
        if self._commodity_alias_cache is not None:
            return self._commodity_alias_cache

        rows = self._conn.execute(
            "SELECT commodity_slug, ingredient_aliases FROM commodities "
            "WHERE ingredient_aliases IS NOT NULL"
        ).fetchall()

        cache = {}  # alias -> commodity_slug
        for row in rows:
            slug = row["commodity_slug"]
            aliases = json.loads(row["ingredient_aliases"])
            for alias in aliases:
                alias_lower = alias.lower().strip()
                # Prefer longer (more specific) aliases
                if alias_lower not in cache or len(alias_lower) > len(cache[alias_lower]):
                    cache[alias_lower] = slug

        DetectionEngine._commodity_alias_cache = cache
        return cache

    def _match_ingredients_to_commodities(self, ingredients: list[dict] | list[str]) -> list[str]:
        """
        Match ingredient names to commodity slugs.
        Returns list of unique matched commodity slugs.
        """
        alias_cache = self._load_commodity_aliases()
        matched = set()

        for ing in ingredients:
            name = (ing.get("name") or ing.get("text") or str(ing)).lower().strip()
            if not name:
                continue

            # Exact match
            if name in alias_cache:
                matched.add(alias_cache[name])
                continue

            # Substring match (ingredient contains alias)
            for alias, slug in alias_cache.items():
                if alias in name:
                    matched.add(slug)
                    break

        return sorted(matched)

    def scan_barcode(
        self,
        barcode: str,
        contaminant: str = "glyphosate",
    ) -> Optional[ProductScanResult]:
        """
        Scan a barcode and return full product scan result.

        Complete flow:
        1. Look up product via Open Food Facts API
        2. Run three-tier risk scoring (product → ingredient → category)
        3. Check each ingredient against regulatory flags
        4. Match ingredients to commodities for PDP residue data
        5. Compute data_confidence from tier used
        """
        product = self._off_client.lookup(barcode)
        if not product:
            return None

        # Map OFF categories to canonical food category
        food_category = None
        if product.get("categories"):
            from db.database import normalize_category
            for cat in product["categories"]:
                mapped = normalize_category(cat, conn=self._conn)
                if mapped:
                    food_category = mapped
                    break

        # Step 1: Risk scoring (three-tier)
        risk_result = self._ingredient_risk.execute(
            product_name=product["product_name"],
            ingredients=product["ingredients"],
            contaminant=contaminant,
            food_category=food_category,
        )

        # Step 2: Regulatory flags for each ingredient
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

        # Step 3: Commodity matching
        commodities_matched = self._match_ingredients_to_commodities(ingredient_list)

        # Step 4: Multi-contaminant report (all contaminants for this food category)
        contaminant_report = None
        if food_category:
            try:
                contaminant_report = self.scan_all_contaminants(food_category)
            except Exception:
                pass  # Non-critical — don't fail the scan

        # Step 5: Data confidence from tier
        data_confidence = self._TIER_TO_CONFIDENCE.get(
            risk_result.tier_used if risk_result else "none", "low"
        )

        # Build ingredient name list
        ingredients_parsed = [
            (ing.get("name") or ing.get("text") or "").strip()
            for ing in ingredient_list
        ]

        return ProductScanResult(
            upc=barcode,
            name=product["product_name"],
            brand=product.get("brand"),
            ingredients_raw=product.get("ingredients_text", ""),
            ingredients_parsed=ingredients_parsed,
            commodities_matched=commodities_matched,
            flags=all_flags,
            data_confidence=data_confidence,
            risk_level=risk_result.risk_level if risk_result else "unknown",
            score=risk_result.score if risk_result else 0.5,
            tier_used=risk_result.tier_used if risk_result else "none",
            contaminant=contaminant,
            ingredient_scores=risk_result.ingredient_scores if risk_result else [],
            notes=risk_result.notes if risk_result else [],
            contaminant_report=contaminant_report,
        )

    # ═════════════════════════════════════════════
    # REGULATORY QUERY METHODS
    # ═════════════════════════════════════════════

    def ingredient_flags(self, ingredient_name: str) -> Optional[IngredientDetail]:
        """
        Look up regulatory flags for a specific ingredient.

        Args:
            ingredient_name: Ingredient name or ID (e.g. 'red_40', 'potassium bromate')

        Returns:
            IngredientDetail with all flags, IARC/NTP data, FDA status
            None if ingredient not found
        """
        # Try direct ID match first, then alias match
        row = self._conn.execute(
            "SELECT * FROM ingredients WHERE ingredient_id = ?",
            (ingredient_name.lower().replace(" ", "_"),),
        ).fetchone()

        if not row:
            # Try alias search — exact match within aliases list
            name_lower = ingredient_name.lower()
            candidates = self._conn.execute(
                "SELECT * FROM ingredients WHERE aliases LIKE ?",
                (f"%{name_lower}%",),
            ).fetchall()
            for c in candidates:
                try:
                    alias_list = json.loads(c["aliases"]) if c["aliases"] else []
                    if name_lower in [a.lower() for a in alias_list]:
                        row = c
                        break
                except (json.JSONDecodeError, TypeError):
                    pass

        if not row:
            return None

        # Get flags
        flag_rows = self._conn.execute(
            "SELECT * FROM regulatory_flags WHERE ingredient_id = ?",
            (row["ingredient_id"],),
        ).fetchall()

        flags = [
            RegulatoryFlag(
                flag_id=r["flag_id"],
                ingredient_id=r["ingredient_id"],
                jurisdiction=r["jurisdiction"],
                flag_type=r["flag_type"],
                regulatory_body=r["regulatory_body"],
                regulation_citation=r["regulation_citation"],
                source_url=r["source_url"],
                effective_date=r["effective_date"],
                compliance_date=r["compliance_date"],
                notes=r["notes"],
            )
            for r in flag_rows
        ]

        aliases = json.loads(row["aliases"]) if row["aliases"] else []
        flag_types = json.loads(row["flag_types"]) if row["flag_types"] else []

        return IngredientDetail(
            ingredient_id=row["ingredient_id"],
            display_name=row["display_name"],
            aliases=aliases,
            flag_types=flag_types,
            flags=flags,
            ntp_classification=row["ntp_classification"],
            iarc_classification=row["iarc_classification"],
            fda_status=row["fda_status"],
            fda_cfr_citation=row["fda_cfr_citation"],
        )

    def commodity_residues(self, commodity_slug: str) -> Optional[CommodityDetail]:
        """
        Get pesticide residue data for a commodity.

        Args:
            commodity_slug: Commodity identifier (e.g. 'strawberry', 'wheat')

        Returns:
            CommodityDetail with residue data and ingredient aliases
            None if commodity not found
        """
        row = self._conn.execute(
            "SELECT * FROM commodities WHERE commodity_slug = ?",
            (commodity_slug.lower(),),
        ).fetchone()

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
        )

    def lookup_alternatives(self, product_name: str, brand: str = None) -> Optional[dict]:
        """
        Look up alternative products for a flagged product.

        Args:
            product_name: Name of the flagged product (e.g. 'Cheerios (Original)')
            brand: Optional brand name for disambiguation

        Returns:
            Dict with flagged_product_name, risk_label, flag_summary, alternatives list
            None if no alternatives found
        """
        # 1. Exact match on product name + brand (most precise)
        if brand:
            row = self._conn.execute(
                "SELECT * FROM alternatives WHERE flagged_product_name = ? AND LOWER(flagged_brand) = ?",
                (product_name, brand.lower().strip()),
            ).fetchone()
            if row:
                return self._build_alternatives_result(row)

        # 2. Exact match on product name only
        row = self._conn.execute(
            "SELECT * FROM alternatives WHERE flagged_product_name = ?",
            (product_name,),
        ).fetchone()
        if row:
            return self._build_alternatives_result(row)

        # 3. Case-insensitive exact match
        row = self._conn.execute(
            "SELECT * FROM alternatives WHERE LOWER(flagged_product_name) = ?",
            (product_name.lower(),),
        ).fetchone()
        if row:
            return self._build_alternatives_result(row)

        # 4. Brand + word match (e.g. "Coca-Cola" + "Original" matches "Coca-Cola Classic")
        if brand:
            brand_lower = brand.lower().strip()
            name_words = [w for w in product_name.lower().split() if len(w) > 2]
            for word in name_words:
                row = self._conn.execute(
                    "SELECT * FROM alternatives WHERE LOWER(flagged_brand) = ? "
                    "AND LOWER(flagged_product_name) LIKE ?",
                    (brand_lower, f"%{word}%"),
                ).fetchone()
                if row:
                    return self._build_alternatives_result(row)

        # 5. Partial word match (any significant word from product name)
        name_words = [w for w in product_name.lower().split() if len(w) > 3]
        for word in name_words:
            row = self._conn.execute(
                "SELECT * FROM alternatives WHERE LOWER(flagged_product_name) LIKE ?",
                (f"%{word}%",),
            ).fetchone()
            if row:
                return self._build_alternatives_result(row)

        # 6. Brand-only match
        if brand:
            row = self._conn.execute(
                "SELECT * FROM alternatives WHERE LOWER(flagged_brand) = ?",
                (brand.lower().strip(),),
            ).fetchone()
            if row:
                return self._build_alternatives_result(row)

        # 7. Category-based fallback: search all certified products by keyword
        return self._category_fallback(product_name)

    def _category_fallback(self, product_name: str) -> Optional[dict]:
        """
        Fallback: find certified products matching the product name.
        Searches all certified products using keyword matching on
        raw_category and product_name.
        """
        # Get product name keywords for matching
        name_words = set(w.lower() for w in product_name.split() if len(w) > 3)
        stop_words = {"with", "from", "this", "that", "have", "been", "your", "their",
                      "original", "classic", "natural", "organic", "conventional"}
        name_words -= stop_words

        if not name_words:
            return None

        # Query all certified products
        rows = self._conn.execute('''
            SELECT product_name, brand, certification, raw_category
            FROM certified_products
            ORDER BY
                CASE certification
                    WHEN 'Glyphosate Residue Free' THEN 1
                    WHEN 'Clean Label Project Certified' THEN 2
                    WHEN 'USDA Organic' THEN 3
                    WHEN 'EU Organic' THEN 4
                    WHEN 'Canada Organic' THEN 5
                    WHEN 'Soil Association Organic' THEN 6
                    WHEN 'Non-GMO Project Verified' THEN 7
                    ELSE 8
                END
        ''').fetchall()

        if not rows:
            return None

        # Score each certified product by keyword overlap
        scored = []
        for row in rows:
            cert_name = row[0].lower()
            cert_brand = (row[1] or "").lower()
            raw_cat = (row[3] or "").lower()
            cert_text = f"{cert_name} {cert_brand} {raw_cat}"

            # Skip clearly irrelevant categories
            skip_keywords = ["supplement", "wine", "vitamin", "protein powder",
                             "bone broth", "pet food", "personal care"]
            if any(sk in raw_cat for sk in skip_keywords):
                continue

            # Score by keyword overlap
            name_matches = sum(1 for w in name_words if w in cert_text)
            cat_matches = sum(1 for w in name_words if w in raw_cat)
            total_score = name_matches + cat_matches * 2  # Category match weighted higher

            if total_score > 0:
                scored.append((total_score, row))

        # Sort by score (descending)
        scored.sort(key=lambda x: -x[0])

        # Take top 5
        alternatives = []
        for score, row in scored[:5]:
            alternatives.append({
                "name": row[0],
                "brand": row[1] or "",
                "why_better": f"{row[2]} certified",
                "certification": row[2],
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
        """Build result dict from alternatives row."""
        return {
            "lookup_key": row["lookup_key"],
            "flagged_product_name": row["flagged_product_name"],
            "flagged_brand": row["flagged_brand"],
            "risk_label": row["risk_label"],
            "flag_summary": row["flag_summary"],
            "alternatives": json.loads(row["alternatives"]) if row["alternatives"] else [],
        }

    def _build_alternatives_result(self, row) -> dict:
        """Build result dict from alternatives row."""
        return {
            "lookup_key": row["lookup_key"],
            "flagged_product_name": row["flagged_product_name"],
            "flagged_brand": row["flagged_brand"],
            "risk_label": row["risk_label"],
            "flag_summary": row["flag_summary"],
            "alternatives": json.loads(row["alternatives"]) if row["alternatives"] else [],
        }

    def list_ingredients(self) -> list[IngredientDetail]:
        """List all ingredients in the database."""
        rows = self._conn.execute("SELECT * FROM ingredients ORDER BY ingredient_id").fetchall()
        results = []
        for row in rows:
            flag_rows = self._conn.execute(
                "SELECT * FROM regulatory_flags WHERE ingredient_id = ?",
                (row["ingredient_id"],),
            ).fetchall()

            flags = [
                RegulatoryFlag(
                    flag_id=r["flag_id"],
                    ingredient_id=r["ingredient_id"],
                    jurisdiction=r["jurisdiction"],
                    flag_type=r["flag_type"],
                    regulatory_body=r["regulatory_body"],
                    regulation_citation=r["regulation_citation"],
                    source_url=r["source_url"],
                    effective_date=r["effective_date"],
                    compliance_date=r["compliance_date"],
                    notes=r["notes"],
                )
                for r in flag_rows
            ]

            aliases = json.loads(row["aliases"]) if row["aliases"] else []
            flag_types = json.loads(row["flag_types"]) if row["flag_types"] else []

            results.append(IngredientDetail(
                ingredient_id=row["ingredient_id"],
                display_name=row["display_name"],
                aliases=aliases,
                flag_types=flag_types,
                flags=flags,
                ntp_classification=row["ntp_classification"],
                iarc_classification=row["iarc_classification"],
                fda_status=row["fda_status"],
                fda_cfr_citation=row["fda_cfr_citation"],
            ))
        return results

    def list_commodities(self) -> list[CommodityDetail]:
        """List all commodities in the database."""
        rows = self._conn.execute(
            "SELECT * FROM commodities ORDER BY commodity_slug"
        ).fetchall()
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
            ))
        return results
