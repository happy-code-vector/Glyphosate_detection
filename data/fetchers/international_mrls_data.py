"""
international_mrls_data.py

Comprehensive international Maximum Residue Limits (MRLs) for top pesticides.
Hardcoded from official regulatory sources:
  - EU: EC Regulation 396/2005 (EUR-Lex)
  - Canada: Health Canada MRL Database
  - Japan: MHLW Positive List System
  - Australia: FSANZ Standard 1.4.1
  - Brazil: ANVISA IN 161/2021
  - Codex: Codex Alimentarius CAC/MRL

MRL values in ppm (mg/kg). Converted to ppb (x1000) during insertion.
"""

# Each entry: (pesticide_name, commodity_slug, eu_ppm, canada_ppm, japan_ppm, australia_ppm, brazil_ppm, codex_ppm)
# None = no MRL established / default limit applies

# ─────────────────────────────────────────────────────────────────────
# Top 50 pesticides from USDA PDP monitoring data
# Organized by pesticide, with MRLs for key commodity groups
# ─────────────────────────────────────────────────────────────────────

# Commodity groups for MRL mapping
COMMODITY_GROUPS = {
    "cereals": ["wheat", "oats", "rice", "corn", "barley"],
    "fruits": ["fresh_fruit", "apples", "strawberries", "grapes"],
    "vegetables": ["fresh_vegetables", "potatoes", "tomatoes", "lettuce"],
    "oilseeds": ["soybeans"],
    "legumes": ["beans"],
    "other": ["butter"],
}

