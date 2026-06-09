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
    ) -> list[WaterQualityResult]:
        return self._water_quality.execute(state, contaminant, water_type)

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

    def scan_barcode(
        self,
        barcode: str,
        contaminant: str = "glyphosate",
    ) -> Optional[IngredientRiskResult]:
        """
        Scan a barcode and return ingredient-based risk assessment.

        Complete flow:
        1. Look up product via Open Food Facts API
        2. Run three-tier risk scoring (product → ingredient → category)
        """
        product = self._off_client.lookup(barcode)
        if not product:
            return None

        food_category = None
        if product.get("categories"):
            from db.database import normalize_category
            for cat in product["categories"]:
                mapped = normalize_category(cat, conn=self._conn)
                if mapped:
                    food_category = mapped
                    break

        return self._ingredient_risk.execute(
            product_name=product["product_name"],
            ingredients=product["ingredients"],
            contaminant=contaminant,
            food_category=food_category,
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
            # Try alias search
            row = self._conn.execute(
                "SELECT * FROM ingredients WHERE display_name LIKE ? "
                "OR aliases LIKE ?",
                (f"%{ingredient_name}%", f"%{ingredient_name}%"),
            ).fetchone()

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
                pesticide_name=r.get("pesticide_name", ""),
                pct_samples_detected=r.get("pct_samples_detected", 0),
                median_detected_ppb=r.get("median_detected_ppb", 0),
                max_detected_ppb=r.get("max_detected_ppb", 0),
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
