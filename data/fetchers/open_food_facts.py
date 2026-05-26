"""
fetchers/open_food_facts.py

Open Food Facts live barcode lookup API.

This is NOT a batch data pipeline — it is a LIVE API that gets called per
product scan. It provides product identification from barcode for the
ResidueIQ scan feature.

API docs: https://openfoodfacts.github.io/api-documentation/
"""

import json
import logging
import time
from pathlib import Path

from fetchers.base import BaseFetcher, SESSION, RAW_DATA_DIR

logger = logging.getLogger(__name__)

# Organic-related label tags used by Open Food Facts
_ORGANIC_LABEL_PREFIXES = (
    "en:organic",
    "en:eu-organic",
    "en:usda-organic",
    "en:ab-agriculture-biologique",
    "en:bio",
    "fr:agriculture-biologique",
    "de:bio",
    "es:agricultura-ecologica",
)

# Rate-limit delay between API calls (seconds)
_RATE_LIMIT_DELAY = 0.5

# Sub-directory for cached barcode lookups
_CACHE_DIR = RAW_DATA_DIR / "openfoodfacts"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


class OpenFoodFactsFetcher(BaseFetcher):
    """
    Live lookup service for Open Food Facts barcode data.
    Does not participate in the batch fetch/parse pipeline.
    """

    SOURCE_NAME = "OpenFoodFacts"

    # ── Batch pipeline stubs (this fetcher is not a batch source) ──────────

    def fetch(self) -> list[Path]:
        """No batch download — API is called per barcode via lookup()."""
        return []

    def parse(self, files: list[Path]) -> list[dict]:
        """No batch parse needed — individual lookups return parsed data."""
        return []

    def run(self) -> dict:
        """No-op for the batch pipeline."""
        return {"inserted": 0, "skipped": 0, "failed": 0}

    # ── Live API methods ──────────────────────────────────────────────────

    def lookup(self, barcode: str) -> dict | None:
        """
        Look up a single product by barcode.

        Returns a dict with keys:
            product_name, brand, categories, image_url,
            is_organic, ingredients, countries, barcode, source

        Returns None if the product is not found or the API fails.
        """
        cached = self._read_cache(barcode)
        if cached is not None:
            return cached

        url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
        try:
            time.sleep(_RATE_LIMIT_DELAY)
            resp = SESSION.get(url, timeout=15)
            if resp.status_code == 404:
                logger.info("Product not found for barcode %s", barcode)
                return None
            resp.raise_for_status()
        except Exception as exc:
            logger.error("OFF lookup failed for barcode %s: %s", barcode, exc)
            return None

        data = resp.json()
        if data.get("status") != 1 or "product" not in data:
            logger.info("No product data returned for barcode %s", barcode)
            return None

        parsed = self._parse_product(data["product"], barcode)
        self._write_cache(barcode, parsed)
        return parsed

    def search(self, query: str, page_size: int = 20) -> list[dict]:
        """
        Search for products by text query.

        Returns a list of parsed product dicts (same structure as lookup).
        """
        url = (
            f"https://world.openfoodfacts.org/cgi/search.pl"
            f"?search_terms={query}&json=1&page_size={page_size}"
        )
        try:
            time.sleep(_RATE_LIMIT_DELAY)
            resp = SESSION.get(url, timeout=15)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("OFF search failed for query '%s': %s", query, exc)
            return []

        data = resp.json()
        products = data.get("products", [])
        results = []
        for prod in products:
            barcode = prod.get("code", "")
            if not barcode:
                continue
            results.append(self._parse_product(prod, barcode))
        return results

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _parse_product(product: dict, barcode: str) -> dict:
        """Extract relevant fields from an OFF product JSON object."""
        labels_tags = product.get("labels_tags", []) or []
        is_organic = any(
            tag.startswith(_ORGANIC_LABEL_PREFIXES)
            for tag in labels_tags
        )

        categories_tags = product.get("categories_tags", []) or []
        categories = product.get("categories", "")
        if categories:
            # OFF returns comma-separated string; normalise to list
            categories = [c.strip() for c in categories.split(",") if c.strip()]
        elif categories_tags:
            # Strip language prefix (e.g. "en:beverages" -> "beverages")
            categories = [
                t.split(":", 1)[-1] if ":" in t else t
                for t in categories_tags
            ]
        else:
            categories = []

        return {
            "barcode": barcode,
            "product_name": product.get("product_name", "") or "",
            "brand": product.get("brands", "") or "",
            "categories": categories,
            "image_url": product.get("image_url", "") or "",
            "is_organic": is_organic,
            "ingredients": product.get("ingredients_text", "") or "",
            "countries": product.get("countries", "") or "",
            "source": "OpenFoodFacts",
        }

    @staticmethod
    def _cache_path(barcode: str) -> Path:
        return _CACHE_DIR / f"{barcode}.json"

    def _read_cache(self, barcode: str) -> dict | None:
        path = self._cache_path(barcode)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to read cache for %s: %s", barcode, exc)
        return None

    def _write_cache(self, barcode: str, data: dict) -> None:
        path = self._cache_path(barcode)
        try:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to write cache for %s: %s", barcode, exc)