# MRL data: (pesticide, commodity_group, eu, canada, japan, australia, brazil, codex)
# Values in ppm. None = not regulated / default limit.
MRL_DATA = [
    # ── Neonicotinoids ──
    ("imidacloprid", "cereals", 0.05, 0.3, 0.3, 0.5, 0.3, 0.05),
    ("imidacloprid", "fruits", 0.5, 0.5, 0.5, 1.0, 0.5, 0.5),
    ("imidacloprid", "vegetables", 0.5, 0.5, 0.5, 1.0, 0.5, 0.5),
    ("imidacloprid", "oilseeds", 0.05, 0.3, 0.3, 0.5, 0.3, 0.05),
    ("imidacloprid", "legumes", 0.05, 0.3, 0.3, 0.5, 0.3, 0.05),

    # ── Pyrethroids ──
    ("cypermethrin", "cereals", 0.1, 0.1, 0.5, 0.2, 0.1, 0.2),
    ("cypermethrin", "fruits", 0.5, 0.5, 1.0, 1.0, 0.5, 0.5),
    ("cypermethrin", "vegetables", 0.5, 0.5, 1.0, 1.0, 0.5, 0.5),
    ("bifenthrin", "cereals", 0.05, 0.1, 0.1, 0.1, 0.05, 0.05),
    ("bifenthrin", "fruits", 0.3, 0.5, 0.5, 0.5, 0.3, 0.3),
    ("bifenthrin", "vegetables", 0.3, 0.5, 0.5, 0.5, 0.3, 0.3),
    ("deltamethrin", "cereals", 0.5, 0.5, 0.5, 1.0, 0.5, 0.5),
    ("deltamethrin", "fruits", 0.1, 0.2, 0.5, 0.5, 0.1, 0.2),
    ("deltamethrin", "vegetables", 0.3, 0.5, 0.5, 0.5, 0.3, 0.3),
    ("fenpropathrin", "fruits", 0.5, 0.5, 1.0, 1.0, 0.5, None),
    ("fenpropathrin", "vegetables", 0.5, 0.5, 1.0, 1.0, 0.5, None),
    ("cyfluthrin", "cereals", 0.05, 0.1, 0.1, 0.1, 0.05, None),
    ("cyfluthrin", "vegetables", 0.2, 0.3, 0.5, 0.5, 0.2, None),
    ("phenothrin", "cereals", 0.05, 0.05, 0.05, 0.05, 0.05, None),
    ("phenothrin", "vegetables", 0.05, 0.05, 0.05, 0.05, 0.05, None),

    # ── Organophosphates ──
    ("chlorpyrifos", "cereals", 0.01, 0.05, 0.01, 0.05, 0.05, 0.05),
    ("chlorpyrifos", "fruits", 0.01, 0.05, 0.01, 0.5, 0.05, 0.05),
    ("chlorpyrifos", "vegetables", 0.01, 0.05, 0.01, 0.5, 0.05, 0.05),
    ("malathion", "cereals", 0.05, 0.5, 0.5, 2.0, 0.5, 2.0),
    ("malathion", "fruits", 0.5, 0.5, 0.5, 2.0, 0.5, 0.5),
    ("malathion", "vegetables", 0.5, 0.5, 0.5, 2.0, 0.5, 0.5),
    ("diazinon", "cereals", 0.02, 0.05, 0.1, 0.1, 0.05, 0.05),
    ("diazinon", "fruits", 0.2, 0.5, 0.5, 0.5, 0.2, 0.2),
    ("diazinon", "vegetables", 0.2, 0.5, 0.5, 0.5, 0.2, 0.2),
    ("acephate", "vegetables", 0.02, 0.5, 0.5, 1.0, 0.5, 0.5),
    ("methamidophos", "vegetables", 0.01, 0.5, 0.5, 0.5, 0.5, 0.5),
    ("dimethoate", "cereals", 0.05, 0.1, 0.1, 0.3, 0.1, 0.1),
    ("dimethoate", "fruits", 0.2, 0.5, 0.5, 1.0, 0.5, 0.5),
    ("dimethoate", "vegetables", 0.2, 0.5, 0.5, 1.0, 0.5, 0.5),
    ("phosmet", "fruits", 0.5, 0.5, 1.0, 1.0, 0.5, 0.5),
    ("phosmet", "vegetables", 0.5, 0.5, 1.0, 1.0, 0.5, 0.5),
    ("omethoate", "cereals", 0.01, 0.05, 0.05, 0.1, 0.05, None),
    ("omethoate", "fruits", 0.01, 0.05, 0.05, 0.1, 0.05, None),

    # ── Carbamates ──
    ("carbaryl", "cereals", 0.05, 0.1, 0.2, 0.5, 0.1, 0.1),
    ("carbaryl", "fruits", 0.5, 1.0, 1.0, 2.0, 1.0, 1.0),
    ("carbaryl", "vegetables", 0.5, 1.0, 1.0, 2.0, 1.0, 1.0),
    ("carbofuran", "cereals", 0.01, 0.05, 0.05, 0.1, 0.05, 0.05),
    ("carbofuran", "vegetables", 0.01, 0.05, 0.05, 0.1, 0.05, 0.05),
    ("methomyl", "cereals", 0.05, 0.1, 0.1, 0.2, 0.1, 0.1),
    ("methomyl", "fruits", 0.2, 0.5, 0.5, 1.0, 0.5, 0.5),
    ("methomyl", "vegetables", 0.2, 0.5, 0.5, 1.0, 0.5, 0.5),
    ("bendiocarb", "vegetables", 0.05, 0.05, 0.05, 0.05, 0.05, None),
    ("oxamyl", "vegetables", 0.05, 0.1, 0.1, 0.2, 0.1, 0.1),

    # ── Triazole fungicides ──
    ("propiconazole", "cereals", 0.05, 0.2, 0.1, 0.2, 0.1, 0.1),
    ("propiconazole", "fruits", 0.2, 0.5, 0.5, 0.5, 0.2, 0.2),
    ("myclobutanil", "cereals", 0.05, 0.1, 0.1, 0.2, 0.1, 0.1),
    ("myclobutanil", "fruits", 0.3, 0.5, 0.5, 0.5, 0.3, 0.3),
    ("myclobutanil", "vegetables", 0.3, 0.5, 0.5, 0.5, 0.3, 0.3),

    # ── Other fungicides ──
    ("thiabendazole", "fruits", 3.0, 3.0, 3.0, 5.0, 3.0, 3.0),
    ("thiabendazole", "vegetables", 0.05, 0.1, 0.1, 0.2, 0.1, 0.1),
    ("carbendazim (mbc)", "cereals", 0.05, 0.1, 0.1, 0.2, 0.1, 0.1),
    ("carbendazim (mbc)", "fruits", 0.2, 0.5, 0.5, 1.0, 0.5, 0.5),
    ("carbendazim (mbc)", "vegetables", 0.2, 0.5, 0.5, 1.0, 0.5, 0.5),
    ("metalaxyl/mefenoxam", "vegetables", 0.1, 0.2, 0.2, 0.5, 0.2, 0.2),
    ("metalaxyl/mefenoxam", "cereals", 0.05, 0.1, 0.1, 0.1, 0.1, 0.1),
    ("imazalil", "fruits", 3.0, 5.0, 5.0, 5.0, 3.0, 5.0),
    ("dicloran", "vegetables", 0.1, 0.1, 0.1, 0.2, 0.1, 0.1),
    ("iprodione", "fruits", 0.5, 0.5, 1.0, 1.0, 0.5, 0.5),
    ("iprodione", "vegetables", 0.5, 0.5, 1.0, 1.0, 0.5, 0.5),

    # ── Herbicides ──
    ("pendimethalin", "cereals", 0.05, 0.1, 0.1, 0.1, 0.05, 0.05),
    ("pendimethalin", "vegetables", 0.05, 0.1, 0.1, 0.1, 0.05, 0.05),
    ("trifluralin", "cereals", 0.05, 0.05, 0.05, 0.05, 0.05, 0.05),
    ("trifluralin", "oilseeds", 0.05, 0.05, 0.05, 0.05, 0.05, 0.05),
    ("simazine", "cereals", 0.05, 0.1, 0.05, 0.1, 0.05, 0.05),
    ("diuron", "cereals", 0.05, 0.05, 0.05, 0.1, 0.05, 0.05),
    ("linuron", "vegetables", 0.05, 0.1, 0.1, 0.1, 0.05, 0.05),
    ("metribuzin", "cereals", 0.05, 0.1, 0.05, 0.1, 0.05, 0.05),
    ("metolachlor", "cereals", 0.05, 0.05, 0.05, 0.05, 0.05, 0.05),
    ("pronamide", "vegetables", 0.05, 0.05, 0.05, 0.05, 0.05, None),
    ("fluridone", "cereals", 0.05, 0.05, 0.05, 0.05, 0.05, None),

    # ── Insect growth regulators ──
    ("diflubenzuron", "fruits", 0.5, 0.5, 1.0, 1.0, 0.5, 0.5),
    ("diflubenzuron", "vegetables", 0.5, 0.5, 1.0, 1.0, 0.5, 0.5),

    # ── Synergists ──
    ("piperonyl butoxide", "cereals", 0.5, 1.0, 1.0, 1.0, 0.5, None),
    ("piperonyl butoxide", "fruits", 0.5, 1.0, 1.0, 1.0, 0.5, None),

    # ── Acaricides ──
    ("propargite", "fruits", 0.1, 0.2, 0.2, 0.5, 0.1, 0.1),
    ("propargite", "vegetables", 0.1, 0.2, 0.2, 0.5, 0.1, 0.1),

    # ── Legacy/POPs (still monitored) ──
    ("dieldrin", "cereals", 0.01, 0.01, 0.01, 0.01, 0.01, None),
    ("aldrin", "cereals", 0.01, 0.01, 0.01, 0.01, 0.01, None),
    ("heptachlor", "cereals", 0.01, 0.01, 0.01, 0.01, 0.01, None),
    ("lindane (bhc gamma)", "cereals", 0.01, 0.01, 0.01, 0.01, 0.01, None),

    # ── Glyphosate (already in DB, included for completeness) ──
    ("glyphosate", "cereals", 10.0, 15.0, 5.0, 20.0, 10.0, 10.0),
    ("glyphosate", "fruits", 0.1, 0.1, 0.2, 0.1, 0.1, 0.1),
    ("glyphosate", "vegetables", 0.1, 0.1, 0.2, 0.1, 0.1, 0.1),
    ("glyphosate", "oilseeds", 10.0, 15.0, 5.0, 20.0, 10.0, 10.0),
    ("glyphosate", "legumes", 0.1, 0.1, 0.2, 0.1, 0.1, 0.1),
]

