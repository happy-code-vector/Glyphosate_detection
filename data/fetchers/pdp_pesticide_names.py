"""
PDP Pesticide Code → Name Mapping

USDA PDP uses numeric pesticide codes in the data files. This module
provides a lookup from code to human-readable pesticide name.

Source: USDA PDP Data Dictionary + annual PDP reference files.
Codes are integers stored as strings in the pipe-delimited data.

This is not exhaustive — PDP tests ~500 pesticides. Unknown codes
will be stored as 'pesticide_{code}' in the database.
"""

# Top ~100 most commonly detected PDP pesticides.
# Expand as needed from PDP reference files.
PESTCODE_NAMES = {
    # ── Glyphosate & metabolites ──
    653: "glyphosate",
    957: "ampa",  # Aminomethylphosphonic acid (glyphosate metabolite)

    # ── Organophosphates ──
    297: "chlorpyrifos",
    395: "malathion",
    486: "diazinon",
    522: "dimethoate",
    568: "acephate",
    600: "methamidophos",
    640: "omethoate",
    691: "phosmet",
    721: "azinphos-methyl",
    421: "dicrotophos",
    315: "chlorpyrifos-methyl",
    516: "dichlorvos",
    379: "coumaphos",
    509: "ethoprophos",
    355: "profenofos",
    274: "bensulide",
    485: "terbufos",
    635: "phorate",

    # ── Neonicotinoids ──
    470: "imidacloprid",
    463: "acetamiprid",
    575: "clothianidin",
    571: "thiamethoxam",
    774: "dinotefuran",
    494: "thiacloprid",

    # ── Pyrethroids ──
    239: "permethrin",
    266: "bifenthrin",
    370: "cypermethrin",
    392: "lambda-cyhalothrin",
    365: "cyfluthrin",
    256: "deltamethrin",
    482: "fenpropathrin",
    387: "esfenvalerate",
    390: "zeta-cypermethrin",
    282: "permethrin-cis",
    283: "permethrin-trans",

    # ── Triazines ──
    48: "atrazine",
    194: "simazine",
    296: "prometryn",
    411: "terbuthylazine",
    592: "hexazinone",

    # ── Carbamates ──
    311: "carbaryl",
    316: "carbofuran",
    309: "aldicarb",
    413: "methomyl",
    312: "carbendazim",
    536: "oxamyl",
    414: "thiodicarb",
    347: "propoxur",
    278: "benomyl",

    # ── Chloroacetamides ──
    506: "metolachlor",
    460: "alachlor",
    507: "acetochlor",
    241: "propachlor",
    394: "dimethenamid",

    # ── Sulfonylureas ──
    631: "nicosulfuron",
    639: "rimsulfuron",
    578: "tribenuron-methyl",
    652: "thifensulfuron-methyl",
    649: "sulfometuron-methyl",

    # ── Phenoxy herbicides ──
    257: "2,4-d",
    258: "2,4-db",
    427: "dicamba",
    555: "triclopyr",
    350: "mcpa",
    539: "fluazifop",

    # ── Strobilurins (fungicides) ──
    589: "azoxystrobin",
    580: "pyraclostrobin",
    534: "trifloxystrobin",
    579: "kresoxim-methyl",

    # ── Triazole fungicides ──
    594: "propiconazole",
    595: "tebuconazole",
    564: "myclobutanil",
    645: "triticonazole",
    573: "triadimefon",
    574: "triadimenol",
    646: "difenoconazole",
    651: "epoxiconazole",
    597: "cyproconazole",
    636: "flusilazole",

    # ── Other herbicides ──
    495: "glyphosate-trimesium",
    658: "glufosinate",
    576: "pendimethalin",
    417: "trifluralin",
    656: "mesotrione",
    556: "clethodim",
    544: "sethoxydim",
    616: "pyridate",
    648: "flumioxazin",
    357: "oxyfluorfen",
    505: "paraquat",
    503: "diquat",
    558: "glyphosate-potassium",

    # ── Other fungicides ──
    660: "boscalid",
    663: "fluopyram",
    647: "penthiopyrad",
    659: "isopyrazam",
    561: "chlorothalonil",
    650: "cyprodinil",
    644: "fludioxonil",
    587: "iprodione",
    590: "vinclozolin",
    627: "fenhexamid",
    629: "pyrimethanil",

    # ── Insect growth regulators ──
    488: "methoprene",
    491: "hydroprene",
    553: "diflubenzuron",
    562: "teflubenzuron",
    603: "novaluron",
    577: "lufenuron",

    # ── Other insecticides ──
    313: "chlorantraniliprole",
    661: "cyantraniliprole",
    637: "spinetoram",
    570: "spinosad",
    540: "indoxacarb",
    605: "chlorfenapyr",
    628: "metaflumizone",
    492: "abamectin",
    632: "emamectin benzoate",
    541: "fenpyroximate",
    599: "spiromesifen",
    654: "spirotetramat",

    # ── Herbicide safeners ──
    515: "dichlormid",
    591: "furilazole",
    633: "isoxadifen",

    # ── Fumigants ──
    344: "1,3-dichloropropene",
    265: "chloropicrin",
    369: "metam-sodium",

    # ── Rodenticides (rare in food, but PDP tests) ──
    703: "brodifacoum",
    705: "bromadiolone",

    # ── Plant growth regulators ──
    641: "ethephon",
    638: "mepiquat",
    642: "chlormequat",
}

# Reverse lookup: name → code
PESTNAME_CODES = {v: k for k, v in PESTCODE_NAMES.items()}


def get_pesticide_name(code: int | str) -> str:
    """
    Get human-readable pesticide name from PDP code.
    Returns 'pesticide_{code}' for unknown codes.
    """
    try:
        code_int = int(code)
    except (ValueError, TypeError):
        return f"pesticide_unknown"

    name = PESTCODE_NAMES.get(code_int)
    if name:
        return name
    return f"pesticide_{code_int}"


def get_pesticide_code(name: str) -> int | None:
    """Get PDP code from pesticide name. Returns None if unknown."""
    return PESTNAME_CODES.get(name.lower().strip())
