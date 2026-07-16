"""HTTP endpoints mapping to DetectionEngine methods.

Endpoints return the engine's existing @dataclass result types directly; FastAPI
serializes them. Protected routes require a valid Firebase App Check token.

Note: ingredient_risk(product_name, ingredients, contaminant) scores a product
from an ingredient *list* — not a clean GET — so it's intentionally omitted here
(it's a lower-level building block that scan_barcode calls internally). Add it
later as a POST if a direct client need arises.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api import deps, security

# /api/health is public (Cloud Run liveness probes carry no App Check token).
public_router = APIRouter(prefix="/api")
router = APIRouter(prefix="/api", dependencies=[Depends(security.verify_appcheck)])


@public_router.get("/health")
def health() -> dict:
    eng = deps.get_engine()
    return {"status": "ok", "contaminants": len(eng.list_ingredients())}


@router.get("/scan/{barcode}")
def scan_barcode(
    barcode: str,
    contaminant: str = Query(..., description="Contaminant slug, e.g. glyphosate"),
):
    """Scan a product barcode -> full risk result (calls Open Food Facts)."""
    try:
        res = deps.get_engine().scan_barcode(barcode, contaminant)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if res is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"No product found for barcode {barcode}")
    return res


@router.get("/food/{category}")
def food_risk(
    category: str,
    contaminant: str | None = Query(default=None, description="Omit for all contaminants"),
):
    res = deps.get_engine().food_risk(category, contaminant)
    if res is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No data for category '{category}' / contaminant '{contaminant}'",
        )
    return res


@router.get("/product")
def product_lookup(
    q: str = Query(..., min_length=2, description="Product name fragment"),
    contaminant: str | None = Query(default=None),
):
    return deps.get_engine().product_lookup(q, contaminant)


@router.get("/water")
def water_quality(
    state: str | None = Query(default=None),
    contaminant: str | None = Query(default=None),
):
    return deps.get_engine().water_quality(state=state, contaminant=contaminant)


@router.get("/contaminants")
def contaminants():
    return deps.get_engine().list_ingredients()