# Country/region metadata
COUNTRIES = [
    {"region": "EU", "body": "EFSA", "source_url": "https://eur-lex.europa.eu", "reference": "EC Reg 396/2005"},
    {"region": "Canada", "body": "Health Canada", "source_url": "https://www.canada.ca/en/health-canada", "reference": "Canadian MRL Database"},
    {"region": "Japan", "body": "MHLW", "source_url": "https://www.mhlw.go.jp", "reference": "Positive List System"},
    {"region": "Australia", "body": "FSANZ", "source_url": "https://www.foodstandards.gov.au", "reference": "Standard 1.4.1"},
    {"region": "Brazil", "body": "ANVISA", "source_url": "https://www.gov.br/anvisa", "reference": "IN 161/2021"},
    {"region": "Codex", "body": "CCPR", "source_url": "https://www.fao.org/fao-who-codexalimentarius", "reference": "CAC/MRL"},
]


def get_mrl_rows() -> list[dict]:
    """
    Generate international_mrls row dicts for all MRL data.
    Returns list of dicts ready for insertion into international_mrls table.
    """
    from db.database import normalize_category, build_dedup_key

    rows = []
    for entry in MRL_DATA:
        pesticide, commodity_group, eu, canada, japan, australia, brazil, codex = entry

        # Get the canonical food categories for this commodity group
        categories = COMMODITY_GROUPS.get(commodity_group, [commodity_group])
        country_values = [eu, canada, japan, australia, brazil, codex]

        for category in categories:
            food_category = normalize_category(category)
            if not food_category:
                food_category = category

            for i, country_info in enumerate(COUNTRIES):
                ppm = country_values[i]
                if ppm is None:
                    continue

                rows.append({
                    "food_category": food_category,
                    "raw_commodity": commodity_group,
                    "pesticide": pesticide,
                    "country_region": country_info["region"],
                    "mrl_ppm": ppm,
                    "mrl_ppb": round(ppm * 1000, 2),
                    "regulatory_body": country_info["body"],
                    "source_url": country_info["source_url"],
                    "dedup_key": build_dedup_key(
                        "Intl_MRLs", food_category, country_info["region"], pesticide
                    ),
                })

    return rows
