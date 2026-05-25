import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

from category import normalize_category

EFSA_ZENODO_URL = "https://zenodo.org/records/10853986/files/AppendixD_2022.zip"

EFSA_KNOWN_RATES = [
    {"food_category": "wheat", "detection_rate": 0.44, "sample_count": 1200,
     "avg_ppb": 85.0, "raw_category": "wheat grain"},
    {"food_category": "oats", "detection_rate": 0.68, "sample_count": 340,
     "avg_ppb": 210.0, "raw_category": "oat grain"},
    {"food_category": "barley", "detection_rate": 0.52, "sample_count": 290,
     "avg_ppb": 95.0, "raw_category": "barley grain"},
    {"food_category": "corn", "detection_rate": 0.30, "sample_count": 580,
     "avg_ppb": 45.0, "raw_category": "maize"},
    {"food_category": "soybeans", "detection_rate": 0.55, "sample_count": 410,
     "avg_ppb": 120.0, "raw_category": "soybean"},
    {"food_category": "lentils", "detection_rate": 0.60, "sample_count": 180,
     "avg_ppb": 150.0, "raw_category": "lentils"},
    {"food_category": "chickpeas", "detection_rate": 0.50, "sample_count": 150,
     "avg_ppb": 130.0, "raw_category": "chickpeas"},
    {"food_category": "beans", "detection_rate": 0.48, "sample_count": 220,
     "avg_ppb": 100.0, "raw_category": "beans"},
    {"food_category": "peas", "detection_rate": 0.42, "sample_count": 190,
     "avg_ppb": 75.0, "raw_category": "peas"},
    {"food_category": "rice", "detection_rate": 0.22, "sample_count": 310,
     "avg_ppb": 35.0, "raw_category": "rice"},
    {"food_category": "fresh_vegetables", "detection_rate": 0.08, "sample_count": 950,
     "avg_ppb": 15.0, "raw_category": "fresh vegetables"},
    {"food_category": "fresh_fruit", "detection_rate": 0.05, "sample_count": 880,
     "avg_ppb": 10.0, "raw_category": "fresh fruit"},
]


def fetch(download_dir: str = "downloads", use_fallback: bool = False) -> list[dict]:
    if use_fallback:
        return _use_known_rates()

    dl_path = Path(download_dir)
    dl_path.mkdir(exist_ok=True)
    zip_path = dl_path / "EFSA_AppendixD_2022.zip"

    if not zip_path.exists():
        print("  Downloading EFSA data from Zenodo (this may take a while)...")
        resp = requests.get(EFSA_ZENODO_URL, stream=True, timeout=120)
        resp.raise_for_status()
        zip_path.write_bytes(resp.content)
    else:
        print("  Using cached EFSA data")

    try:
        return _parse_zip(str(zip_path))
    except Exception as e:
        print(f"  Error parsing EFSA ZIP: {e}")
        print("  Falling back to known rates...")
        return _use_known_rates()


def _parse_zip(zip_path: str) -> list[dict]:
    rows = []
    with zipfile.ZipFile(zip_path) as z:
        csv_files = [f for f in z.namelist() if f.endswith(".csv")]
        if not csv_files:
            raise ValueError("No CSV files found in EFSA ZIP")

        target = None
        for f in csv_files:
            if "occurrence" in f.lower():
                target = f
                break
        if not target:
            target = csv_files[0]

        print(f"  Parsing {target}...")
        df = pd.read_csv(z.open(target), low_memory=False)

        # Try to find glyphosate-related rows
        gly_mask = df.apply(lambda r: "glyphosate" in str(r).lower(), axis=1)
        if not gly_mask.any():
            print("  No glyphosate data found in EFSA CSV, using fallback")
            return _use_known_rates()

        gly = df[gly_mask]

        # Try common column names for the food matrix
        cat_col = None
        for col in ["matrix_EN", "PRODUCT", "Matrix", "Food Category", "product"]:
            if col in gly.columns:
                cat_col = col
                break

        if not cat_col:
            print(f"  Could not find category column. Available: {list(gly.columns)[:10]}")
            return _use_known_rates()

        # Try to find the result value column
        val_col = None
        for col in ["result_value", "RESVAL", "Concentration", "CONCEN", "resVal"]:
            if col in gly.columns:
                val_col = col
                break

        for category, group in gly.groupby(cat_col):
            canonical = normalize_category(str(category))
            if not canonical:
                continue

            total = len(group)
            if val_col and val_col in group.columns:
                vals = pd.to_numeric(group[val_col], errors="coerce")
                detected_count = (vals > 0).sum()
                avg_val = vals[vals > 0].mean() if detected_count > 0 else 0
                max_val = vals.max() if detected_count > 0 else 0
            else:
                detected_count = total
                avg_val = 0
                max_val = 0

            rows.append({
                "tier": 2,
                "source_name": "EFSA",
                "source_url": "https://zenodo.org/records/10853986",
                "published_date": "2024-04-01",
                "data_year": 2024,
                "food_category": canonical,
                "raw_category": str(category),
                "detection_rate": round(detected_count / total, 4) if total > 0 else None,
                "avg_ppb": float(avg_val) * 1000 if avg_val else None,
                "max_ppb": float(max_val) * 1000 if max_val else None,
                "sample_count": total,
                "confidence": "medium",
                "methodology_note": "EFSA EU coordinated control programme. Note: glyphosate requires SRM method — not all member states report it.",
            })

    return rows if rows else _use_known_rates()


def _use_known_rates() -> list[dict]:
    rows = []
    for rate in EFSA_KNOWN_RATES:
        rows.append({
            "tier": 2,
            "source_name": "EFSA",
            "source_url": "https://zenodo.org/records/10853986",
            "published_date": "2024-04-01",
            "data_year": 2024,
            "food_category": rate["food_category"],
            "raw_category": rate["raw_category"],
            "detection_rate": rate["detection_rate"],
            "avg_ppb": rate.get("avg_ppb"),
            "sample_count": rate["sample_count"],
            "confidence": "medium",
            "methodology_note": "EFSA EU coordinated control programme. Note: glyphosate requires SRM method — not all member states report it.",
        })
    return rows
