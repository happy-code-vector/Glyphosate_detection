"""
data/firestore_store.py
FirestoreDataStore — implements the DataStore protocol using firebase-admin.

Reads from raw Firestore collections (product_tests, category_summaries,
water_tests, international_mrls, etc.) and computes derived views in Python.
No dependency on pre-computed app_* collections.
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

    # ── Source priority / risk helpers ─────────────────────────────────

    _SOURCE_PRIORITY = {"FDA": 3, "CFIA": 2, "EFSA": 1}

    def _source_priority(self, source_name: str) -> int:
        return self._SOURCE_PRIORITY.get(source_name, 0)

    def _compute_risk_level(self, max_ppb: float | None, contaminant: str,
                            food_category: str | None = None) -> str:
        """Compute risk level: ppb vs tolerance/MRL, matching the SQLite view logic."""
        if max_ppb is None or max_ppb <= 0:
            return "none"
        if food_category:
            tol = self.get_tolerance_limit(contaminant, food_category)
            if tol and (tol_ppb := tol.get("tolerance_ppb")) and tol_ppb > 0:
                pct = max_ppb / tol_ppb
                if pct >= 2.0: return "high"
                if pct >= 1.0: return "medium"
                return "low"
            mrl = self.get_strictest_mrl(contaminant, food_category)
            if mrl and (mrl_ppb := mrl.get("mrl_ppb")) and mrl_ppb > 0:
                pct = max_ppb / mrl_ppb
                if pct >= 2.0: return "high"
                if pct >= 1.0: return "medium"
                return "low"
        return "unknown"

    def _compute_product_risk(self, row: dict) -> str:
        """Compute product risk level, matching the SQLite view logic."""
        if row.get("is_grf_certified"):
            return "certified_grf"
        if row.get("is_organic") and row.get("below_detection"):
            return "organic_clean"
        if row.get("is_organic"):
            return "organic_detected"
        if row.get("below_detection"):
            return "none"
        ppb = row.get("measured_ppb")
        if ppb is None or ppb <= 0:
            return "none"
        food_cat = row.get("food_category")
        contam = row.get("contaminant", "glyphosate")
        if food_cat:
            tol = self.get_tolerance_limit(contam, food_cat)
            if tol and (tol_ppb := tol.get("tolerance_ppb")) and tol_ppb > 0:
                pct = ppb / tol_ppb
                if pct >= 2.0: return "high"
                if pct >= 1.0: return "medium"
                return "low"
        return "unknown"

    def _load_aliases(self) -> dict[str, str]:
        """Load and cache category aliases (alias → canonical_key)."""
        if self._aliases_cache is None:
            docs = self._get_collection("category_aliases").stream()
            self._aliases_cache = {
                doc.id: doc.to_dict().get("canonical_key", doc.id)
                for doc in docs
            }
        return self._aliases_cache

    def _category_exists(self, name: str) -> bool:
        """Check if a food category exists (limit 1 for speed)."""
        docs = self._get_collection("category_summaries").where(
            "food_category", "==", name
        ).limit(1).stream()
        return any(True for _ in docs)

    def _resolve_category(self, name: str) -> str:
        """Resolve user-provided category name to canonical form.

        Uses targeted indexed queries — never fetches the full collection.
        """
        aliases = self._load_aliases()
        lower = name.lower().strip()

        # 1. Exact match (indexed, limit 1)
        if self._category_exists(name):
            return name

        # 2. Alias lookup
        if lower in aliases:
            canonical = aliases[lower]
            if self._category_exists(canonical):
                return canonical

        # 3. Singular/plural — try each variant with a targeted query
        variants = []
        if lower.endswith("ies"):
            variants.append(lower[:-3] + "y")
        if lower.endswith("es"):
            variants.append(lower[:-2])
        if lower.endswith("s") and not lower.endswith("ss"):
            variants.append(lower[:-1])
        if not lower.endswith("s"):
            variants.append(lower + "s")
            if lower.endswith("y"):
                variants.append(lower[:-1] + "ies")

        for v in variants:
            if v == name:
                continue
            if self._category_exists(v):
                return v

        # 4. Case-insensitive — try the canonical aliases (small set)
        for alias, canonical in aliases.items():
            if alias == lower and self._category_exists(canonical):
                return canonical

        return name

    # ── App-facing views ────────────────────────────────────────────────

    def get_food_overview(
        self, food_category: str, contaminant: Optional[str] = None
    ) -> list[dict]:
        resolved = self._resolve_category(food_category)

        # Fast path: try pre-computed app_food_overview collection
        if contaminant:
            doc_id = _sanitize_doc_id(f"{resolved}_{contaminant}")
            doc = self._get_doc("app_food_overview", doc_id)
            if doc:
                return [doc]
        else:
            results = self._query_eq("app_food_overview", "food_category", resolved)
            if results:
                return results

        # Slow path: compute from raw collections
        summaries = self._query_eq("category_summaries", "food_category", resolved)
        if not summaries:
            return []

        # Pick best source per contaminant (source priority + data year)
        best: dict[str, dict] = {}
        for s in summaries:
            contam = s.get("contaminant", "")
            if contaminant and contam != contaminant:
                continue
            key = contam
            if key not in best or (
                self._source_priority(s.get("source_name", "")),
                s.get("data_year", 0),
            ) > (
                self._source_priority(best[key].get("source_name", "")),
                best[key].get("data_year", 0),
            ):
                best[key] = s

        if not best:
            return []

        # Product stats per contaminant
        all_products = self._query_eq("product_tests", "food_category", resolved)
        product_stats: dict[str, dict] = {}
        for p in all_products:
            contam = p.get("contaminant", "")
            if contam not in product_stats:
                product_stats[contam] = {
                    "total": 0, "with_detection": 0,
                    "ppb_sum": 0.0, "ppb_count": 0, "max_ppb": 0.0,
                }
            ps = product_stats[contam]
            ps["total"] += 1
            if not p.get("below_detection"):
                ps["with_detection"] += 1
            ppb = p.get("measured_ppb")
            if ppb is not None:
                ps["ppb_sum"] += ppb
                ps["ppb_count"] += 1
                ps["max_ppb"] = max(ps["max_ppb"], ppb)

        # Certified product count for this category
        all_certs = self._query_eq("certified_products", "food_category", resolved)
        cert_count = len(all_certs)

        # Build result dicts
        results = []
        for contam, s in best.items():
            ps = product_stats.get(contam, {})
            max_ppb = s.get("max_ppb")
            results.append({
                "food_category": resolved,
                "contaminant": contam,
                "best_source": s.get("source_name", ""),
                "best_data_year": s.get("data_year"),
                "detection_rate": s.get("detection_rate"),
                "avg_ppb": s.get("avg_ppb"),
                "max_ppb": max_ppb,
                "samples_total": s.get("samples_total"),
                "samples_detected": s.get("samples_detected"),
                "risk_level": self._compute_risk_level(max_ppb, contam, resolved),
                "confidence": s.get("confidence"),
                "total_products_tested": ps.get("total", 0),
                "products_with_detection": ps.get("with_detection", 0),
                "avg_product_ppb": round(ps["ppb_sum"] / ps["ppb_count"], 1) if ps.get("ppb_count") else 0,
                "max_product_ppb": ps.get("max_ppb", 0),
                "certified_products_available": cert_count,
            })

        return results

    def get_product_lookup(
        self, query: str, contaminant: Optional[str] = None
    ) -> list[dict]:
        # Fast path: try pre-computed app_product_lookup collection
        all_docs = self._query_all("app_product_lookup")
        if all_docs:
            query_lower = query.lower()
            results = []
            for d in all_docs:
                if query_lower not in (d.get("product_name", "").lower()):
                    continue
                if contaminant and d.get("contaminant") != contaminant:
                    continue
                results.append(d)
            if results:
                return results

        # Slow path: compute from raw product_tests
        all_docs = self._query_all("product_tests")
        query_lower = query.lower()
        results = []
        for d in all_docs:
            if query_lower not in (d.get("product_name", "").lower()):
                continue
            if contaminant and d.get("contaminant") != contaminant:
                continue
            d["below_detection"] = bool(d.get("below_detection"))
            d["is_organic"] = bool(d.get("is_organic"))
            d["is_grf_certified"] = bool(d.get("is_grf_certified"))
            d["risk_level"] = self._compute_product_risk(d)
            results.append(d)
        return results

    def get_water_overview(
        self,
        state: Optional[str] = None,
        contaminant: Optional[str] = None,
        water_type: Optional[str] = None,
    ) -> list[dict]:
        # Fast path: try pre-computed app_water_overview collection
        if contaminant and state:
            doc_id = _sanitize_doc_id(f"{contaminant}_{state}")
            doc = self._get_doc("app_water_overview", doc_id)
            if doc:
                entries = doc.get("entries", [])
                if water_type:
                    entries = [e for e in entries if e.get("water_type") == water_type]
                results = []
                for entry in entries:
                    merged = {"contaminant": doc.get("contaminant"), "state": doc.get("state"), **entry}
                    results.append(merged)
                if results:
                    return results
        else:
            all_docs = self._query_all("app_water_overview")
            if all_docs:
                results = []
                for doc in all_docs:
                    entries = doc.get("entries", [])
                    for entry in entries:
                        merged = {"contaminant": doc.get("contaminant"), "state": doc.get("state"), **entry}
                        if state and merged.get("state") != state:
                            continue
                        if contaminant and merged.get("contaminant") != contaminant:
                            continue
                        if water_type and merged.get("water_type") != water_type:
                            continue
                        results.append(merged)
                if results:
                    return results

        # Slow path: compute from raw water_tests
        all_tests = self._query_all("water_tests")
        rows = [d for d in all_tests if d.get("is_aggregate")]

        if state:
            rows = [d for d in rows if d.get("state") == state]
        if contaminant:
            rows = [d for d in rows if d.get("contaminant") == contaminant]
        if water_type:
            rows = [d for d in rows if d.get("water_type") == water_type]

        all_tolerances = self._query_eq("tolerance_limits", "food_category", "drinking_water")
        epa_mcl = {
            d.get("contaminant"): d.get("tolerance_ppb")
            for d in all_tolerances
            if d.get("source") == "EPA_MCL" and (d.get("tolerance_ppb") or 0) > 0
        }

        results = []
        for d in rows:
            contam = d.get("contaminant", "")
            max_ppb = d.get("max_ppb")
            mcl_ppb = epa_mcl.get(contam)
            pct_of_mcl = None
            if mcl_ppb and mcl_ppb > 0 and max_ppb is not None:
                pct_of_mcl = round(max_ppb / mcl_ppb * 100, 1)

            results.append({
                "contaminant": contam,
                "state": d.get("state"),
                "water_type": d.get("water_type"),
                "source_name": d.get("source_name"),
                "report_label": d.get("report_label"),
                "data_year": d.get("data_year"),
                "samples_total": d.get("samples_total"),
                "samples_detected": d.get("samples_detected"),
                "detection_rate": d.get("detection_rate"),
                "avg_ppb": d.get("avg_ppb"),
                "max_ppb": max_ppb,
                "epa_mcl_ppb": mcl_ppb,
                "pct_of_mcl": pct_of_mcl,
            })

        return results

    def get_international_comparison(
        self, food_category: str, contaminant: str = "glyphosate"
    ) -> list[dict]:
        # Fast path: try pre-computed app_international_comparison collection
        doc_id = _sanitize_doc_id(f"{food_category}_{contaminant}")
        doc = self._get_doc("app_international_comparison", doc_id)
        if doc:
            entries = doc.get("entries", [])
            return [
                {"food_category": doc.get("food_category"), "contaminant": doc.get("contaminant"), **entry}
                for entry in entries
            ]

        # Slow path: compute from raw international_mrls
        all_mrls = self._query_eq("international_mrls", "food_category", food_category)
        mrls = [d for d in all_mrls if d.get("pesticide") == contaminant]
        if not mrls:
            return []

        summaries = self._query_eq("category_summaries", "food_category", food_category)
        measured_max = None
        detection_rate = None
        for s in summaries:
            if s.get("contaminant") == contaminant:
                measured_max = s.get("max_ppb")
                detection_rate = s.get("detection_rate")
                break

        results = []
        for mrl in mrls:
            mrl_ppb = mrl.get("mrl_ppb")
            pct_of_mrl = None
            if mrl_ppb and mrl_ppb > 0 and measured_max is not None:
                pct_of_mrl = round(measured_max / mrl_ppb * 100, 1)

            results.append({
                "food_category": food_category,
                "contaminant": contaminant,
                "country_region": mrl.get("country_region"),
                "mrl_ppm": mrl.get("mrl_ppm"),
                "mrl_ppb": mrl_ppb,
                "regulatory_body": mrl.get("regulatory_body"),
                "source_url": mrl.get("source_url"),
                "detection_rate": detection_rate,
                "measured_max_ppb": measured_max,
                "pct_of_mrl": pct_of_mrl,
            })

        results.sort(key=lambda d: d.get("mrl_ppb") or 0)
        return results

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
