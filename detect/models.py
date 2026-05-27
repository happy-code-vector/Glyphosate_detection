from dataclasses import dataclass


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