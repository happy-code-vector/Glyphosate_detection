from pathlib import Path

import pandas as pd
import requests

from category import normalize_category

CFIA_KNOWN_RATES = [
    {"food_category": "wheat", "detection_rate": 0.366, "sample_count": 869,
     "avg_ppb": None, "raw_category": "grains"},
    {"food_category": "beans", "detection_rate": 0.474, "sample_count": 869,
     "avg_ppb": None, "raw_category": "beans"},
    {"food_category": "peas", "detection_rate": 0.474, "sample_count": 869,
     "avg_ppb": None, "raw_category": "peas"},
    {"food_category": "lentils", "detection_rate": 0.474, "sample_count": 869,
     "avg_ppb": None, "raw_category": "lentils"},
    {"food_category": "chickpeas", "detection_rate": 0.474, "sample_count": 869,
     "avg_ppb": None, "raw_category": "chickpeas"},
    {"food_category": "soybeans", "detection_rate": 0.474, "sample_count": 869,
     "avg_ppb": None, "raw_category": "soybeans"},
    {"food_category": "infant_cereal", "detection_rate": 0.32, "sample_count": 82,
     "avg_ppb": None, "raw_category": "infant food"},
    {"food_category": "fresh_vegetables", "detection_rate": 0.05, "sample_count": 482,
     "avg_ppb": None, "raw_category": "fresh vegetables"},
    {"food_category": "fresh_fruit", "detection_rate": 0.05, "sample_count": 482,
     "avg_ppb": None, "raw_category": "fresh fruit"},
]


def fetch(csv_path: str | None = None) -> list[dict]:
    if csv_path and Path(csv_path).exists():
        return _parse_csv(csv_path)
    return _use_known_rates()


def _parse_csv(filepath: str) -> list[dict]:
    df = pd.read_csv(filepath)
    rows = []
    for _, row in df.iterrows():
        raw_cat = str(row.get("Food Category", "")).strip()
        canonical = normalize_category(raw_cat)
        if not canonical:
            continue

        total = int(row.get("Total Samples", 0) or 0)
        detected = int(row.get("Samples with Detectable Residues", 0) or 0)

        mean_mg = float(row.get("Mean Concentration (mg/kg)", 0) or 0)
        max_mg = float(row.get("Max Concentration (mg/kg)", 0) or 0)

        rows.append({
            "tier": 2,
            "source_name": "CFIA",
            "source_url": "https://inspection.canada.ca/en/food-safety-industry/food-chemistry-and-microbiology/food-safety-testing-reports-and-journal-articles/executive-summary",
            "published_date": "2017-04-01",
            "data_year": 2017,
            "food_category": canonical,
            "raw_category": raw_cat,
            "detection_rate": round(detected / total, 4) if total > 0 else None,
            "avg_ppb": mean_mg * 1000,
            "max_ppb": max_mg * 1000,
            "sample_count": total,
            "confidence": "medium",
            "methodology_note": "CFIA Safeguarding with Science: Glyphosate Testing 2015-2016. LC-MS/MS method. No brand names disclosed.",
        })
    return rows


def _use_known_rates() -> list[dict]:
    rows = []
    for rate in CFIA_KNOWN_RATES:
        rows.append({
            "tier": 2,
            "source_name": "CFIA",
            "source_url": "https://inspection.canada.ca/en/food-safety-industry/food-chemistry-and-microbiology/food-safety-testing-reports-and-journal-articles/executive-summary",
            "published_date": "2017-04-01",
            "data_year": 2017,
            "food_category": rate["food_category"],
            "raw_category": rate["raw_category"],
            "detection_rate": rate["detection_rate"],
            "avg_ppb": rate.get("avg_ppb"),
            "sample_count": rate["sample_count"],
            "confidence": "medium",
            "methodology_note": "CFIA Safeguarding with Science: Glyphosate Testing 2015-2016. LC-MS/MS method. No brand names disclosed.",
        })
    return rows
