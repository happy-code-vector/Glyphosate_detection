import re
from pathlib import Path

import pdfplumber

from category import normalize_category

BRANDS = [
    "Quaker", "Cheerios", "General Mills", "Nature Valley",
    "Kind", "Clif", "Bob's Red Mill", "Nature's Path", "Lucky Charms",
    "Honey Nut Cheerios", "Back to Nature", "Simple Truth",
]

PDF_URLS = [
    {
        "url": "https://www.ewg.org/sites/default/files/u352/EWG_Glyphosate_BenchmarkTable-2_C02.pdf",
        "round_label": "2018 Round 1",
        "published_date": "2018-08-01",
        "food_category": "oats",
        "raw_category": "oat-based products",
    },
    {
        "url": "https://www.ewg.org/sites/default/files/u352/EWG_Glyphosate-2_Table_Full_C02.pdf",
        "round_label": "2018 Round 2",
        "published_date": "2018-10-01",
        "food_category": "oats",
        "raw_category": "oat-based products",
    },
    {
        "url": "https://static.ewg.org/upload/pdf/EWG_Glyphosate-Testing_05.23_Table_C01.pdf",
        "round_label": "2023 Round",
        "published_date": "2023-04-01",
        "food_category": "oats",
        "raw_category": "oat-based products",
    },
]


def extract_brand(product_name: str) -> str | None:
    for brand in BRANDS:
        if brand.lower() in product_name.lower():
            return brand
    return None


def parse_ewg_pdf(pdf_path: str, round_label: str, published_date: str,
                  food_category: str, raw_category: str) -> list[dict]:
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue
            for row in table:
                if not row or not row[0]:
                    continue
                product_name = str(row[0]).strip()
                if not product_name or product_name.lower() in ["product", "product name", "name"]:
                    continue
                ppb_raw = str(row[1]).strip() if len(row) > 1 else ""

                if ppb_raw.upper() in ["ND", "ND*", "<LOQ", "", "—", "-"]:
                    ppb_value = None
                else:
                    ppb_raw_clean = ppb_raw.replace("<", "").replace(">", "").replace(",", "").strip()
                    try:
                        ppb_value = float(ppb_raw_clean)
                    except ValueError:
                        continue

                rows.append({
                    "tier": 1,
                    "source_name": "EWG",
                    "source_url": "https://www.ewg.org",
                    "published_date": published_date,
                    "data_year": int(published_date[:4]),
                    "product_name": product_name,
                    "brand": extract_brand(product_name),
                    "food_category": food_category,
                    "raw_category": raw_category,
                    "ppb_value": ppb_value,
                    "detection_rate": None,
                    "confidence": "high",
                    "methodology_note": f"EWG commissioned lab test, {round_label}. Lab: Anresco Laboratories.",
                    "is_organic": "organic" in product_name.lower(),
                })
    return rows


EWG_CATEGORY_RATES = [
    {
        "tier": 2, "source_name": "EWG", "published_date": "2023-04-01",
        "data_year": 2023,
        "food_category": "oats", "detection_rate": 1.0,
        "avg_ppb": 290, "sample_count": 24,
        "methodology_note": "EWG 2023 round: all 24 non-organic samples detected",
    },
    {
        "tier": 2, "source_name": "EWG", "published_date": "2020-07-01",
        "data_year": 2020,
        "food_category": "chickpeas", "detection_rate": 0.82,
        "avg_ppb": 510, "sample_count": 11,
        "methodology_note": "EWG 2020 hummus/chickpea round",
    },
    {
        "tier": 2, "source_name": "EWG", "published_date": "2020-07-01",
        "data_year": 2020,
        "food_category": "beans", "detection_rate": 0.60,
        "avg_ppb": 380, "sample_count": 20,
        "methodology_note": "EWG 2020 bean and lentil round",
    },
    {
        "tier": 2, "source_name": "EWG", "published_date": "2020-07-01",
        "data_year": 2020,
        "food_category": "lentils", "detection_rate": 0.60,
        "avg_ppb": 380, "sample_count": 20,
        "methodology_note": "EWG 2020 bean and lentil round",
    },
]


def fetch(download_dir: str = "downloads") -> list[dict]:
    import requests

    all_rows = []

    # Add Tier 2 category rates
    all_rows.extend(EWG_CATEGORY_RATES)

    # Download and parse PDFs
    dl_path = Path(download_dir)
    dl_path.mkdir(exist_ok=True)

    for pdf_info in PDF_URLS:
        filename = pdf_info["url"].split("/")[-1]
        filepath = dl_path / filename

        if not filepath.exists():
            print(f"  Downloading {filename}...")
            resp = requests.get(pdf_info["url"], timeout=60)
            resp.raise_for_status()
            filepath.write_bytes(resp.content)
        else:
            print(f"  Using cached {filename}")

        rows = parse_ewg_pdf(
            str(filepath),
            pdf_info["round_label"],
            pdf_info["published_date"],
            pdf_info["food_category"],
            pdf_info["raw_category"],
        )
        print(f"  Parsed {len(rows)} rows from {filename}")
        all_rows.extend(rows)

    return all_rows
