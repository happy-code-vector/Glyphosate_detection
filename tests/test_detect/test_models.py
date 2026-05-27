import unittest

from detect.models import (
    FoodRiskResult,
    ProductResult,
    WaterQualityResult,
    InternationalComparisonResult,
    InternationalComparisonEntry,
    RegulatoryEntry,
)


class TestModels(unittest.TestCase):
    def test_regulatory_entry(self):
        entry = RegulatoryEntry(
            source="EPA_MCL", tolerance_ppb=700.0,
            regulation_reference="40 CFR 141.60", pct_of_tolerance=50.0
        )
        self.assertEqual(entry.source, "EPA_MCL")
        self.assertEqual(entry.tolerance_ppb, 700.0)

    def test_food_risk_result(self):
        result = FoodRiskResult(
            food_category="oats", contaminant="glyphosate",
            best_source="EWG", data_year=2024, detection_rate=0.8,
            avg_ppb=250.0, max_ppb=1200.0, samples_total=100,
            samples_detected=80, risk_level="high", confidence="high",
            total_products_tested=2, products_with_detection=2,
            certified_products_available=0, regulatory_comparison=[],
        )
        self.assertEqual(result.food_category, "oats")
        self.assertEqual(result.risk_level, "high")

    def test_product_result(self):
        result = ProductResult(
            product_name="Cheerios", food_category="oats",
            contaminant="glyphosate", source_name="FDA",
            report_label="FDA 2023", data_year=2023,
            measured_ppb=730.0, below_detection=False,
            is_organic=False, is_grf_certified=False,
            risk_level="high", confidence="high", source_url="https://example.com",
        )
        self.assertEqual(result.product_name, "Cheerios")
        self.assertFalse(result.below_detection)

    def test_water_quality_result(self):
        result = WaterQualityResult(
            state="California", contaminant="glyphosate",
            water_type="surface", source_name="USGS_WQP",
            data_year=2024, detection_rate=0.75,
            avg_ppb=45.0, max_ppb=500.0, samples_total=200,
            epa_mcl_ppb=700.0, pct_of_mcl=71.4,
        )
        self.assertEqual(result.state, "California")

    def test_international_comparison_result(self):
        entry = InternationalComparisonEntry(
            country_region="EU", mrl_ppb=20000.0,
            regulatory_body="EFSA", measured_max_ppb=1200.0, pct_of_mrl=6.0,
        )
        result = InternationalComparisonResult(
            food_category="oats", contaminant="glyphosate", entries=[entry],
        )
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.entries[0].country_region, "EU")

    def test_none_fields(self):
        result = WaterQualityResult(
            state="Texas", contaminant="glyphosate",
            water_type="ground", source_name="USGS_WQP",
            data_year=2024, detection_rate=None,
            avg_ppb=None, max_ppb=None, samples_total=None,
            epa_mcl_ppb=None, pct_of_mcl=None,
        )
        self.assertIsNone(result.avg_ppb)


if __name__ == "__main__":
    unittest.main()