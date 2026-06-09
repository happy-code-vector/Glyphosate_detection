import json
import sqlite3
import os

SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "db", "schema.sql"
)


def get_schema_sql():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return f.read()


def create_test_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(get_schema_sql())
    return conn


def seed_food_data(conn: sqlite3.Connection):
    conn.execute(
        "INSERT INTO category_summaries "
        "(source_name, source_url, report_label, published_date, data_year, "
        "food_category, raw_category, contaminant, samples_total, samples_detected, "
        "detection_rate, avg_ppb, max_ppb, confidence, dedup_key) "
        "VALUES ('FDA', 'https://example.com', 'FDA 2024', '2024-01-01', 2024, "
        "'oats', 'Oats', 'glyphosate', 100, 80, 0.80, 250.0, 1200.0, 'high', 'test-cs-oats-gly')"
    )
    conn.execute(
        "INSERT INTO category_summaries "
        "(source_name, source_url, report_label, published_date, data_year, "
        "food_category, raw_category, contaminant, samples_total, samples_detected, "
        "detection_rate, avg_ppb, max_ppb, confidence, dedup_key) "
        "VALUES ('FDA', 'https://example.com', 'FDA 2024', '2024-01-01', 2024, "
        "'oats', 'Oats', 'lead', 50, 10, 0.20, 3.5, 12.0, 'high', 'test-cs-oats-lead')"
    )
    conn.execute(
        "INSERT INTO product_tests "
        "(source_name, source_url, report_label, published_date, data_year, "
        "food_category, raw_category, contaminant, product_name, measured_ppb, "
        "below_detection, is_organic, is_grf_certified, confidence, dedup_key) "
        "VALUES ('FDA', 'https://example.com', 'FDA 2023', '2023-01-01', 2023, "
        "'oats', 'Oats', 'glyphosate', 'Cheerios Original', 730.0, "
        "0, 0, 0, 'high', 'test-pt-cheerios')"
    )
    conn.execute(
        "INSERT INTO product_tests "
        "(source_name, source_url, report_label, published_date, data_year, "
        "food_category, raw_category, contaminant, product_name, measured_ppb, "
        "below_detection, is_organic, is_grf_certified, confidence, dedup_key) "
        "VALUES ('FDA', 'https://example.com', 'FDA 2023', '2023-01-01', 2023, "
        "'oats', 'Oats', 'glyphosate', 'Nature Valley Granola', 450.0, "
        "0, 0, 0, 'high', 'test-pt-nature-valley')"
    )
    conn.execute(
        "INSERT INTO product_tests "
        "(source_name, source_url, report_label, published_date, data_year, "
        "food_category, raw_category, contaminant, product_name, measured_ppb, "
        "below_detection, is_organic, is_grf_certified, confidence, dedup_key) "
        "VALUES ('FDA', 'https://example.com', 'FDA 2023', '2023-01-01', 2023, "
        "'oats', 'Oats', 'lead', 'Cheerios Original', 5.2, "
        "0, 0, 0, 'high', 'test-pt-cheerios-lead')"
    )
    conn.execute(
        "INSERT INTO tolerance_limits "
        "(food_category, tolerance_ppm, tolerance_ppb, contaminant, source, "
        "regulation_reference, dedup_key) "
        "VALUES ('oats', 30.0, 30000.0, 'glyphosate', 'EPA_40CFR180.364', "
        "'40 CFR 180.364', 'test-tl-oats-gly')"
    )
    conn.execute(
        "INSERT INTO tolerance_limits "
        "(food_category, tolerance_ppm, tolerance_ppb, contaminant, source, "
        "regulation_reference, dedup_key) "
        "VALUES ('oats', 0.1, 100.0, 'lead', 'EPA_40CFR180', "
        "'EPA Lead Standard', 'test-tl-oats-lead')"
    )
    conn.execute(
        "INSERT INTO international_mrls "
        "(food_category, pesticide, country_region, mrl_ppm, mrl_ppb, "
        "regulatory_body, dedup_key) "
        "VALUES ('oats', 'glyphosate', 'EU', 20.0, 20000.0, "
        "'EFSA', 'test-imrl-oats-eu')"
    )
    conn.execute(
        "INSERT INTO international_mrls "
        "(food_category, pesticide, country_region, mrl_ppm, mrl_ppb, "
        "regulatory_body, dedup_key) "
        "VALUES ('oats', 'glyphosate', 'Canada', 15.0, 15000.0, "
        "'Health Canada', 'test-imrl-oats-ca')"
    )
    conn.commit()


