"""
data/firestore_store.py
FirestoreDataStore — implements the DataStore protocol using firebase-admin.

Reads from the collections created by data/migrate_to_firestore.py:
  - Raw tables: product_tests, category_summaries, water_tests, etc.
  - Pre-computed views: app_food_overview, app_product_lookup,
    app_international_comparison, app_water_overview, app_regulatory_limits
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _sanitize_doc_id(value: str) -> str:
    """Mirror the migration script's doc-ID sanitizer."""
    return value.replace("/", "_").replace("\\", "_")


class FirestoreDataStore:
    """Firestore-backed DataStore.

    Uses the pre-computed app_* collections for overview queries and
    raw collections for detail lookups. Handles Firestore's query
    limitations (no LIKE, no JOIN) by filtering client-side where needed.
    """

    def __init__(
        self,
        cred_path: Optional[str] = None,
        database_id: str = "purityiq",
    ):
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
        except ImportError:
            raise ImportError(
                "firebase-admin not installed. Run: pip install firebase-admin>=6.2.0"
            )

        # Resolve credential path
        if cred_path is None:
            cred_path = str(
                Path(__file__).parent.parent / "firebase-service-account.json"
            )

        if not os.path.exists(cred_path):
            raise FileNotFoundError(
                f"Firebase credentials not found: {cred_path}\n"
                "Download from Firebase Console → Project Settings → Service Accounts"
            )

        # Initialize app (idempotent — skip if already initialized)
        try:
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        except ValueError:
            pass  # Already initialized

        self._db = firestore.client(database_id=database_id)
        self._aliases_cache: Optional[dict[str, str]] = None

    # ── helpers ─────────────────────────────────────────────────────────

    def _get_collection(self, name: str):
        return self._db.collection(name)

    def _get_doc(self, collection: str, doc_id: str) -> Optional[dict]:
        doc = self._get_collection(collection).document(doc_id).get()
        if doc.exists:
            return doc.to_dict()
        return None

    def _query_eq(self, collection: str, field: str, value: Any) -> list[dict]:
        """Simple equality query → list of dicts."""
        docs = self._get_collection(collection).where(field, "==", value).stream()
        return [doc.to_dict() for doc in docs]

    def _query_all(self, collection: str) -> list[dict]:
        """Fetch all documents in a collection."""
        docs = self._get_collection(collection).stream()
        return [doc.to_dict() for doc in docs]

    def _load_aliases(self) -> dict[str, str]:
        """Load and cache category aliases (alias → canonical_key)."""
        if self._aliases_cache is None:
            docs = self._get_collection("category_aliases").stream()
            self._aliases_cache = {
                doc.id: doc.to_dict().get("canonical_key", doc.id)
                for doc in docs
            }
        return self._aliases_cache

    def _resolve_category(self, name: str) -> str:
        """Resolve user-provided category name to canonical form."""
        aliases = self._load_aliases()
        lower = name.lower().strip()

        # 1. Check if it exists in app_food_overview
        doc_id = _sanitize_doc_id(f"{name}_glyphosate")
        if self._get_doc("app_food_overview", doc_id):
            return name

        # 2. Alias lookup
        if lower in aliases:
            canonical = aliases[lower]
            check_id = _sanitize_doc_id(f"{canonical}_glyphosate")
            if self._get_doc("app_food_overview", check_id):
                return canonical

        # 3. Singular/plural
        variants = set()
        variants.add(lower)
        if lower.endswith("ies"):
            variants.add(lower[:-3] + "y")
        if lower.endswith("es"):
            variants.add(lower[:-2])
        if lower.endswith("s") and not lower.endswith("ss"):
            variants.add(lower[:-1])
        if not lower.endswith("s"):
            variants.add(lower + "s")
            if lower.endswith("y"):
                variants.add(lower[:-1] + "ies")

        for v in variants:
            if v == name:
                continue
            check_id = _sanitize_doc_id(f"{v}_glyphosate")
            if self._get_doc("app_food_overview", check_id):
                return v

        return name

    # ── App-facing views ────────────────────────────────────────────────

    def get_food_overview(
        self, food_category: str, contaminant: Optional[str] = None
    ) -> list[dict]:
        resolved = self._resolve_category(food_category)
        # Try doc ID lookup first (fast path)
        if contaminant:
            doc_id = _sanitize_doc_id(f"{resolved}_{contaminant}")
            doc = self._get_doc("app_food_overview", doc_id)
            if doc:
                return [doc]

        # Query by food_category field
        results = self._query_eq("app_food_overview", "food_category", resolved)
        if contaminant:
            results = [r for r in results if r.get("contaminant") == contaminant]
        return results

    def get_product_lookup(
        self, query: str, contaminant: Optional[str] = None
    ) -> list[dict]:
        # Firestore has no LIKE — fetch all and filter client-side
        # For production, consider Algolia or a search index
        all_docs = self._query_all("app_product_lookup")
        query_lower = query.lower()
        results = [d for d in all_docs if query_lower in (d.get("product_name", "").lower())]
        if contaminant:
            results = [r for r in results if r.get("contaminant") == contaminant]
        return results

    def get_water_overview(
        self,
        state: Optional[str] = None,
        contaminant: Optional[str] = None,
        water_type: Optional[str] = None,
    ) -> list[dict]:
        # Try doc ID lookup for contaminant+state
        if contaminant and state:
            doc_id = _sanitize_doc_id(f"{contaminant}_{state}")
            doc = self._get_doc("app_water_overview", doc_id)
            if doc:
                # app_water_overview stores entries as array — flatten
                entries = doc.get("entries", [])
                if water_type:
                    entries = [e for e in entries if e.get("water_type") == water_type]
                # Merge parent fields into each entry
                results = []
                for entry in entries:
                    merged = {
                        "contaminant": doc.get("contaminant"),
                        "state": doc.get("state"),
                        **entry,
                    }
                    results.append(merged)
                return results

        # Fallback: query all and filter
        all_docs = self._query_all("app_water_overview")
        results = []
        for doc in all_docs:
            entries = doc.get("entries", [])
            for entry in entries:
                merged = {
                    "contaminant": doc.get("contaminant"),
                    "state": doc.get("state"),
                    **entry,
                }
                if state and merged.get("state") != state:
                    continue
                if contaminant and merged.get("contaminant") != contaminant:
                    continue
                if water_type and merged.get("water_type") != water_type:
                    continue
                results.append(merged)
        return results

    def get_international_comparison(
        self, food_category: str, contaminant: str = "glyphosate"
    ) -> list[dict]:
        doc_id = _sanitize_doc_id(f"{food_category}_{contaminant}")
        doc = self._get_doc("app_international_comparison", doc_id)
        if doc:
            entries = doc.get("entries", [])
            # Merge parent fields
            return [
                {
                    "food_category": doc.get("food_category"),
                    "contaminant": doc.get("contaminant"),
                    **entry,
                }
                for entry in entries
            ]
        return []

    # ── Raw table reads ─────────────────────────────────────────────────

    def get_product_tests(
        self, product_name: str, contaminant: str
    ) -> Optional[dict]:
        # Firestore has no LIKE — query by contaminant and filter client-side
        docs = self._query_eq("product_tests", "contaminant", contaminant)
        name_lower = product_name.lower()
        matches = [d for d in docs if name_lower in d.get("product_name", "").lower()]
        if not matches:
            return None
        # Sort by data_year desc
        matches.sort(key=lambda d: d.get("data_year", 0), reverse=True)
        return matches[0]

    def get_category_summaries(
        self,
        food_category: str,
        contaminant: str,
        source_priority: Optional[str] = None,
    ) -> Optional[dict]:
        # Query by food_category + contaminant
        docs = self._query_eq("category_summaries", "food_category", food_category)
        docs = [d for d in docs if d.get("contaminant") == contaminant]
        if not docs:
            return None

        # Source priority (same as SQLite)
        priority_map = {"FDA": 3, "CFIA": 2, "EFSA": 1}
        docs.sort(
            key=lambda d: (
                priority_map.get(d.get("source_name", ""), 0),
                d.get("data_year", 0),
            ),
            reverse=True,
        )
        return docs[0]

    def get_biomonitoring(
        self, analyte: Optional[str] = None, cycle: Optional[str] = None
    ) -> list[dict]:
        if analyte:
            results = self._query_eq("biomonitoring", "analyte", analyte)
        else:
            results = self._query_all("biomonitoring")
        if cycle:
            results = [r for r in results if r.get("cycle") == cycle]
        results.sort(key=lambda d: (d.get("analyte", ""), d.get("cycle", "")))
        return results

    def get_ingredient(
        self,
        ingredient_id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Optional[dict]:
        if ingredient_id:
            doc = self._get_doc("ingredients", ingredient_id)
            if doc:
                return doc

        if name:
            name_lower = name.lower()
            all_ingredients = self._query_all("ingredients")
            for ing in all_ingredients:
                aliases = ing.get("aliases", [])
                if isinstance(aliases, str):
                    try:
                        aliases = json.loads(aliases)
                    except (json.JSONDecodeError, TypeError):
                        aliases = []
                if name_lower in [a.lower() for a in aliases]:
                    return ing

        return None

    def get_regulatory_flags(self, ingredient_id: str) -> list[dict]:
        return self._query_eq("regulatory_flags", "ingredient_id", ingredient_id)

    def get_commodity(self, commodity_slug: str) -> Optional[dict]:
        return self._get_doc("commodities", commodity_slug.lower())

    def get_all_commodities_with_aliases(self) -> list[dict]:
        all_commodities = self._query_all("commodities")
        return [
            d for d in all_commodities
            if d.get("ingredient_aliases")
        ]

    def get_alternatives(
        self, product_name: str, brand: Optional[str] = None
    ) -> Optional[dict]:
        # 1. Exact match on product name + brand
        if brand:
            docs = self._query_eq("alternatives", "flagged_product_name", product_name)
            brand_lower = brand.lower().strip()
            for d in docs:
                if (d.get("flagged_brand") or "").lower() == brand_lower:
                    return d

        # 2. Exact match on product name
        docs = self._query_eq("alternatives", "flagged_product_name", product_name)
        if docs:
            return docs[0]

        return None

    def get_alternatives_case_insensitive(self, product_name: str) -> Optional[dict]:
        all_docs = self._query_all("alternatives")
        target = product_name.lower()
        for d in all_docs:
            if (d.get("flagged_product_name") or "").lower() == target:
                return d
        return None

    def get_alternatives_by_brand_word(
        self, brand: str, word: str
    ) -> Optional[dict]:
        all_docs = self._query_all("alternatives")
        brand_lower = brand.lower().strip()
        for d in all_docs:
            if (d.get("flagged_brand") or "").lower() == brand_lower:
                if word in (d.get("flagged_product_name") or "").lower():
                    return d
        return None

    def get_alternatives_by_word(self, word: str) -> Optional[dict]:
        all_docs = self._query_all("alternatives")
        for d in all_docs:
            if word in (d.get("flagged_product_name") or "").lower():
                return d
        return None

    def get_alternatives_by_brand(self, brand: str) -> Optional[dict]:
        all_docs = self._query_all("alternatives")
        brand_lower = brand.lower().strip()
        for d in all_docs:
            if (d.get("flagged_brand") or "").lower() == brand_lower:
                return d
        return None

    def get_certified_products(self) -> list[dict]:
        results = self._query_all("certified_products")
        cert_order = {
            "Glyphosate Residue Free": 1,
            "Clean Label Project Certified": 2,
            "USDA Organic": 3,
            "EU Organic": 4,
            "Canada Organic": 5,
            "Soil Association Organic": 6,
            "Non-GMO Project Verified": 7,
        }
        results.sort(key=lambda d: cert_order.get(d.get("certification", ""), 8))
        return results

    def get_all_ingredients(self) -> list[dict]:
        results = self._query_all("ingredients")
        results.sort(key=lambda d: d.get("ingredient_id", ""))
        return results

    def get_all_commodities(self) -> list[dict]:
        results = self._query_all("commodities")
        results.sort(key=lambda d: d.get("commodity_slug", ""))
        return results

    # ── Regulatory / benchmark lookups ──────────────────────────────────

    def get_category_aliases(self) -> list[dict]:
        docs = self._get_collection("category_aliases").stream()
        return [
            {"alias": doc.id, "canonical_key": doc.to_dict().get("canonical_key", doc.id)}
            for doc in docs
        ]

    def get_category_alias(self, alias: str) -> Optional[str]:
        doc = self._get_doc("category_aliases", alias.lower())
        if doc:
            return doc.get("canonical_key")
        return None

    def get_tolerance_limit(
        self, contaminant: str, food_category: str
    ) -> Optional[dict]:
        resolved = self.resolve_benchmark_category(food_category, "tolerance_limits")
        docs = self._query_eq("tolerance_limits", "contaminant", contaminant.lower())
        matches = [
            d for d in docs
            if d.get("food_category", "").lower() == resolved.lower()
            and (d.get("tolerance_ppb") or 0) > 0
        ]
        if not matches:
            return None
        matches.sort(key=lambda d: d.get("tolerance_ppb", float("inf")))
        return matches[0]

    def get_all_tolerance_limits(
        self, contaminant: str, food_category: str
    ) -> list[dict]:
        resolved = self.resolve_benchmark_category(food_category, "tolerance_limits")
        docs = self._query_eq("tolerance_limits", "contaminant", contaminant)
        return [d for d in docs if d.get("food_category") == resolved]

    def get_strictest_mrl(
        self, contaminant: str, food_category: str
    ) -> Optional[dict]:
        resolved = self.resolve_benchmark_category(food_category, "international_mrls")
        docs = self._query_eq("international_mrls", "pesticide", contaminant.lower())
        matches = [
            d for d in docs
            if d.get("food_category", "").lower() == resolved.lower()
            and (d.get("mrl_ppb") or 0) > 0
        ]
        if not matches:
            return None
        matches.sort(key=lambda d: d.get("mrl_ppb", float("inf")))
        return matches[0]

    def get_consumption_tier(self, food_category: str) -> Optional[str]:
        doc = self._get_doc("commodities", food_category)
        if doc:
            return doc.get("consumption_tier")
        return None

    def get_contaminant_type(self, contaminant: str) -> Optional[str]:
        # Try ingredients table
        doc = self._get_doc("ingredients", contaminant.lower().replace(" ", "_"))
        if doc and doc.get("contaminant_type"):
            return doc["contaminant_type"]

        # Try contaminants.py registry
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from contaminants import CONTAMINANTS
            config = CONTAMINANTS.get(contaminant.lower())
            if config:
                return config.get("type", "unknown")
        except ImportError:
            pass

        # Infer from name
        _HEAVY_METALS = frozenset({
            "lead", "inorganic_arsenic", "cadmium", "mercury", "arsenic",
        })
        if contaminant.lower() in _HEAVY_METALS:
            return "heavy_metal"
        return "pesticide"

    def get_all_contaminants_for_category(
        self, food_category: str, source_priority_sql: str
    ) -> list[dict]:
        # Fetch all category_summaries for this food_category
        docs = self._query_eq("category_summaries", "food_category", food_category)

        # Filter to those with detections
        docs = [d for d in docs if (d.get("detection_rate") or 0) > 0]

        # Build source priority from the SQL string (parse CASE values)
        priority_map = self._parse_source_priority(source_priority_sql)

        # Group by contaminant, pick best source
        best: dict[str, dict] = {}
        for d in docs:
            contam = d.get("contaminant", "")
            priority = priority_map.get(d.get("source_name", ""), 0)
            year = d.get("data_year", 0)
            if contam not in best or (priority, year) > (
                priority_map.get(best[contam].get("source_name", ""), 0),
                best[contam].get("data_year", 0),
            ):
                best[contam] = d

        results = list(best.values())
        results.sort(key=lambda d: d.get("detection_rate", 0), reverse=True)
        return results

    def _parse_source_priority(self, sql: str) -> dict[str, int]:
        """Extract source priority map from CASE SQL string."""
        priority = {}
        pattern = r"WHEN\s+'([^']+)'\s+THEN\s+(\d+)"
        for match in re.finditer(pattern, sql):
            source = match.group(1)
            value = int(match.group(2))
            priority[source] = value
        return priority

    def resolve_benchmark_category(self, food_category: str, table: str) -> str:
        fc = food_category.strip()
        aliases = self._load_aliases()

        candidates = [fc]
        if fc.endswith("s"):
            candidates.append(fc[:-1])
        else:
            candidates.append(fc + "s")
        if fc.endswith("ies"):
            candidates.append(fc[:-3] + "y")
        elif fc.endswith("es"):
            candidates.append(fc[:-2])
        if "_" in fc:
            candidates.append(fc.replace("_", " "))
        if " " in fc:
            candidates.append(fc.replace(" ", "_"))

        # Reverse alias lookup
        for alias, canonical in aliases.items():
            if canonical == fc:
                candidates.append(alias)

        # Check which candidates exist in the benchmark collection
        lower_set = set()
        for c in candidates:
            cl = c.lower()
            if cl in lower_set:
                continue
            lower_set.add(cl)

            # Try as doc ID first
            doc = self._get_doc(table, c)
            if doc:
                return doc.get("food_category", c)

        # Fallback: query and filter
        all_docs = self._query_all(table)
        candidate_lower = {c.lower() for c in candidates}
        for d in all_docs:
            if d.get("food_category", "").lower() in candidate_lower:
                return d["food_category"]

        return fc

    # ── Lifecycle ───────────────────────────────────────────────────────

    def close(self) -> None:
        # firebase-admin doesn't have an explicit close; nothing to do
        pass
