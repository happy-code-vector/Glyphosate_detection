from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RegulatoryEntry:
    source: str
    tolerance_ppb: float
    regulation_reference: str
    pct_of_tolerance: float | None


@dataclass
class FoodRiskResult:
    food_category: str
    contaminant: str
    best_source: str
    data_year: int
    detection_rate: float
    avg_ppb: float | None
    max_ppb: float | None
    samples_total: int
    samples_detected: int
    risk_level: str
    confidence: str
    total_products_tested: int
    products_with_detection: int
    certified_products_available: int
    regulatory_comparison: list[RegulatoryEntry]


@dataclass
class ProductResult:
    product_name: str
    food_category: str
    contaminant: str
    source_name: str
    report_label: str
    data_year: int
    measured_ppb: float | None
    below_detection: bool
    is_organic: bool
    is_grf_certified: bool
    risk_level: str
    confidence: str
    source_url: str | None


@dataclass
class WaterQualityResult:
    state: str
    contaminant: str
    water_type: str
    source_name: str
    data_year: int
    detection_rate: float | None
    avg_ppb: float | None
    max_ppb: float | None
    samples_total: int | None
    epa_mcl_ppb: float | None
    pct_of_mcl: float | None


@dataclass
class InternationalComparisonEntry:
    country_region: str
    mrl_ppb: float
    regulatory_body: str | None
    measured_max_ppb: float | None
    pct_of_mrl: float | None


@dataclass
class InternationalComparisonResult:
    food_category: str
    contaminant: str
    entries: list[InternationalComparisonEntry]


# ═════════════════════════════════════════════
# REGULATORY MODELS (ingredients, flags, commodities)
# ═════════════════════════════════════════════

@dataclass
class RegulatoryFlag:
    """A jurisdiction-specific regulatory flag for an ingredient."""
    flag_id: str
    ingredient_id: str
    jurisdiction: str
    flag_type: str
    regulatory_body: str
    regulation_citation: str | None
    source_url: str
    effective_date: str | None
    compliance_date: str | None
    notes: str | None


@dataclass
class IngredientDetail:
    """Master reference for a flagged ingredient."""
    ingredient_id: str
    display_name: str
    aliases: list[str]
    flag_types: list[str]
    flags: list[RegulatoryFlag]
    ntp_classification: str | None
    iarc_classification: str | None  # Per Addendum A: now populated
    fda_status: str | None
    fda_cfr_citation: str | None


@dataclass
class CommodityResidue:
    """Pesticide residue data for a single commodity-pesticide pair."""
    pesticide_name: str
    pct_samples_detected: float
    median_detected_ppb: float
    max_detected_ppb: float
    epa_tolerance_ppb: float
    tolerance_revoked: bool
    pdp_year: int


@dataclass
class CommodityDetail:
    """Commodity with residue data and ingredient aliases."""
    commodity_slug: str
    display_name: str
    ingredient_aliases: list[str]
    pdp_commodity_code: str | None
    pdp_year_latest: int | None
    residues: list[CommodityResidue]
    dirty_dozen: bool


@dataclass
class AlternativeProduct:
    """A suggested alternative to a flagged product."""
    name: str
    brand: str | None
    upc: str | None
    why_better: str | None
    where_to_buy: str | None


@dataclass
class ContaminantDetail:
    """Risk assessment for a single contaminant in a food category.

    Compares measured levels against regulatory limits (MRLs/tolerances).
    Uses the strictest available limit from international_mrls or tolerance_limits.
    """
    contaminant: str
    contaminant_type: str  # 'pesticide', 'heavy_metal', 'food_dye', 'additive'
    food_category: str
    # Measured data from category_summaries
    measured_avg_ppb: float | None
    measured_max_ppb: float | None
    detection_rate: float  # 0.0-1.0
    samples_total: int
    samples_detected: int
    source_name: str
    data_year: int | None
    # Regulatory comparison
    mrl_ppb: float | None  # Strictest MRL from international_mrls
    mrl_source: str | None  # Country/region that set the MRL
    tolerance_ppb: float | None  # From tolerance_limits (EPA, FDA)
    tolerance_source: str | None
    # Risk assessment
    pct_of_mrl: float | None  # measured_max / mrl * 100
    pct_of_tolerance: float | None  # measured_max / tolerance * 100
    risk_level: str  # 'none', 'low', 'medium', 'high', 'unknown'
    risk_reason: str  # Human-readable explanation
    confidence: str  # 'high', 'medium', 'low'
    # Detection frequency (shown when risk_level is 'unknown')
    detection_frequency: str | None  # 'high', 'medium', 'low', 'none'


@dataclass
class ContaminantReport:
    """Full multi-contaminant report for a food category or product."""
    food_category: str
    contaminant: str | None  # None = all contaminants
    contaminants: list[ContaminantDetail]
    total_detected: int  # How many contaminants have detections
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    overall_risk_level: str  # Worst risk level across all contaminants
    overall_score: float  # 0.0-1.0


@dataclass
class ProductScanResult:
    """Full result of a barcode scan — includes flags and residue data."""
    upc: str
    name: str
    brand: str | None
    ingredients_raw: str
    ingredients_parsed: list[str]
    commodities_matched: list[str]
    flags: list[RegulatoryFlag]
    data_confidence: str  # 'high', 'medium', 'low'
    # Risk data from ingredient scoring
    risk_level: str = "unknown"
    score: float = 0.5
    tier_used: str = "none"
    contaminant: str = "glyphosate"
    ingredient_scores: list = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Multi-contaminant report
    contaminant_report: ContaminantReport | None = None