"""
detect/open_food_facts.py

Open Food Facts live barcode lookup API.

This is a RUNTIME service for product identification — not part of the
batch data pipeline. Used by DetectionEngine.scan_barcode() to fetch
product metadata (name, ingredients, categories) from a barcode.

API docs: https://openfoodfacts.github.io/api-documentation/
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

# Cache directory for barcode lookups
_CACHE_DIR = Path(__file__).parent.parent / "data" / "raw_data" / "openfoodfacts"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _build_session() -> requests.Session:
    """Build HTTP session with retry logic."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "ResidueIQ/1.0 (barcode-scanner)"
    })
    return session


_SESSION = _build_session()


class OpenFoodFactsClient:
    """
    Live lookup service for Open Food Facts barcode data.
    Not part of the batch pipeline — used at runtime for product identification.
    """

    def lookup(self, barcode: str) -> Optional[dict]:
        """
        Look up a single product by barcode.

        Returns a dict with keys:
            barcode, product_name, brand, categories, image_url,
            is_organic, ingredients, countries, source

        Returns None if the product is not found or the API fails.
        """
        cached = self._read_cache(barcode)
        if cached is not None:
            return cached

        url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
        try:
            time.sleep(_RATE_LIMIT_DELAY)
            resp = _SESSION.get(url, timeout=15)
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
            resp = _SESSION.get(url, timeout=15)
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
            categories = [c.strip() for c in categories.split(",") if c.strip()]
        elif categories_tags:
            categories = [
                t.split(":", 1)[-1] if ":" in t else t
                for t in categories_tags
            ]
        else:
            categories = []

        # Extract structured ingredients with English IDs
        # OFF provides: {"id": "en:wheat-flour", "text": "farine de blé", "percent": 34.8}
        raw_ingredients = product.get("ingredients", []) or []
        ingredients_list = []
        for ing in raw_ingredients:
            ing_id = ing.get("id", "")
            # Convert "en:wheat-flour" -> "wheat flour"
            if ing_id.startswith("en:"):
                canonical_name = ing_id[3:].replace("-", " ")
            else:
                canonical_name = ing.get("text", "")
            ingredients_list.append({
                "id": ing_id,
                "name": canonical_name,
                "text": ing.get("text", ""),
                "percent": ing.get("percent_estimate") or ing.get("percent"),
                "is_in_taxonomy": ing.get("is_in_taxonomy", 0),
            })

        return {
            "barcode": barcode,
            "product_name": product.get("product_name", "") or "",
            "brand": product.get("brands", "") or "",
            "categories": categories,
            "image_url": product.get("image_url", "") or "",
            "is_organic": is_organic,
            "ingredients_text": product.get("ingredients_text", "") or "",
            "ingredients": ingredients_list,
            "countries": product.get("countries", "") or "",
            "source": "OpenFoodFacts",
        }

    @staticmethod
    def _cache_path(barcode: str) -> Path:
        return _CACHE_DIR / f"{barcode}.json"

    def _read_cache(self, barcode: str) -> Optional[dict]:
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
