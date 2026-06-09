"""
contaminants.py
Registry of supported contaminants with source-specific lookup keys.

Includes pesticides, heavy metals, food dyes, and additives.
Regulatory flag data per PurityIQ Handoff v3 + Addendum A.
"""

CONTAMINANTS = {
    # ══════════════════════════════════════════
    # PESTICIDES
    # ══════════════════════════════════════════
    "glyphosate": {
        "type": "pesticide",
        "cas_number": "1071-83-6",
        "wqp_characteristic": "Glyphosate",
        "pdp_codes": [653],
        "pdp_exclude_codes": [957],  # AMPA metabolite
        "fda_resname": "GLYPHOSATE",
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "water_standards": [
            {
                "source": "EPA_MCL",
                "tolerance_ppm": 0.7,
                "tolerance_ppb": 700.0,
                "regulation_reference": "40 CFR 141.60",
            },
            {
                "source": "EU_DWD",
                "tolerance_ppm": 0.0001,
                "tolerance_ppb": 0.1,
                "regulation_reference": "EU Drinking Water Directive 2020/2184",
            },
            {
                "source": "Health_Canada",
                "tolerance_ppm": 0.28,
                "tolerance_ppb": 280.0,
                "regulation_reference": "Health Canada Guidelines",
            },
        ],
    },
    "atrazine": {
        "type": "pesticide",
        "cas_number": "1912-24-9",
        "wqp_characteristic": "Atrazine",
        "wqp_date_ranges": [
            ("01-01-2020", "12-31-2023"),
            ("01-01-2015", "12-31-2019"),
            ("01-01-2010", "12-31-2014"),
        ],
        "pdp_codes": [],
        "fda_resname": "ATRAZINE",
        "units": "ppb",
        "risk_thresholds": {"high": 3, "medium": 1, "low": 0},
        "water_standards": [
            {
                "source": "EPA_MCL",
                "tolerance_ppm": 0.003,
                "tolerance_ppb": 3.0,
                "regulation_reference": "40 CFR 141.61",
            },
            {
                "source": "EU_DWD",
                "tolerance_ppm": 0.0001,
                "tolerance_ppb": 0.1,
                "regulation_reference": "EU Drinking Water Directive 2020/2184",
            },
            {
                "source": "Health_Canada",
                "tolerance_ppm": 0.005,
                "tolerance_ppb": 5.0,
                "regulation_reference": "Health Canada Guidelines",
            },
        ],
    },

    # ══════════════════════════════════════════
    # HEAVY METALS
    # ══════════════════════════════════════════
    "lead": {
        "type": "heavy_metal",
        "cas_number": "7439-92-1",
        "wqp_characteristic": "Lead",
        "wqp_params_override": {"sampleMedia": "Water"},
        "wqp_date_ranges": [
            ("01-01-2018", "12-31-2023"),
            ("01-01-2012", "12-31-2017"),
            ("01-01-2006", "12-31-2011"),
        ],
        "pdp_codes": [],
        "fda_search": "Lead",
        "units": "ppb",
        "risk_thresholds": {"high": 15, "medium": 5, "low": 0},
        "water_standards": [
            {
                "source": "EPA_MCL",
                "tolerance_ppm": 0.015,
                "tolerance_ppb": 15.0,
                "regulation_reference": "40 CFR 141.80 — Lead and Copper Rule",
            },
            {
                "source": "EU_DWD",
                "tolerance_ppm": 0.005,
                "tolerance_ppb": 5.0,
                "regulation_reference": "EU Drinking Water Directive 2020/2184",
            },
            {
                "source": "Health_Canada",
                "tolerance_ppm": 0.01,
                "tolerance_ppb": 10.0,
                "regulation_reference": "Health Canada Guidelines — lead MAC",
            },
        ],
        # FDA Metals and Your Food action levels
        "fda_action_levels": {
            "baby_food": {"ppb": 10, "reference": "FDA Closer to Zero action level for lead in baby food"},
            "juice": {"ppb": 50, "reference": "FDA action level for lead in juice"},
        },
        # California AB 899 baby food disclosure
        "ab899": True,
    },
    "inorganic_arsenic": {
        "type": "heavy_metal",
        "cas_number": "7440-38-2",
        "display_name": "Inorganic Arsenic",
        "wqp_characteristic": "Arsenic",
        "pdp_codes": [],
        "fda_search": "Arsenic",
        "units": "ppb",
        "risk_thresholds": {"high": 10, "medium": 5, "low": 0},
        "water_standards": [
            {
                "source": "EPA_MCL",
                "tolerance_ppm": 0.01,
                "tolerance_ppb": 10.0,
                "regulation_reference": "40 CFR 141.62",
            },
            {
                "source": "EU_DWD",
                "tolerance_ppm": 0.001,
                "tolerance_ppb": 1.0,
                "regulation_reference": "EU Drinking Water Directive 2020/2184",
            },
        ],
        "fda_action_levels": {
            "baby_food": {"ppb": 10, "reference": "FDA Closer to Zero action level for arsenic in baby food (infant rice cereal)"},
            "juice": {"ppb": 10, "reference": "FDA action level for inorganic arsenic in apple juice"},
        },
        "ab899": True,
    },
    "cadmium": {
        "type": "heavy_metal",
        "cas_number": "7440-43-9",
        "wqp_characteristic": "Cadmium",
        "pdp_codes": [],
        "fda_search": "Cadmium",
        "units": "ppb",
        "risk_thresholds": {"high": 5, "medium": 2, "low": 0},
        "water_standards": [
            {
                "source": "EPA_MCL",
                "tolerance_ppm": 0.005,
                "tolerance_ppb": 5.0,
                "regulation_reference": "40 CFR 141.62",
            },
            {
                "source": "EU_DWD",
                "tolerance_ppm": 0.002,
                "tolerance_ppb": 2.0,
                "regulation_reference": "EU Drinking Water Directive 2020/2184",
            },
        ],
        "fda_action_levels": {
            "baby_food": {"ppb": 5, "reference": "FDA Closer to Zero action level for cadmium in baby food"},
        },
        "ab899": True,
    },
    "mercury": {
        "type": "heavy_metal",
        "cas_number": "7439-97-6",
        "wqp_characteristic": "Mercury",
        "pdp_codes": [],
        "fda_search": "Mercury",
        "units": "ppb",
        "risk_thresholds": {"high": 10, "medium": 2, "low": 0},
        "water_standards": [
            {
                "source": "EPA_MCL",
                "tolerance_ppm": 0.002,
                "tolerance_ppb": 2.0,
                "regulation_reference": "40 CFR 141.62",
            },
        ],
        "ab899": True,
    },

    # ══════════════════════════════════════════
    # FOOD DYES
    # All flagged in EU (warning label) and/or Prop 65
    # ══════════════════════════════════════════
    "red_40": {
        "type": "food_dye",
        "display_name": "Red 40 (Allura Red AC)",
        "cas_number": "25956-17-6",
        "aliases": ["red 40", "allura red ac", "e129", "fd&c red no. 40", "ci 16035"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [
            {"jurisdiction": "EU", "flag_type": "eu_warning_label", "regulatory_body": "European Commission",
             "regulation_citation": "Regulation (EC) No 1333/2008", "notes": "Requires warning label: 'May have an adverse effect on activity and attention in children'"},
            {"jurisdiction": "California", "flag_type": "prop65_listed", "regulatory_body": "OEHHA",
             "notes": "Listed on California Proposition 65"},
        ],
        "fda_status": "permitted",
    },
    "yellow_5": {
        "type": "food_dye",
        "display_name": "Yellow 5 (Tartrazine)",
        "cas_number": "1934-21-0",
        "aliases": ["yellow 5", "tartrazine", "e102", "fd&c yellow no. 5"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [
            {"jurisdiction": "EU", "flag_type": "eu_warning_label", "regulatory_body": "European Commission",
             "regulation_citation": "Regulation (EC) No 1333/2008", "notes": "Requires warning label: 'May have an adverse effect on activity and attention in children'"},
            {"jurisdiction": "California", "flag_type": "prop65_listed", "regulatory_body": "OEHHA",
             "notes": "Listed on California Proposition 65"},
        ],
        "fda_status": "permitted",
    },
    "yellow_6": {
        "type": "food_dye",
        "display_name": "Yellow 6 (Sunset Yellow FCF)",
        "cas_number": "2783-94-0",
        "aliases": ["yellow 6", "sunset yellow fcf", "e110", "fd&c yellow no. 6"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [
            {"jurisdiction": "EU", "flag_type": "eu_warning_label", "regulatory_body": "European Commission",
             "regulation_citation": "Regulation (EC) No 1333/2008", "notes": "Requires warning label: 'May have an adverse effect on activity and attention in children'"},
            {"jurisdiction": "California", "flag_type": "prop65_listed", "regulatory_body": "OEHHA",
             "notes": "Listed on California Proposition 65"},
        ],
        "fda_status": "permitted",
    },
    "blue_1": {
        "type": "food_dye",
        "display_name": "Blue 1 (Brilliant Blue FCF)",
        "cas_number": "3844-45-9",
        "aliases": ["blue 1", "brilliant blue fcf", "e133", "fd&c blue no. 1"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [],
        "fda_status": "permitted",
    },
    "blue_2": {
        "type": "food_dye",
        "display_name": "Blue 2 (Indigo Carmine)",
        "cas_number": "860-22-0",
        "aliases": ["blue 2", "indigo carmine", "e132", "fd&c blue no. 2"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [],
        "fda_status": "permitted",
    },
    "green_3": {
        "type": "food_dye",
        "display_name": "Green 3 (Fast Green FCF)",
        "cas_number": "2353-45-9",
        "aliases": ["green 3", "fast green fcf", "e143", "fd&c green no. 3"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [],
        "fda_status": "permitted",
    },
    "red_3": {
        "type": "food_dye",
        "display_name": "Red 3 (Erythrosine)",
        "cas_number": "16423-68-0",
        "aliases": ["red 3", "erythrosine", "e127", "fd&c red no. 3"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [
            {"jurisdiction": "US_Federal", "flag_type": "us_banned", "regulatory_body": "FDA",
             "regulation_citation": "21 CFR 74.1303, 21 CFR 74.2303", "notes": "Banned in food by FDA (January 2025 final rule). Previously only banned in cosmetics."},
        ],
        "fda_status": "banned_final_rule",
        "fda_cfr_citation": "21 CFR 74.1303",
    },

    # ══════════════════════════════════════════
    # FOOD ADDITIVES
    # ══════════════════════════════════════════
    "potassium_bromate": {
        "type": "additive",
        "display_name": "Potassium Bromate",
        "cas_number": "7758-01-2",
        "aliases": ["potassium bromate", "e924", "bromated flour"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [
            {"jurisdiction": "EU", "flag_type": "eu_banned", "regulatory_body": "European Commission",
             "regulation_citation": "Regulation (EC) No 1333/2008", "notes": "Banned as a food additive in the EU"},
            {"jurisdiction": "Canada", "flag_type": "canada_banned", "regulatory_body": "Health Canada",
             "notes": "Banned in Canada"},
            {"jurisdiction": "UK", "flag_type": "eu_banned", "regulatory_body": "Food Standards Agency",
             "notes": "Banned in the UK (retained EU law)"},
        ],
        # Per Addendum A: IARC Group 2B, not in NTP RoC, not Prop 65 listed
        "ntp_classification": None,
        "iarc_classification": "Group 2B",
        "fda_status": "permitted",
        "fda_cfr_citation": "21 CFR 136.110",
    },
    "ada": {
        "type": "additive",
        "display_name": "Azodicarbonamide (ADA)",
        "cas_number": "123-77-3",
        "aliases": ["azodicarbonamide", "ada", "e927a"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [
            {"jurisdiction": "EU", "flag_type": "eu_banned", "regulatory_body": "European Commission",
             "regulation_citation": "Regulation (EC) No 1333/2008", "notes": "Banned as a food additive in the EU (flour treatment agent)"},
            {"jurisdiction": "Australia", "flag_type": "eu_banned", "regulatory_body": "FSANZ",
             "notes": "Banned in Australia"},
        ],
        "fda_status": "permitted",
    },
    "tbhq": {
        "type": "additive",
        "display_name": "TBHQ (tert-Butylhydroquinone)",
        "cas_number": "1948-33-0",
        "aliases": ["tbhq", "tert-butylhydroquinone", "e319"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [
            {"jurisdiction": "EU", "flag_type": "eu_banned", "regulatory_body": "European Commission",
             "regulation_citation": "Regulation (EC) No 1333/2008", "notes": "Banned as a food additive in the EU"},
            {"jurisdiction": "Japan", "flag_type": "eu_banned", "regulatory_body": "Ministry of Health, Labour and Welfare",
             "notes": "Banned in Japan"},
        ],
        "fda_status": "permitted",
        "fda_cfr_citation": "21 CFR 172.185",
    },
    "bvo": {
        "type": "additive",
        "display_name": "Brominated Vegetable Oil (BVO)",
        "cas_number": "8016-94-2",
        "aliases": ["brominated vegetable oil", "bvo"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [
            {"jurisdiction": "US_Federal", "flag_type": "us_banned", "regulatory_body": "FDA",
             "regulation_citation": "21 CFR 180.30 (revoked)", "notes": "Banned by FDA (August 2024 final rule). Previously permitted at 15 ppm in citrus-flavored beverages."},
            {"jurisdiction": "EU", "flag_type": "eu_banned", "regulatory_body": "European Commission",
             "notes": "Banned in the EU"},
            {"jurisdiction": "Japan", "flag_type": "eu_banned", "regulatory_body": "Ministry of Health, Labour and Welfare",
             "notes": "Banned in Japan"},
            {"jurisdiction": "India", "flag_type": "eu_banned", "regulatory_body": "FSSAI",
             "notes": "Banned in India"},
        ],
        "fda_status": "banned_final_rule",
    },
    "titanium_dioxide": {
        "type": "additive",
        "display_name": "Titanium Dioxide",
        "cas_number": "13463-67-7",
        "aliases": ["titanium dioxide", "tio2", "e171"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [
            {"jurisdiction": "EU", "flag_type": "eu_banned", "regulatory_body": "European Commission",
             "regulation_citation": "Regulation (EU) 2022/63", "notes": "Banned as a food additive in the EU (effective August 2022)"},
            {"jurisdiction": "California", "flag_type": "prop65_listed", "regulatory_body": "OEHHA",
             "notes": "Listed on California Proposition 65"},
        ],
        "fda_status": "permitted",
        "fda_cfr_citation": "21 CFR 73.575",
    },
    "sodium_nitrite": {
        "type": "additive",
        "display_name": "Sodium Nitrite / Nitrosamines",
        "cas_number": "7632-00-0",
        "aliases": ["sodium nitrite", "sodium nitrate", "potassium nitrite", "potassium nitrate", "e250", "e251", "e249", "e252"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [
            {"jurisdiction": "California", "flag_type": "prop65_listed", "regulatory_body": "OEHHA",
             "notes": "Listed on California Proposition 65 (nitrosamines formed from nitrite in processed meats)"},
        ],
        # Per Addendum A: IARC Group 1 (processed meat), NTP 15th RoC
        "ntp_classification": "NTP 15th RoC — N-Nitrosamines, 15 listings",
        "iarc_classification": "Group 1",
        "fda_status": "permitted",
        "fda_cfr_citation": "21 CFR 172.175",
    },
    "acrylamide": {
        "type": "additive",
        "display_name": "Acrylamide",
        "cas_number": "79-06-1",
        "aliases": ["acrylamide"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [
            {"jurisdiction": "California", "flag_type": "prop65_listed", "regulatory_body": "OEHHA",
             "notes": "Listed on California Proposition 65"},
        ],
        # Per Addendum A: IARC Group 2A, NTP 15th RoC
        "ntp_classification": "NTP 15th RoC — listed",
        "iarc_classification": "Group 2A",
        "fda_status": "under_review",
    },
    "mei_4": {
        "type": "additive",
        "display_name": "4-MEI (4-Methylimidazole)",
        "cas_number": "822-36-6",
        "aliases": ["4-mei", "4-methylimidazole", "4-methylimidazol"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [
            {"jurisdiction": "California", "flag_type": "prop65_listed", "regulatory_body": "OEHHA",
             "notes": "Listed on California Proposition 65 (listed 2011)"},
        ],
        # Per Addendum A: IARC Group 2B, NTP TR 535
        "ntp_classification": "NTP 2007 Technical Report 535",
        "iarc_classification": "Group 2B",
        "fda_status": "permitted",
    },
    "styrene": {
        "type": "additive",
        "display_name": "Styrene (packaging migration)",
        "cas_number": "100-42-5",
        "aliases": ["styrene"],
        "units": "ppb",
        "risk_thresholds": {"high": 500, "medium": 100, "low": 0},
        "regulatory_flags": [
            {"jurisdiction": "California", "flag_type": "prop65_listed", "regulatory_body": "OEHHA",
             "notes": "Listed on California Proposition 65"},
        ],
        # Per Addendum A: IARC Group 2A, NTP 15th RoC
        "ntp_classification": "NTP 15th RoC — listed",
        "iarc_classification": "Group 2A",
        "fda_status": "permitted",
        # V2 feature — packaging migration concern
        "v2_feature": True,
    },
}

CONTAMINANT_KEYS = list(CONTAMINANTS.keys())


def get_contaminant_config(key: str) -> dict:
    """Get config dict for a contaminant. Raises KeyError if unknown."""
    return CONTAMINANTS[key]


def get_risk_level(contaminant: str, ppb: float) -> str:
    """Classify a measurement into risk level based on contaminant thresholds."""
    if ppb is None or ppb <= 0:
        return "none"
    thresholds = CONTAMINANTS[contaminant]["risk_thresholds"]
    if ppb >= thresholds["high"]:
        return "high"
    if ppb >= thresholds["medium"]:
        return "medium"
    return "low"


def get_contaminants_by_type(contaminant_type: str) -> dict:
    """Get all contaminants of a given type (pesticide, heavy_metal, food_dye, additive)."""
    return {k: v for k, v in CONTAMINANTS.items() if v.get("type") == contaminant_type}


def get_regulatory_flags() -> list[dict]:
    """
    Flatten all regulatory flags from all contaminants into a list
    suitable for insertion into the regulatory_flags table.
    """
    flags = []
    for ingredient_id, config in CONTAMINANTS.items():
        for flag in config.get("regulatory_flags", []):
            flags.append({
                "flag_id": build_dedup_key(ingredient_id, flag["jurisdiction"], flag["flag_type"]),
                "ingredient_id": ingredient_id,
                "jurisdiction": flag["jurisdiction"],
                "flag_type": flag["flag_type"],
                "regulatory_body": flag["regulatory_body"],
                "regulation_citation": flag.get("regulation_citation"),
                "source_url": flag.get("source_url", ""),
                "effective_date": flag.get("effective_date"),
                "compliance_date": flag.get("compliance_date"),
                "notes": flag.get("notes"),
            })
    return flags


def get_ingredients() -> list[dict]:
    """
    Flatten all contaminants into ingredient records
    suitable for insertion into the ingredients table.
    """
    import json
    ingredients = []
    for ingredient_id, config in CONTAMINANTS.items():
        flag_types = list({f["flag_type"] for f in config.get("regulatory_flags", [])})
        ingredients.append({
            "ingredient_id": ingredient_id,
            "display_name": config.get("display_name", ingredient_id.replace("_", " ").title()),
            "aliases": json.dumps(config.get("aliases", [])),
            "flag_types": json.dumps(flag_types),
            "flags": json.dumps(config.get("regulatory_flags", [])),
            "ntp_classification": config.get("ntp_classification"),
            "iarc_classification": config.get("iarc_classification"),
            "fda_status": config.get("fda_status"),
            "fda_cfr_citation": config.get("fda_cfr_citation"),
        })
    return ingredients


# Import here to avoid circular dependency at module level
def build_dedup_key(*parts) -> str:
    """Deterministic key — same logic as db.database.build_dedup_key."""
    import hashlib
    combined = "|".join(str(p).lower().strip() for p in parts if p is not None)
    return hashlib.sha256(combined.encode()).hexdigest()[:32]
