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
        "VALUES ('EWG', 'https://example.com', 'EWG 2024', '2024-01-01', 2024, "
        "'oats', 'Oats', 'glyphosate', 100, 80, 0.80, 250.0, 1200.0, 'high', 'test-cs-oats-gly')"
    )
    conn.execute(
        "INSERT INTO category_summaries "
        "(source_name, source_url, report_label, published_date, data_year, "
        "food_category, raw_category, contaminant, samples_total, samples_detected, "
        "detection_rate, avg_ppb, max_ppb, confidence, dedup_key) "
        "VALUES ('EWG', 'https://example.com', 'EWG 2024', '2024-01-01', 2024, "
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