def seed_water_data(conn: sqlite3.Connection):
    conn.execute(
        "INSERT INTO water_tests "
        "(source_name, source_url, report_label, data_year, state, water_type, "
        "contaminant, measured_ppb, below_detection, is_aggregate, samples_total, "
        "samples_detected, detection_rate, avg_ppb, max_ppb, confidence, dedup_key) "
        "VALUES ('USGS_WQP', 'https://example.com', 'WQP 2024', 2024, 'California', "
        "'surface', 'glyphosate', NULL, 0, 1, 200, 150, 0.75, "
        "45.0, 500.0, 'high', 'test-wt-ca-gly')"
    )
    conn.execute(
        "INSERT INTO water_tests "
        "(source_name, source_url, report_label, data_year, state, water_type, "
        "contaminant, measured_ppb, below_detection, is_aggregate, samples_total, "
        "samples_detected, detection_rate, avg_ppb, max_ppb, confidence, dedup_key) "
        "VALUES ('USGS_WQP', 'https://example.com', 'WQP 2024', 2024, 'California', "
        "'surface', 'lead', NULL, 0, 1, 100, 30, 0.30, "
        "8.0, 22.0, 'high', 'test-wt-ca-lead')"
    )
    conn.execute(
        "INSERT INTO tolerance_limits "
        "(food_category, tolerance_ppm, tolerance_ppb, contaminant, source, "
        "regulation_reference, dedup_key) "
        "VALUES ('drinking_water', 0.7, 700.0, 'glyphosate', 'EPA_MCL', "
        "'40 CFR 141.60', 'test-tl-dw-gly')"
    )
    conn.execute(
        "INSERT INTO tolerance_limits "
        "(food_category, tolerance_ppm, tolerance_ppb, contaminant, source, "
        "regulation_reference, dedup_key) "
        "VALUES ('drinking_water', 0.015, 15.0, 'lead', 'EPA_MCL', "
        "'40 CFR 141.80', 'test-tl-dw-lead')"
    )
    conn.commit()


def seed_all(conn: sqlite3.Connection):
    seed_food_data(conn)
    seed_water_data(conn)


def seed_regulatory_data(conn: sqlite3.Connection):
    """Seed ingredients, regulatory_flags, and commodities tables."""
    # Seed ingredient
    conn.execute(
        "INSERT INTO ingredients "
        "(ingredient_id, display_name, aliases, flag_types, flags, "
        "ntp_classification, iarc_classification, fda_status, fda_cfr_citation) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "potassium_bromate",
            "Potassium Bromate",
            json.dumps(["potassium bromate", "bromated flour"]),
            json.dumps(["eu_banned"]),
            json.dumps([{"jurisdiction": "EU", "flag_type": "eu_banned"}]),
            None,
            "Group 2B",
            "permitted",
            "21 CFR 136.110",
        ),
    )
    conn.execute(
        "INSERT INTO ingredients "
        "(ingredient_id, display_name, aliases, flag_types, flags, "
        "ntp_classification, iarc_classification, fda_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "red_40",
            "Red 40 (Allura Red AC)",
            json.dumps(["red 40", "allura red"]),
            json.dumps(["eu_warning_label"]),
            json.dumps([{"jurisdiction": "EU", "flag_type": "eu_warning_label"}]),
            None,
            None,
            "permitted",
        ),
    )
    conn.execute(
        "INSERT INTO ingredients "
        "(ingredient_id, display_name, aliases, flag_types, flags, "
        "ntp_classification, iarc_classification, fda_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "bvo",
            "Brominated Vegetable Oil (BVO)",
            json.dumps(["brominated vegetable oil", "bvo"]),
            json.dumps(["us_banned"]),
            json.dumps([{"jurisdiction": "US_Federal", "flag_type": "us_banned"}]),
            None,
            None,
            "banned_final_rule",
        ),
    )

    # Seed regulatory flags
    conn.execute(
        "INSERT INTO regulatory_flags "
        "(flag_id, ingredient_id, jurisdiction, flag_type, regulatory_body, "
        "regulation_citation, source_url, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "test-flag-kbr-eu",
            "potassium_bromate",
            "EU",
            "eu_banned",
            "European Commission",
            "Regulation (EC) No 1333/2008",
            "https://eur-lex.europa.eu",
            "Banned as a food additive in the EU",
        ),
    )
    conn.execute(
        "INSERT INTO regulatory_flags "
        "(flag_id, ingredient_id, jurisdiction, flag_type, regulatory_body, "
        "source_url, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "test-flag-red40-eu",
            "red_40",
            "EU",
            "eu_warning_label",
            "European Commission",
            "https://eur-lex.europa.eu",
            "Requires warning label about children's attention",
        ),
    )
    conn.execute(
        "INSERT INTO regulatory_flags "
        "(flag_id, ingredient_id, jurisdiction, flag_type, regulatory_body, "
        "source_url, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "test-flag-bvo-us",
            "bvo",
            "US_Federal",
            "us_banned",
            "FDA",
            "https://www.fda.gov",
            "Banned by FDA (August 2024 final rule)",
        ),
    )

    # Seed commodity
    conn.execute(
        "INSERT INTO commodities "
        "(commodity_slug, display_name, ingredient_aliases, dirty_dozen) "
        "VALUES (?, ?, ?, ?)",
        (
            "strawberry",
            "Strawberry",
            json.dumps(["strawberries", "strawberry puree", "freeze-dried strawberries"]),
            1,
        ),
    )
    conn.commit()