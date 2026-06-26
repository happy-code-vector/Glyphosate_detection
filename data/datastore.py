"""
data/datastore.py
DataStore protocol — abstracts database reads so the detection engine
works with SQLite, Firestore, or any future backend without code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


# ── Protocol ────────────────────────────────────────────────────────────────

@runtime_checkable
class DataStore(Protocol):
    """Read-only interface the detection engine needs from a database.

    Every method returns plain dicts (or lists of dicts). The engine
    converts these into dataclasses (FoodRiskResult, ProductResult, etc.)
    at the boundary.

    Implementations: SqliteDataStore, FirestoreDataStore.
    """

    # ── App-facing views (pre-computed collections in Firestore) ─────────

    def get_food_overview(
        self, food_category: str, contaminant: Optional[str] = None
    ) -> list[dict]:
        """Best-source stats per food category per contaminant."""
        ...

    def get_product_lookup(
        self, query: str, contaminant: Optional[str] = None
    ) -> list[dict]:
        """Search products by name (LIKE match)."""
        ...

    def get_water_overview(
        self,
        state: Optional[str] = None,
        contaminant: Optional[str] = None,
        water_type: Optional[str] = None,
    ) -> list[dict]:
        """Aggregated water quality data by state."""
        ...

    def get_international_comparison(
        self, food_category: str, contaminant: str = "glyphosate"
    ) -> list[dict]:
        """MRL comparison entries across countries."""
        ...

    # ── Raw table reads ─────────────────────────────────────────────────

    def get_product_tests(
        self, product_name: str, contaminant: str
    ) -> Optional[dict]:
        """Single best product test match (LIKE, ordered by year desc)."""
        ...

    def get_category_summaries(
        self,
        food_category: str,
        contaminant: str,
        source_priority: Optional[str] = None,
    ) -> Optional[dict]:
        """Single best category summary (source-priority ordered)."""
        ...

    def get_biomonitoring(
        self, analyte: Optional[str] = None, cycle: Optional[str] = None
    ) -> list[dict]:
        """CDC NHANES biomonitoring data."""
        ...

    def get_ingredient(
        self,
        ingredient_id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Optional[dict]:
        """Look up ingredient by ID or alias name."""
        ...

    def get_regulatory_flags(self, ingredient_id: str) -> list[dict]:
        """All regulatory flags for an ingredient."""
        ...

    def get_commodity(self, commodity_slug: str) -> Optional[dict]:
        """Single commodity by slug."""
        ...

    def get_all_commodities_with_aliases(self) -> list[dict]:
        """All commodities that have ingredient_aliases (for matching)."""
        ...

    def get_plu(self, plu_code: str) -> Optional[dict]:
        """Single PLU code -> produce row (plu_codes table)."""
        ...

    def get_plu_by_commodity(self, commodity_slug: str) -> list[dict]:
        """All PLU codes mapped to a commodity slug."""
        ...

    def get_alternatives(
        self, product_name: str, brand: Optional[str] = None
    ) -> Optional[dict]:
        """Exact match alternatives lookup."""
        ...

    def get_alternatives_case_insensitive(self, product_name: str) -> Optional[dict]:
        """Case-insensitive alternatives lookup."""
        ...

    def get_alternatives_by_brand_word(
        self, brand: str, word: str
    ) -> Optional[dict]:
        """Brand + word match alternatives."""
        ...

    def get_alternatives_by_word(self, word: str) -> Optional[dict]:
        """Partial word match alternatives."""
        ...

    def get_alternatives_by_brand(self, brand: str) -> Optional[dict]:
        """Brand-only match alternatives."""
        ...

    def get_certified_products(self) -> list[dict]:
        """All certified products (for category fallback)."""
        ...

    def get_all_ingredients(self) -> list[dict]:
        """All ingredients (for list_ingredients)."""
        ...

    def get_all_commodities(self) -> list[dict]:
        """All commodities (for list_commodities)."""
        ...

    # ── Regulatory / benchmark lookups ──────────────────────────────────

    def get_category_aliases(self) -> list[dict]:
        """All category aliases (alias → canonical_key)."""
        ...

    def get_category_alias(self, alias: str) -> Optional[str]:
        """Single alias lookup → canonical_key."""
        ...

    def get_tolerance_limit(
        self, contaminant: str, food_category: str
    ) -> Optional[dict]:
        """Lowest tolerance for contaminant+category."""
        ...

    def get_all_tolerance_limits(
        self, contaminant: str, food_category: str
    ) -> list[dict]:
        """All tolerance entries for contaminant+category (for regulatory comparison)."""
        ...

    def get_strictest_mrl(
        self, contaminant: str, food_category: str
    ) -> Optional[dict]:
        """Strictest (lowest) MRL for contaminant+category."""
        ...

    def get_consumption_tier(self, food_category: str) -> Optional[str]:
        """Consumption tier for a commodity slug."""
        ...

    def get_contaminant_type(self, contaminant: str) -> Optional[str]:
        """Contaminant type (pesticide, heavy_metal, etc.)."""
        ...

    def get_all_contaminants_for_category(
        self, food_category: str, source_priority_sql: str
    ) -> list[dict]:
        """All contaminants with detections for a category (best source per contaminant)."""
        ...

    def resolve_benchmark_category(self, food_category: str, table: str) -> str:
        """Resolve canonical key to actual food_category in a benchmark table."""
        ...

    # ── Lifecycle ───────────────────────────────────────────────────────

    def close(self) -> None:
        """Release resources."""
        ...


# ── Config ──────────────────────────────────────────────────────────────────

@dataclass
class DataStoreConfig:
    """Configuration for creating a DataStore."""
    backend: str = "sqlite"  # "sqlite" or "firestore"
    # SQLite options
    db_path: Optional[str] = None
    # Firestore options
    cred_path: Optional[str] = None
    database_id: str = "purityiq"


# ── Factory ─────────────────────────────────────────────────────────────────

def create_datastore(
    backend: Optional[str] = None,
    db_path: Optional[str] = None,
    cred_path: Optional[str] = None,
    database_id: str = "purityiq",
) -> DataStore:
    """Create a DataStore instance.

    Args:
        backend: "sqlite" or "firestore". Defaults to RESIDUEIQ_BACKEND env var, then "sqlite".
        db_path: Path to SQLite database (SQLite only). Defaults to data/residueiq.db.
        cred_path: Path to Firebase service account JSON (Firestore only).
        database_id: Firestore database ID. Default "purityiq".

    Returns:
        A DataStore implementation.

    Raises:
        ValueError: If backend is unknown or required config is missing.
    """
    backend = backend or os.environ.get("RESIDUEIQ_BACKEND", "sqlite")

    if backend == "sqlite":
        from data.sqlite_store import SqliteDataStore
        return SqliteDataStore(db_path=db_path)

    elif backend == "firestore":
        from data.firestore_store import FirestoreDataStore
        return FirestoreDataStore(cred_path=cred_path, database_id=database_id)

    else:
        raise ValueError(
            f"Unknown backend: {backend!r}. Expected 'sqlite' or 'firestore'."
        )
