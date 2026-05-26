"""
contaminants.py
Registry of supported contaminants with source-specific lookup keys.
"""

CONTAMINANTS = {
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
                "regulation_reference": "40 CFR 141.60 — National Primary Drinking Water Regulation",
            },
            {
                "source": "EU_DWD",
                "tolerance_ppm": 0.0001,
                "tolerance_ppb": 0.1,
                "regulation_reference": "EU Drinking Water Directive 2020/2184 — individual pesticide limit",
            },
            {
                "source": "Health_Canada",
                "tolerance_ppm": 0.28,
                "tolerance_ppb": 280.0,
                "regulation_reference": "Health Canada Guidelines for Canadian Drinking Water Quality",
            },
        ],
    },
    "lead": {
        "type": "heavy_metal",
        "cas_number": "7439-92-1",
        "wqp_characteristic": "Lead",
        "pdp_codes": [],
        "fda_search": "Lead",
        "units": "ppb",
        "risk_thresholds": {"high": 15, "medium": 5, "low": 0},
        "water_standards": [
            {
                "source": "EPA_MCL",
                "tolerance_ppm": 0.015,
                "tolerance_ppb": 15.0,
                "regulation_reference": "40 CFR 141.80 — Lead and Copper Rule, action level",
            },
            {
                "source": "EU_DWD",
                "tolerance_ppm": 0.005,
                "tolerance_ppb": 5.0,
                "regulation_reference": "EU Drinking Water Directive 2020/2184 — lead limit",
            },
            {
                "source": "Health_Canada",
                "tolerance_ppm": 0.01,
                "tolerance_ppb": 10.0,
                "regulation_reference": "Health Canada Guidelines for Canadian Drinking Water Quality — lead MAC",
            },
        ],
    },
    "atrazine": {
        "type": "pesticide",
        "cas_number": "1912-24-9",
        "wqp_characteristic": "Atrazine",
        "pdp_codes": [],
        "fda_resname": "ATRAZINE",
        "units": "ppb",
        "risk_thresholds": {"high": 3, "medium": 1, "low": 0},
        "water_standards": [
            {
                "source": "EPA_MCL",
                "tolerance_ppm": 0.003,
                "tolerance_ppb": 3.0,
                "regulation_reference": "40 CFR 141.61 — National Primary Drinking Water Regulation, atrazine",
            },
            {
                "source": "EU_DWD",
                "tolerance_ppm": 0.0001,
                "tolerance_ppb": 0.1,
                "regulation_reference": "EU Drinking Water Directive 2020/2184 — individual pesticide limit",
            },
            {
                "source": "Health_Canada",
                "tolerance_ppm": 0.005,
                "tolerance_ppb": 5.0,
                "regulation_reference": "Health Canada Guidelines for Canadian Drinking Water Quality — atrazine MAC",
            },
        ],
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
