"""
db/database.py
Core database operations. All pipeline code imports from here.
"""

import csv
import re
import sqlite3
import hashlib
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "residueiq.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"
ALIASES_PATH = Path(__file__).parent / "category_aliases.csv"


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize():
    """Create all tables. Safe to call on every run — idempotent."""
    with get_connection() as conn:
        _migrate_legacy(conn)
        conn.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
        _migrate_add_contaminant_column(conn)
        _migrate_add_new_columns(conn)
        _seed_category_aliases(conn)
    logger.info("Database initialized at %s", DB_PATH)


def _migrate_add_contaminant_column(conn):
    """Add contaminant column to existing tables if missing."""
    tables_to_migrate = [
        "product_tests",
        "category_summaries",
        "water_tests",
        "tolerance_limits",
    ]
    for table in tables_to_migrate:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        col_names = [c[1] for c in cols]
        if "contaminant" not in col_names:
            logger.info("Adding contaminant column to %s", table)
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN contaminant TEXT NOT NULL DEFAULT 'glyphosate'"
            )
    conn.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
    logger.info("Contaminant column migration complete")


def _migrate_add_new_columns(conn):
    """Add new columns to existing tables for regulatory features."""
    # Add contaminant_type to ingredients
    cols = conn.execute("PRAGMA table_info(ingredients)").fetchall()
    col_names = [c[1] for c in cols]
    if "contaminant_type" not in col_names:
        logger.info("Adding contaminant_type column to ingredients")
        conn.execute("ALTER TABLE ingredients ADD COLUMN contaminant_type TEXT")

    # Add contaminant_type to regulatory_flags
    cols = conn.execute("PRAGMA table_info(regulatory_flags)").fetchall()
    col_names = [c[1] for c in cols]
    if "contaminant_type" not in col_names:
        logger.info("Adding contaminant_type column to regulatory_flags")
        conn.execute("ALTER TABLE regulatory_flags ADD COLUMN contaminant_type TEXT")

    # Add contaminant to certified_products
    cols = conn.execute("PRAGMA table_info(certified_products)").fetchall()
    col_names = [c[1] for c in cols]
    if "contaminant" not in col_names:
        logger.info("Adding contaminant column to certified_products")
        conn.execute("ALTER TABLE certified_products ADD COLUMN contaminant TEXT")

    # Add flagged_brand to alternatives
    cols = conn.execute("PRAGMA table_info(alternatives)").fetchall()
    col_names = [c[1] for c in cols]
    if "flagged_brand" not in col_names:
        logger.info("Adding flagged_brand column to alternatives")
        conn.execute("ALTER TABLE alternatives ADD COLUMN flagged_brand TEXT")

    logger.info("New columns migration complete")


def _migrate_legacy(conn):
    """Migrate data from old glyphosate_measurements table to new split tables."""
    # Check if legacy table exists
    legacy = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='glyphosate_measurements'"
    ).fetchone()
    if not legacy:
        return

    # Check if migration already done (new tables exist with data)
    new_tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('product_tests', 'category_summaries')"
    ).fetchall()
    if len(new_tables) == 2:
        # Check if new tables already have data — if so, migration done
        pt_count = conn.execute("SELECT COUNT(*) FROM product_tests").fetchone()[0]
        cs_count = conn.execute("SELECT COUNT(*) FROM category_summaries").fetchone()[0]
        if pt_count > 0 or cs_count > 0:
            logger.info("Legacy migration already complete (product_tests=%d, category_summaries=%d)",
                        pt_count, cs_count)
            return

    logger.info("Migrating legacy glyphosate_measurements to product_tests + category_summaries...")

    # Create new tables if they don't exist yet
    conn.execute("""
        CREATE TABLE IF NOT EXISTS product_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL, source_url TEXT NOT NULL, report_label TEXT NOT NULL,
            published_date TEXT NOT NULL, data_year INTEGER NOT NULL,
            food_category TEXT NOT NULL, raw_category TEXT NOT NULL,
            product_name TEXT NOT NULL, measured_ppb REAL, below_detection INTEGER DEFAULT 0,
            limit_of_detection REAL,
            original_unit TEXT DEFAULT 'ppb', unit_conversion REAL DEFAULT 1.0,
            is_organic INTEGER DEFAULT 0, is_grf_certified INTEGER DEFAULT 0,
            methodology_note TEXT, confidence TEXT NOT NULL,
            dedup_key TEXT UNIQUE NOT NULL,
            ingested_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')),
            raw_file_path TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS category_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL, source_url TEXT NOT NULL, report_label TEXT NOT NULL,
            published_date TEXT NOT NULL, data_year INTEGER NOT NULL,
            food_category TEXT NOT NULL, raw_category TEXT NOT NULL,
            samples_total INTEGER NOT NULL, samples_detected INTEGER NOT NULL,
            detection_rate REAL NOT NULL, avg_ppb REAL, max_ppb REAL, p95_ppb REAL,
            median_ppb REAL, min_ppb REAL,
            original_unit TEXT DEFAULT 'ppb', unit_conversion REAL DEFAULT 1.0,
            is_organic INTEGER DEFAULT 0, methodology_note TEXT, confidence TEXT NOT NULL,
            dedup_key TEXT UNIQUE NOT NULL,
            ingested_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')),
            raw_file_path TEXT
        )
    """)

    # Migrate Tier 1
    conn.execute("""
        INSERT OR IGNORE INTO product_tests (
            source_name, source_url, report_label, published_date, data_year,
            food_category, raw_category, product_name, measured_ppb, below_detection,
            original_unit, unit_conversion, is_organic, is_grf_certified,
            methodology_note, confidence, dedup_key, ingested_at, raw_file_path
        )
        SELECT
            source_name, source_url, report_label, published_date, data_year,
            food_category, raw_category, product_name, measured_ppb, below_detection,
            original_unit, unit_conversion, is_organic, is_grf_certified,
            methodology_note, confidence, dedup_key, ingested_at, raw_file_path
        FROM glyphosate_measurements
        WHERE tier = 1
    """)
    t1_migrated = conn.execute("SELECT changes()").fetchone()[0]

    # Migrate Tier 2
    conn.execute("""
        INSERT OR IGNORE INTO category_summaries (
            source_name, source_url, report_label, published_date, data_year,
            food_category, raw_category,
            samples_total, samples_detected, detection_rate, avg_ppb, max_ppb, p95_ppb,
            original_unit, unit_conversion, is_organic, methodology_note, confidence,
            dedup_key, ingested_at, raw_file_path
        )
        SELECT
            source_name, source_url, report_label, published_date, data_year,
            food_category, raw_category,
            COALESCE(samples_total, 0), COALESCE(samples_detected, 0),
            COALESCE(detection_rate, 0), avg_ppb, max_ppb, p95_ppb,
            original_unit, unit_conversion, is_organic, methodology_note, confidence,
            dedup_key, ingested_at, raw_file_path
        FROM glyphosate_measurements
        WHERE tier = 2
    """)
    t2_migrated = conn.execute("SELECT changes()").fetchone()[0]

    conn.commit()
    logger.info("Migrated %d Tier 1 rows to product_tests, %d Tier 2 rows to category_summaries",
                t1_migrated, t2_migrated)

    # Drop legacy table — the schema.sql will create the backward-compat view
    conn.execute("DROP TABLE IF EXISTS glyphosate_measurements")
    logger.info("Dropped legacy glyphosate_measurements table")


def _seed_category_aliases(conn):
    """
    Load aliases from category_aliases.csv.
    Extend the CSV when a new source introduces a new spelling — no code change needed.
    """
    if not ALIASES_PATH.exists():
        logger.warning("category_aliases.csv not found at %s", ALIASES_PATH)
        return

    with open(ALIASES_PATH, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        aliases = [(row[0].strip(), row[1].strip()) for row in reader if len(row) >= 2]

    conn.executemany(
        "INSERT OR IGNORE INTO category_aliases (alias, canonical_key) VALUES (?, ?)",
        aliases,
    )
    invalidate_alias_cache()
    logger.info("Seeded %d category aliases from CSV", len(aliases))


# Module-level cache for category aliases (loaded once, reused across calls)
_alias_cache: Optional[dict[str, str]] = None  # alias -> canonical_key
_alias_substring: Optional[list[tuple[str, str]]] = None  # (alias, key) for substring matching


def _load_alias_cache(conn=None):
    """Load category aliases into module-level cache."""
    global _alias_cache, _alias_substring
    if _alias_cache is not None:
        return

    def _load(c):
        global _alias_cache, _alias_substring
        rows = c.execute("SELECT alias, canonical_key FROM category_aliases").fetchall()
        _alias_cache = {row[0]: row[1] for row in rows}
        # Sort by alias length descending — prefer longer (more specific) matches
        _alias_substring = sorted(
            [(row[0], row[1]) for row in rows],
            key=lambda x: len(x[0]),
            reverse=True,
        )

    if conn:
        _load(conn)
    else:
        with get_connection() as c:
            _load(c)


def invalidate_alias_cache():
    """Clear the alias cache. Call after modifying category_aliases table."""
    global _alias_cache, _alias_substring
    _alias_cache = None
    _alias_substring = None


def normalize_category(raw: str, conn=None) -> Optional[str]:
    """
    Map any raw category string to a canonical key.
    Uses cached aliases for fast matching. Falls back to word-boundary substring matching.
    Returns None if no match found — caller must handle this.
    """
    if not raw:
        return None
    cleaned = raw.lower().strip()
    # Normalize punctuation to spaces for matching (commas, semicolons, etc.)
    normalized = re.sub(r'[,;/\t]+', ' ', cleaned)
    normalized = re.sub(r'\s+', ' ', normalized).strip()

    _load_alias_cache(conn)

    # 1. Exact match (O(1) dict lookup) — try both raw and normalized
    if cleaned in _alias_cache:
        return _alias_cache[cleaned]
    if normalized != cleaned and normalized in _alias_cache:
        return _alias_cache[normalized]

    # 2. Word-boundary substring: find best alias that appears as a whole word
    #    inside the normalized string. Prevents "pea" matching inside "peanut butter".
    #    When multiple aliases match, prefer longer alias. On tie, prefer the
    #    match whose captured text covers more of the input (beats generic words
    #    like "butter" winning over "peanut" in "peanut, butter").
    best_alias_len = 0
    best_span = 0
    best_key = None
    for alias, key in _alias_substring:
        if len(alias) < 2:
            continue
        if len(alias) < best_alias_len:
            break  # sorted desc, no better alias possible
        pattern = r'\b' + re.escape(alias) + r'\b'
        m = re.search(pattern, normalized)
        if m:
            span = m.end() - m.start()
            if len(alias) > best_alias_len or (len(alias) == best_alias_len and span > best_span):
                best_alias_len = len(alias)
                best_span = span
                best_key = key
    if best_key:
        return best_key

    return None


def build_dedup_key(*parts) -> str:
    """Deterministic key to prevent duplicate rows on re-runs."""
    combined = "|".join(str(p).lower().strip() for p in parts if p is not None)
    return hashlib.sha256(combined.encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Contaminant name normalization
# ---------------------------------------------------------------------------

# German umlaut replacements
_UMLAUT_MAP = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})

# Curated German → English contaminant name mappings (top BVL entries)
_CONTAMINANT_ALIASES: dict[str, str] = {
    # Simple German chemical names
    "acephat": "acephate",
    "amitrol": "amitrol",
    "atrazin": "atrazine",
    "azoxystrobin": "azoxystrobin",
    "bifenthrin": "bifenthrin",
    "boscalid": "boscalid",
    "captan": "captan",
    "carbaryl": "carbaryl",
    "chlorantraniliprol": "chlorantraniliprole",
    "chloridazon-desphenyl": "chloridazon",
    "chloridazondesphenyl": "chloridazon",
    "chlorothalonil": "chlorothalonil",
    "chlorpropham": "chlorpropham",
    "chlorpyrifos": "chlorpyrifos",
    "clothianidin": "clothianidin",
    "cypermethrin": "cypermethrin",
    "cyproconazol": "cyproconazole",
    "cyprodinil": "cyprodinil",
    "deltamethrin": "deltamethrin",
    "diazinon": "diazinon",
    "dichlofluanid": "dichlofluanid",
    "dieldrin": "dieldrin",
    "difenoconazol": "difenoconazole",
    "dimethoat": "dimethoate",
    "dithiocarbamate": "dithiocarbamate",
    "dodin": "dodine",
    "endosulfan": "endosulfan",
    "endrin": "endrin",
    "epoxiconazol": "epoxiconazole",
    "etofenprox": "etofenprox",
    "fenhexamid": "fenhexamid",
    "fenpropathrin": "fenpropathrin",
    "fenpyroximat": "fenpyroximate",
    "flonicamid": "flonicamid",
    "fluazinam": "fluazinam",
    "fludioxonil": "fludioxonil",
    "flufenacet": "flufenacet",
    "fluopyram": "fluopyram",
    "fluopicolid": "fluopicolide",
    "flutriafol": "flutriafol",
    "fluxapyroxad": "fluxapyroxad",
    "folpet": "folpet",
    "glufosinate": "glufosinate",
    "glyphosat": "glyphosate",
    "heptachlor": "heptachlor",
    "hexaconazol": "hexaconazole",
    "imidacloprid": "imidacloprid",
    "indoxacarb": "indoxacarb",
    "iprodion": "iprodione",
    "isoprothiolane": "isoprothiolane",
    "kupfer cu": "copper",
    "lambda-cyhalothrin": "lambda-cyhalothrin",
    "lindan": "lindane",
    "linuron": "linuron",
    "malathion": "malathion",
    "mandipropamid": "mandipropamide",
    "mandipropamide": "mandipropamide",
    "metalaxyl": "metalaxyl",
    "methamidophos": "methamidophos",
    "methomyl": "methomyl",
    "metolachlor": "metolachlor",
    "metribuzin": "metribuzin",
    "myclobutanil": "myclobutanil",
    "nikotin": "nicotine",
    "omethoat": "omethoate",
    "oxamyl": "oxamyl",
    "parathion": "parathion",
    "pendimethalin": "pendimethalin",
    "permethrin": "permethrin",
    "phosmet": "phosmet",
    "propamocarb": "propamocarb",
    "propiconazol": "propiconazole",
    "propiconazole": "propiconazole",
    "propoxur": "propoxur",
    "prothioconazole": "prothioconazole",
    "pyraclostrobin": "pyraclostrobin",
    "pyrimethanil": "pyrimethanil",
    "pyriproxyfen": "pyriproxyfen",
    "quecksilber hg": "mercury",
    "schwefel s": "sulfur",
    "spinosad": "spinosad",
    "spinosyn a": "spinosad",
    "spinosyn d": "spinosad",
    "spirodiclofen": "spirodiclofen",
    "spirotetramat": "spirotetramat",
    "tebuconazol": "tebuconazole",
    "tebuconazole": "tebuconazole",
    "tebufenpyrad": "tebufenpyrad",
    "thiacloprid": "thiacloprid",
    "thiamethoxam": "thiamethoxam",
    "thiophanat-methyl": "thiophanate-methyl",
    "trifloxystrobin": "trifloxystrobin",
    "trifluralin": "trifluralin",
    "triticonazole": "triticonazole",
    "vinclozolin": "vinclozolin",
    # Compound / descriptive German names → canonical
    "chlorat": "chlorate",
    "phosphonsaeure": "fosetyl",
    "phosphonsäure": "fosetyl",
    "bromhaltige begasungsmittel berechnet als bromid": "bromide",
    "bromhaltige begasungsmittel": "bromide",
    "boscalid; nicobifen": "boscalid",
    "dithiocarbamate berechnet als cs2": "dithiocarbamate",
    "fosetyl, summe aus fosetyl und phosphonsaeure, einschliesslich der salze,": "fosetyl",
    "fosetyl, summe aus fosetyl und phosphonsaeure, einschliesslich der salze": "fosetyl",
    "fosetyl": "fosetyl",
    "iprodion; glycophen": "iprodione",
    "carbendazim": "carbendazim",
    "dichlorobenzophenone, p,p'-": "dichlorobenzophenone",
    "pp-dde": "dde",
    "dde p,p'": "dde",
    "pp-ddt": "ddt",
    "ddt p,p'": "ddt",
    "ddd p,p'": "ddd",
    "2,6-dichlorbenzamid": "2,6-dichlorobenzamide",
    "3,4-dichloraniline": "3,4-dichloroaniline",
    "3-chloranilin": "3-chloroaniline",
    "hexachlorbenzol hcb": "hexachlorobenzene",
    # German chemical name → English canonical
    "thiabendazol": "thiabendazole",
    "chlorthalonil": "chlorothalonil",
    "piperonylbutoxid": "piperonyl butoxide",
    "benzalkoniumchlorid": "benzalkonium chloride",
    "didecyldimethylammoniumchlorid": "didecyldimethylammonium chloride",
    "dialkyldimethylammoniumchlorid": "didecyldimethylammonium chloride",
    "benzyldodecyldimethylammoniumchlorid": "benzalkonium chloride",
    "benzyldimethyltetradecylammoniumchlorid": "benzalkonium chloride",
    "benzylhexadecyldimethylammoniumchlorid": "benzalkonium chloride",
    "benzyldimethylstearylammoniumchlorid": "benzalkonium chloride",
    "benzyldimethyloctylammoniumchlorid": "benzalkonium chloride",
    "benzyldimethyldecylammoniumchlorid": "benzalkonium chloride",
    "alpha-cypermethrin": "cypermethrin",
    "alpha(cis)-chlordan": "chlordane",
    "alpha-hch": "lindane",
    "beta-hch": "lindane",
    "gamma-hch": "lindane",
    "triazol-alanin": "triazole",
    "trimethylsulfonium-kation": "glyphosate",
    "hepa 2-hydroxyethyl-phosphonsaeure": "fosetyl",
    "aminomethylphosphonsaeure ampa": "glyphosate",
    "aminomethylphosphonsaeure": "glyphosate",
    "ampa": "glyphosate",
    "metalaxyl und metalaxyl m": "metalaxyl",
    "fluazifop": "fluazifop-p",
    "ethiprol": "ethiprole",
    "probenazol": "probenazole",
    "anthrachinon": "anthraquinone",
    "amitrol": "amitrole",
    "aldicarbsulfoxid": "aldicarb",
    "3-oh-carbofuran": "carbofuran",
    "4-hydroxychlorthalonil": "chlorothalonil",
    "alpha-endosulfan": "endosulfan",
    "beta-endosulfan": "endosulfan",
    "p,p'-dichlorbenzophenon": "dichlorobenzophenone",
    # German -azol → -azole
    "tetraconazol": "tetraconazole",
    "fenbuconazol": "fenbuconazole",
    "penconazol": "penconazole",
    "metconazol": "metconazole",
    "triticonazol": "triticonazole",
    "fluquinconazol": "fluquinconazole",
    "flusilazol": "flusilazole",
    "diniconazol": "diniconazole",
    "fluvalinat": "fluvalinate",
    "tau-fluvalinat": "fluvalinate",
    "tricyclazol": "tricyclazole",
    "prothioconazol": "prothioconazole",
    "prothioconazol-desthio": "prothioconazole",
    "bromuconazol": "bromuconazole",
    "uniconazol": "uniconazole",
    "metrafenon": "metrafenone",
    "pyriofenon": "pyriofenone",
    "imibenconazol": "imibenconazole",
    "etaconazol": "etaconazole",
    # German -at → -ate
    "glufosinat": "glufosinate",
    "glufosinat-ammonium": "glufosinate",
    "propamocarb-n-oxid": "propamocarb",
    "fenvalerat": "fenvalerate",
    "esfenvalerat": "esfenvalerate",
    "flucythrinat": "flucythrinate",
    "phenthoat": "phenthoate",
    "fosthiazat": "fosthiazate",
    "ethofumesat": "ethofumesate",
    "propargit": "propargite",
    "fenbutatin-oxid": "fenbutatin oxide",
    "bifenazat": "bifenazate",
    "bifenazat-diazen": "bifenazate",
    "formetanat": "formetanate",
    "formetanat-hydrochlorid": "formetanate",
    "tebufenozid": "tebufenozide",
    "pymetrozin": "pymetrozine",
    "cyromazin": "cyromazine",
    "triflumizol": "triflumizole",
    "fuberidazol": "fuberidazole",
    "rotenon": "rotenone",
    "simazin": "simazine",
    "propazin": "propazine",
    "aziprotryn": "aziprotryne",
    "triazin": "triazine",
    "fentin": "fentin",
    "daminozid": "daminozide",
    "metaldehyd": "metaldehyde",
    "phthalimid": "phthalimide",
    "tetrahydrophthalimid": "tetrahydrophthalimide",
    "quinmerac": "quinmerac",
    "trinexapac": "trinexapac",
    "trinexapac-ethyl": "trinexapac",
    "mefentrifluconazol": "mefentrifluconazole",
    # German -saeure → -acid
    "gibberelinsaeure": "gibberellic acid",
    "triazol-essigsaeure": "triazole",
    "triazol-milchsaeure": "triazole",
    "maleinsaeurehydrazid": "maleic hydrazide",
    "dimethylarsinsaeure": "cacodylic acid",
    "naphthoxyessigsaeure": "naphthoxyacetic acid",
    "1-naphthylessigsaeure": "naphthylacetic acid",
    "1-naphthylessigsaeureamid": "naphthylacetamide",
    "1-naphthylacetamid und 1-naphthylessigsaeure": "naphthylacetic acid",
    "beta-indolylessigsaeure": "indoleacetic acid",
    "beta-indolylbuttersaeure": "indolebutyric acid",
    "blausaeure": "hydrogen cyanide",
    "phosphorwasserstoff": "phosphine",
    # German common names
    "diphenylamin": "diphenylamine",
    "pyrethrum": "pyrethrin",
    "pyrethrine": "pyrethrin",
    "pyrethrin i": "pyrethrin",
    "pyrethrin ii": "pyrethrin",
    "cinerin i": "pyrethrin",
    "cinerin ii": "pyrethrin",
    "jasmolin i": "pyrethrin",
    "jasmolin ii": "pyrethrin",
    "sulfur": "sulfur",
    "schwefel": "sulfur",
    "kupfer": "copper",
    "kupfer und kupferverbindungen": "copper",
    "kupferverbindungen": "copper",
    "quecksilber": "mercury",
    "hcb": "hexachlorobenzene",
    "pentachlorphenol": "pentachlorophenol",
    "pentachloranilin": "pentachloroaniline",
    "pentachloranisol": "pentachloroanisole",
    "hexabrombenzol": "hexabromobenzene",
    "quintozen": "quintozene",
    "tecnazen": "tecnazene",
    "propyzamid": "propyzamide",
    "napropamid": "napropamide",
    "zoxamid": "zoxamide",
    "flubendiamid": "flubendiamide",
    "cyantraniliprol": "cyantraniliprole",
    "chlorantraniliprol": "chlorantraniliprole",
    "cyclaniliprol": "cyclaniliprole",
    "emamectinbenzoat": "emamectin benzoate",
    "emamectin b1a und seine": "emamectin benzoate",
    "milbemectin": "milbemectin",
    "milbemectin a3": "milbemectin",
    "milbemectin a4": "milbemectin",
    "avermectin b 1 a": "abamectin",
    "avermectin b 1b": "abamectin",
    "avermectin b1a": "abamectin",
    "8,9-z-avermectin b 1 a": "abamectin",
    "azadirachtin a": "azadirachtin",
    "benzyladenin": "benzyladenine",
    "fenamidon": "fenamidone",
    "metaflumizon": "metaflumizone",
    "flupyradifuron": "flupyradifurone",
    "clofentezin": "clofentezine",
    "etoxazol": "etoxazole",
    "spiroxamin": "spiroxamine",
    "procymidon": "procymidone",
    "phenothrin": "phenothrin",
    "brompropylat": "bromopropylate",
    "chlorpropylat": "chloropropylate",
    "phosalon": "phosalone",
    "phorat": "phorate",
    "phosmetoxon": "phosmet",
    "paraoxon-methyl": "paraoxon",
    "desmethyl-pirimicarb": "pirimicarb",
    "desmethyl-formamido-pirimicarb": "pirimicarb",
    "methiocarb-sulfoxid": "methiocarb",
    "methiocarb-sulfon": "methiocarb",
    "fenamiphos-sulfoxid": "fenamiphos",
    "fenamiphos-sulfon": "fenamiphos",
    "fenthion-sulfoxid": "fenthion",
    "fenthion-sulfon": "fenthion",
    "fenthion-oxon-sulfoxid": "fenthion",
    "fenthion-oxon-sulfon": "fenthion",
    "phorat-sulfoxid": "phorate",
    "phorat-sulfon": "phorate",
    "terbufos-sulfoxid": "terbufos",
    "terbufos-sulfon": "terbufos",
    "disulfoton-sulfoxid": "disulfoton",
    "fipronil-sulfon": "fipronil",
    "fipronil-sulfid": "fipronil",
    "clethodim-sulfoxid": "clethodim",
    "clethodim-sulfon": "clethodim",
    "clethodim-imin-sulfoxid": "clethodim",
    "clethodim-imin-sulfon": "clethodim",
    "endosulfan-sulfat": "endosulfan",
    "carboxinsulfoxid": "carboxin",
    "aldicarbsulfoxid": "aldicarb",
    "desethylatrazin": "atrazine",
    "desisopropylatrazin": "atrazine",
    "chloridazon-methyl-desphenyl": "chloridazon",
    # Compound "und" → take first part
    "malathion und malaoxon": "malathion",
    "chlordan und oxychlordan": "chlordane",
    "triadimefon und triadimenol": "triadimefon",
    "captan und folpet": "captan",
    "mcpa und mcpb": "mcpa",
    "dichlorprop und dichlorprop-p": "dichlorprop",
    "fenvalerat und esfenvalerat": "fenvalerate",
    "fenvalerat und esfenvalerat rs- und sr-isomere": "fenvalerate",
    "metolachlor und metolachlor-s": "metolachlor",
    "mecoprop und mecoprop-p": "mecoprop",
    "dichlorprop p": "dichlorprop",
    "s-metolachlor": "metolachlor",
    "quizalofop-p": "quizalofop",
    "fenoxaprop-p": "fenoxaprop",
    # Metabolites → parent chemical
    "byi08330-enol": "spirotetramat",
    "byi08330-ketohydroxy": "spirotetramat",
    "byi08330-enol-glucosid": "spirotetramat",
    "byi08330-monohydroxy": "spirotetramat",
    "tfng": "flonicamid",
    "tfna": "flonicamid",
    "tfna-am": "flonicamid",
    "im-2-1": "acetamiprid",
    "mpp": "chlorpyrifos",
    "cga 304075": "cyprodinil",
    "cga 321113": "cyprodinil",
    "bts 40348": "prothioconazole",
    "bts 44595": "prothioconazole",
    "bts 44596": "prothioconazole",
    "bts 9608": "prothioconazole",
    "bts 27271": "prothioconazole",
    "rh9090": "prothioconazole",
    "479m04": "metazachlor",
    "479m08": "metazachlor",
    "479m16": "metazachlor",
    "fm-6-1": "metazachlor",
    "sn 614 276": "metazachlor",
    "sn 614 277": "metazachlor",
    "m800h11": "metazachlor",
    "m650f01": "metazachlor",
    "m25": "metazachlor",
    "n-2": "metazachlor",
    "fluopyram-benzamid": "fluopyram",
    "propamocarb-n-oxid": "propamocarb",
    "5-hydroxy-thiabendazol": "thiabendazole",
    "5-hydroxy-clethodim-sulfon": "clethodim",
    "desmethylchlorpyrifos-methyl": "chlorpyrifos",
    "cis-heptachlorepoxid": "heptachlor",
    "trans-heptachlorepoxid": "heptachlor",
    "heptachlorepoxid": "heptachlor",
    "cis-permethrin": "permethrin",
    "trans-permethrin": "permethrin",
    "cis-resmethrin": "resmethrin",
    "trans-nonachlor": "chlordane",
    "oxychlordan": "chlordane",
    "chlordan": "chlordane",
    "gamma-cyhalothrin": "lambda-cyhalothrin",
    "alpha-cypermethrin": "cypermethrin",
    "beta-cyfluthrin": "cyfluthrin",
    "op-ddt": "ddt",
    "op-dde": "dde",
    "op-ddd": "ddd",
    "pp-ddd": "ddd",
    "hch": "lindane",
    "delta-hch": "lindane",
    "hexachlorbenzol": "hexachlorobenzene",
    "2-chlorethanol": "ethylene oxide",
    "ethylenoxid": "ethylene oxide",
    "orthophenylphenol": "phenylphenol",
    "biphenyl e 230": "biphenyl",
    "denatoniumbenzoat": "denatonium benzoate",
    "deiquat": "diquat",
    "benzalkonium chloride": "benzalkonium chloride",
    "ddac-c10": "didecyldimethylammonium chloride",
    "ddac-c8": "didecyldimethylammonium chloride",
    "bac-c12": "benzalkonium chloride",
    "bac-c14": "benzalkonium chloride",
    "bac-c16": "benzalkonium chloride",
    "bac-c18": "benzalkonium chloride",
    "dioctyldimethylammoniumchlorid": "didecyldimethylammonium chloride",
    "didodecyldimethylammoniumchlorid": "didecyldimethylammonium chloride",
    # Additional German → English
    "terbuthylazin": "terbuthylazine",
    "bupirimat": "bupirimate",
    "fenpyrazamin": "fenpyrazamine",
    "emamectinbenzoat b1a": "emamectin benzoate",
    "metalaxyl m": "mefenoxam",
    "phosphine": "phosphine",
    "trinexapac": "trinexapac",
    "pyrethrin": "pyrethrin",
    "triazole": "triazole",
    "bromide": "bromide",
    "sulfur": "sulfur",
    "3,5,6-trichlor-2-pyridinol": "triclopyr",
    "ethylenthioharnstoff": "ethylene thiourea",
    "propylenthioharnstoff": "propylene thiourea",
    "benzyldimethyltetradecylammonium-chlorid": "benzalkonium chloride",
    "benzylhexadecyldimethylammoniumchlorid": "benzalkonium chloride",
    "benzyldimethyltetradecylammoniumchlorid": "benzalkonium chloride",
    "m 510f01": "metazachlor",
    "gibberellic acid": "gibberellic acid",
    "naphthylacetic acid": "naphthylacetic acid",
    "naphthylacetamide": "naphthylacetamide",
    "paclobutrazol": "paclobutrazol",
    "etridiazol": "etridiazole",
    "1,2,4-triazol": "triazole",
    "dimethylarsinsaeure kakodylsaeure": "cacodylic acid",
    # "Summe aus ... als X" patterns handled by extraction logic below
}

# German descriptive pattern keywords to strip
_GERMAN_DESCRIPTIVE_RE = re.compile(
    r",?\s*(?:summe|gesamt|insgesamt|berechnet|ausgedr[\wü]*ckt|einschlie[\wü]*lich|"
    r"nach hydrolyse|der isomere|metabolit von|salze|insgesamt berechnet|"
    r"gesamt-|abbauprodukt von|frei).*",
    re.IGNORECASE,
)

# Known non-contaminant status strings to reject
_STATUS_KEYWORDS = frozenset({
    "no residue found", "residue detected", "none found", "pesticide screen",
    "pesticide_unknown", "no data",
})


def normalize_contaminant(raw: str) -> str:
    """Normalize a contaminant name to a canonical lowercase form.

    Handles:
    - Case normalization (always lowercase)
    - German umlauts (ä→ae, ö→oe, ü→ue, ß→ss)
    - Curated German → English aliases (e.g., Tebuconazol → tebuconazole)
    - Long German descriptive strings (e.g., "X, Summe aus ..., als X" → X)
    - Semicolon-separated names (e.g., "bpmc; fenobucarb" → "bpmc")
    - Status strings rejected → returns empty string
    """
    if not raw:
        return ""

    cleaned = raw.strip().lower().translate(_UMLAUT_MAP)

    # Reject status strings
    if cleaned in _STATUS_KEYWORDS:
        return ""

    # Direct alias lookup
    if cleaned in _CONTAMINANT_ALIASES:
        return _CONTAMINANT_ALIASES[cleaned]

    # Pattern: "X und Y" compounds → take first part
    if " und " in cleaned:
        first = cleaned.split(" und ")[0].strip()
        if len(first) > 2 and first in _CONTAMINANT_ALIASES:
            return _CONTAMINANT_ALIASES[first]
        if len(first) > 2:
            return first

    # Pattern: German suffix normalization
    # -azol → -azole, -at → -ate, -saeure → acid, -id → -ide
    suffix_map = [
        ("azol", "azole"), ("at ", "ate"), ("saeure", "acid"),
        ("imid", "imide"), ("on ", "one"), ("in ", "ine"),
    ]
    for de_suffix, en_suffix in suffix_map:
        if cleaned.endswith(de_suffix) and len(cleaned) > len(de_suffix) + 2:
            candidate = cleaned[:-len(de_suffix)] + en_suffix
            if candidate in _CONTAMINANT_ALIASES:
                return _CONTAMINANT_ALIASES[candidate]

    # Try extracting from "X, Summe/Gesamt/ausgedrückt als ..." patterns
    extracted = _GERMAN_DESCRIPTIVE_RE.sub("", cleaned).strip().rstrip(",")
    if extracted and extracted != cleaned and len(extracted) > 2:
        if extracted in _CONTAMINANT_ALIASES:
            return _CONTAMINANT_ALIASES[extracted]
        return extracted

    # Try "Metabolit von X" pattern
    metabolit_match = re.search(r"metabolit von\s+(.+?)(?:\s*$)", cleaned)
    if metabolit_match:
        parent = metabolit_match.group(1).strip().rstrip(".")
        if parent in _CONTAMINANT_ALIASES:
            return _CONTAMINANT_ALIASES[parent]
        return parent

    # Strip parenthetical explanations first (before comma/semicolon split)
    # Only if the parenthetical part is long (30+ chars) — short ones are chemical IDs
    # e.g., "fosetyl-al (sum of fosetyl, phosphonic acid...)" → "fosetyl-al"
    # e.g., "thpi (cis-1,2,3,6-tetrahydrophthalimide)" → keep as-is (chemical name)
    paren_match = re.match(r"^([^(]+)\s*\(([^)]{30,})", cleaned)
    if paren_match:
        base = paren_match.group(1).strip().rstrip(",")
        if len(base) > 3:
            if base in _CONTAMINANT_ALIASES:
                return _CONTAMINANT_ALIASES[base]
            return base

    # For semicolon-separated names: take the first part
    # e.g., "bpmc; fenobucarb" → "bpmc"
    # e.g., "chloridazon; pyrazon; 5-amino-..." → "chloridazon"
    if ";" in cleaned:
        first_part = cleaned.split(";")[0].strip()
        if len(first_part) > 2:
            if first_part in _CONTAMINANT_ALIASES:
                return _CONTAMINANT_ALIASES[first_part]
            return first_part

    # For comma-separated names: take the first part
    # e.g., "benzyladenin, 6-benzylamino-purin, 6-bap" → "benzyladenin"
    if "," in cleaned:
        first_part = cleaned.split(",")[0].strip()
        if len(first_part) > 2:
            if first_part in _CONTAMINANT_ALIASES:
                return _CONTAMINANT_ALIASES[first_part]
            return first_part

    # Return cleaned name as-is (already lowercased + umlauts replaced)
    return cleaned


def insert_rows(rows: list[dict], source_name: str, source_file: str = "") -> dict:
    """
    Insert a batch of normalized rows. Routes to product_tests (Tier 1)
    or category_summaries (Tier 2) based on the 'tier' field.
    Skips duplicates via dedup_key.
    Returns counts: {inserted, skipped, failed}

    Optimized with batch executemany() and PRAGMA tuning for bulk inserts.
    """
    inserted = skipped = failed = 0

    # Pre-group rows by table/tier for batch inserts
    product_rows = []
    category_rows = []
    water_rows = []

    for row in rows:
        if not row.get("dedup_key"):
            logger.warning("Row missing dedup_key — skipping: %s", row)
            failed += 1
            continue

        table = row.get("table", "food")
        if table == "water":
            water_rows.append(row)
        else:
            tier = row.get("tier", 1)
            if tier == 1:
                product_rows.append(row)
            else:
                category_rows.append(row)

    with get_connection() as conn:
        # Speed up bulk inserts
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA cache_size=-64000")  # 64MB cache

        # Batch insert product_tests
        if product_rows:
            inserted += _batch_insert_products(conn, product_rows, source_name)

        # Batch insert category_summaries
        if category_rows:
            inserted += _batch_insert_categories(conn, category_rows, source_name)

        # Batch insert water_tests
        if water_rows:
            inserted += _batch_insert_water(conn, water_rows, source_name)

    skipped = len(rows) - inserted - failed
    log_ingest(source_name, "success" if failed == 0 else "partial",
               inserted, skipped, failed, source_file=source_file)
    return {"inserted": inserted, "skipped": skipped, "failed": failed}


def _batch_insert_products(conn, rows: list[dict], source_name: str) -> int:
    """Batch insert product_test rows using executemany."""
    defaults = {
        "contaminant": "glyphosate",
        "measured_ppb": None, "below_detection": 0, "limit_of_detection": None,
        "original_unit": "ppb", "unit_conversion": 1.0,
        "is_organic": 0, "is_grf_certified": 0,
        "methodology_note": None, "raw_file_path": None,
    }
    prepared = []
    for row in rows:
        r = {**defaults, **row}
        r["contaminant"] = normalize_contaminant(r["contaminant"])
        prepared.append(r)

    conn.executemany("""
        INSERT OR IGNORE INTO product_tests (
            source_name, source_url, report_label, published_date, data_year,
            food_category, raw_category, contaminant, product_name,
            measured_ppb, below_detection, limit_of_detection,
            original_unit, unit_conversion, is_organic, is_grf_certified,
            methodology_note, confidence, dedup_key, raw_file_path
        ) VALUES (
            :source_name, :source_url, :report_label, :published_date, :data_year,
            :food_category, :raw_category, :contaminant, :product_name,
            :measured_ppb, :below_detection, :limit_of_detection,
            :original_unit, :unit_conversion, :is_organic, :is_grf_certified,
            :methodology_note, :confidence, :dedup_key, :raw_file_path
        )
    """, prepared)
    return conn.execute("SELECT changes()").fetchone()[0]


def _batch_insert_categories(conn, rows: list[dict], source_name: str) -> int:
    """Batch insert category_summary rows using executemany."""
    defaults = {
        "contaminant": "glyphosate",
        "samples_total": 0, "samples_detected": 0, "detection_rate": 0.0,
        "avg_ppb": None, "max_ppb": None, "p95_ppb": None,
        "median_ppb": None, "min_ppb": None,
        "original_unit": "ppb", "unit_conversion": 1.0,
        "is_organic": 0, "methodology_note": None, "raw_file_path": None,
    }
    prepared = []
    for row in rows:
        r = {**defaults, **row}
        r["contaminant"] = normalize_contaminant(r["contaminant"])
        prepared.append(r)

    conn.executemany("""
        INSERT OR IGNORE INTO category_summaries (
            source_name, source_url, report_label, published_date, data_year,
            food_category, raw_category, contaminant,
            samples_total, samples_detected, detection_rate, avg_ppb, max_ppb, p95_ppb,
            median_ppb, min_ppb,
            original_unit, unit_conversion, is_organic,
            methodology_note, confidence, dedup_key, raw_file_path
        ) VALUES (
            :source_name, :source_url, :report_label, :published_date, :data_year,
            :food_category, :raw_category, :contaminant,
            :samples_total, :samples_detected, :detection_rate, :avg_ppb, :max_ppb, :p95_ppb,
            :median_ppb, :min_ppb,
            :original_unit, :unit_conversion, :is_organic,
            :methodology_note, :confidence, :dedup_key, :raw_file_path
        )
    """, prepared)
    return conn.execute("SELECT changes()").fetchone()[0]


def _batch_insert_water(conn, rows: list[dict], source_name: str) -> int:
    """Batch insert water_test rows using executemany."""
    defaults = {
        "contaminant": "glyphosate",
        "state": None, "county": None, "site_type": None, "site_id": None,
        "latitude": None, "longitude": None,
        "measured_ppb": None, "below_detection": 0, "detection_limit_ppb": None,
        "analytical_method": None, "sample_date": None,
        "is_aggregate": 0, "samples_total": None, "samples_detected": None,
        "detection_rate": None, "avg_ppb": None, "max_ppb": None,
        "methodology_note": None, "confidence": None,
    }
    prepared = []
    for row in rows:
        r = {**defaults, **row}
        r["contaminant"] = normalize_contaminant(r["contaminant"])
        prepared.append(r)

    conn.executemany("""
        INSERT OR IGNORE INTO water_tests (
            source_name, source_url, report_label, data_year,
            contaminant,
            state, county, site_type, site_id, latitude, longitude,
            water_type, measured_ppb, below_detection, detection_limit_ppb,
            analytical_method, sample_date, is_aggregate,
            samples_total, samples_detected, detection_rate, avg_ppb, max_ppb,
            methodology_note, confidence, dedup_key
        ) VALUES (
            :source_name, :source_url, :report_label, :data_year,
            :contaminant,
            :state, :county, :site_type, :site_id, :latitude, :longitude,
            :water_type, :measured_ppb, :below_detection, :detection_limit_ppb,
            :analytical_method, :sample_date, :is_aggregate,
            :samples_total, :samples_detected, :detection_rate, :avg_ppb, :max_ppb,
            :methodology_note, :confidence, :dedup_key
        )
    """, prepared)
    return conn.execute("SELECT changes()").fetchone()[0]


def _insert_product(conn, row: dict) -> int:
    """Insert a Tier 1 product test row."""
    defaults = {
        "contaminant": "glyphosate",
        "measured_ppb": None, "below_detection": 0, "limit_of_detection": None,
        "original_unit": "ppb", "unit_conversion": 1.0,
        "is_organic": 0, "is_grf_certified": 0,
        "methodology_note": None, "raw_file_path": None,
    }
    r = {**defaults, **row}
    original_contaminant = r["contaminant"]
    r["contaminant"] = normalize_contaminant(r["contaminant"])
    # Normalize food_category to canonical key
    if r.get("food_category"):
        normalized_cat = normalize_category(r["food_category"], conn=conn)
        if normalized_cat:
            r["food_category"] = normalized_cat
    conn.execute("""
        INSERT OR IGNORE INTO product_tests (
            source_name, source_url, report_label, published_date, data_year,
            food_category, raw_category, contaminant, product_name,
            measured_ppb, below_detection, limit_of_detection,
            original_unit, unit_conversion, is_organic, is_grf_certified,
            methodology_note, confidence, dedup_key, raw_file_path
        ) VALUES (
            :source_name, :source_url, :report_label, :published_date, :data_year,
            :food_category, :raw_category, :contaminant, :product_name,
            :measured_ppb, :below_detection, :limit_of_detection,
            :original_unit, :unit_conversion, :is_organic, :is_grf_certified,
            :methodology_note, :confidence, :dedup_key, :raw_file_path
        )
    """, r)
    changes = conn.execute("SELECT changes()").fetchone()[0]
    if changes and r["contaminant"] != original_contaminant:
        log_data_version("product_tests", conn.execute("SELECT last_insert_rowid()").fetchone()[0],
                         "contaminant", original_contaminant, r["contaminant"])
    return changes


def _insert_water(conn, row: dict) -> int:
    """Insert a water_tests row."""
    defaults = {
        "contaminant": "glyphosate",
        "state": None, "county": None, "site_type": None, "site_id": None,
        "latitude": None, "longitude": None,
        "measured_ppb": None, "below_detection": 0, "detection_limit_ppb": None,
        "analytical_method": None, "sample_date": None,
        "is_aggregate": 0, "samples_total": None, "samples_detected": None,
        "detection_rate": None, "avg_ppb": None, "max_ppb": None,
        "methodology_note": None, "confidence": None,
    }
    r = {**defaults, **row}
    original_contaminant = r["contaminant"]
    r["contaminant"] = normalize_contaminant(r["contaminant"])
    conn.execute("""
        INSERT OR IGNORE INTO water_tests (
            source_name, source_url, report_label, data_year,
            contaminant,
            state, county, site_type, site_id, latitude, longitude,
            water_type, measured_ppb, below_detection, detection_limit_ppb,
            analytical_method, sample_date, is_aggregate,
            samples_total, samples_detected, detection_rate, avg_ppb, max_ppb,
            methodology_note, confidence, dedup_key
        ) VALUES (
            :source_name, :source_url, :report_label, :data_year,
            :contaminant,
            :state, :county, :site_type, :site_id, :latitude, :longitude,
            :water_type, :measured_ppb, :below_detection, :detection_limit_ppb,
            :analytical_method, :sample_date, :is_aggregate,
            :samples_total, :samples_detected, :detection_rate, :avg_ppb, :max_ppb,
            :methodology_note, :confidence, :dedup_key
        )
    """, r)
    changes = conn.execute("SELECT changes()").fetchone()[0]
    if changes and r["contaminant"] != original_contaminant:
        log_data_version("water_tests", conn.execute("SELECT last_insert_rowid()").fetchone()[0],
                         "contaminant", original_contaminant, r["contaminant"])
    return changes


def _insert_category(conn, row: dict) -> int:
    """Insert a Tier 2 category summary row."""
    defaults = {
        "contaminant": "glyphosate",
        "samples_total": 0, "samples_detected": 0, "detection_rate": 0.0,
        "avg_ppb": None, "max_ppb": None, "p95_ppb": None,
        "median_ppb": None, "min_ppb": None,
        "original_unit": "ppb", "unit_conversion": 1.0,
        "is_organic": 0, "methodology_note": None, "raw_file_path": None,
    }
    r = {**defaults, **row}
    original_contaminant = r["contaminant"]
    r["contaminant"] = normalize_contaminant(r["contaminant"])
    # Normalize food_category to canonical key for consistent MRL lookups
    if r.get("food_category"):
        normalized_cat = normalize_category(r["food_category"], conn=conn)
        if normalized_cat:
            r["food_category"] = normalized_cat
    conn.execute("""
        INSERT OR IGNORE INTO category_summaries (
            source_name, source_url, report_label, published_date, data_year,
            food_category, raw_category, contaminant,
            samples_total, samples_detected, detection_rate, avg_ppb, max_ppb, p95_ppb,
            median_ppb, min_ppb,
            original_unit, unit_conversion, is_organic,
            methodology_note, confidence, dedup_key, raw_file_path
        ) VALUES (
            :source_name, :source_url, :report_label, :published_date, :data_year,
            :food_category, :raw_category, :contaminant,
            :samples_total, :samples_detected, :detection_rate, :avg_ppb, :max_ppb, :p95_ppb,
            :median_ppb, :min_ppb,
            :original_unit, :unit_conversion, :is_organic,
            :methodology_note, :confidence, :dedup_key, :raw_file_path
        )
    """, r)
    changes = conn.execute("SELECT changes()").fetchone()[0]
    if changes and r["contaminant"] != original_contaminant:
        log_data_version("category_summaries", conn.execute("SELECT last_insert_rowid()").fetchone()[0],
                         "contaminant", original_contaminant, r["contaminant"])
    return changes


def _insert_ingredient(conn, row: dict) -> int:
    """Insert an ingredient record (regulatory reference data)."""
    defaults = {
        "contaminant_type": None,
        "aliases": None, "flag_types": None, "flags": None,
        "ntp_classification": None, "iarc_classification": None,
        "fda_status": None, "fda_cfr_citation": None,
        "verified_date": None, "verified_by": "AR_Company_internal",
    }
    r = {**defaults, **row}
    conn.execute("""
        INSERT OR IGNORE INTO ingredients (
            ingredient_id, display_name, contaminant_type, aliases, flag_types, flags,
            ntp_classification, iarc_classification,
            fda_status, fda_cfr_citation, verified_date, verified_by
        ) VALUES (
            :ingredient_id, :display_name, :contaminant_type, :aliases, :flag_types, :flags,
            :ntp_classification, :iarc_classification,
            :fda_status, :fda_cfr_citation, :verified_date, :verified_by
        )
    """, r)
    return conn.execute("SELECT changes()").fetchone()[0]


def _insert_regulatory_flag(conn, row: dict) -> int:
    """Insert a regulatory flag record."""
    defaults = {
        "contaminant_type": None,
        "regulation_citation": None,
        "effective_date": None, "compliance_date": None, "notes": None,
    }
    r = {**defaults, **row}
    conn.execute("""
        INSERT OR IGNORE INTO regulatory_flags (
            flag_id, ingredient_id, contaminant_type, jurisdiction, flag_type,
            regulatory_body, regulation_citation, source_url,
            effective_date, compliance_date, notes
        ) VALUES (
            :flag_id, :ingredient_id, :contaminant_type, :jurisdiction, :flag_type,
            :regulatory_body, :regulation_citation, :source_url,
            :effective_date, :compliance_date, :notes
        )
    """, r)
    return conn.execute("SELECT changes()").fetchone()[0]


def _insert_commodity(conn, row: dict) -> int:
    """Insert a commodity record."""
    defaults = {
        "ingredient_aliases": None, "pdp_commodity_code": None,
        "pdp_year_latest": None, "residues": None,
        "dirty_dozen": 0, "last_pdp_update": None,
        "consumption_tier": "occasional",
    }
    r = {**defaults, **row}
    conn.execute("""
        INSERT OR IGNORE INTO commodities (
            commodity_slug, display_name, ingredient_aliases,
            pdp_commodity_code, pdp_year_latest, residues,
            dirty_dozen, last_pdp_update, consumption_tier
        ) VALUES (
            :commodity_slug, :display_name, :ingredient_aliases,
            :pdp_commodity_code, :pdp_year_latest, :residues,
            :dirty_dozen, :last_pdp_update, :consumption_tier
        )
    """, r)
    return conn.execute("SELECT changes()").fetchone()[0]


def _insert_alternative(conn, row: dict) -> int:
    """Insert an alternatives record."""
    defaults = {
        "flagged_product_name": None, "risk_label": None,
        "flag_summary": None, "alternatives": None, "last_updated": None,
    }
    r = {**defaults, **row}
    conn.execute("""
        INSERT OR IGNORE INTO alternatives (
            lookup_key, lookup_type, flagged_product_name,
            risk_label, flag_summary, alternatives, last_updated
        ) VALUES (
            :lookup_key, :lookup_type, :flagged_product_name,
            :risk_label, :flag_summary, :alternatives, :last_updated
        )
    """, r)
    return conn.execute("SELECT changes()").fetchone()[0]


def insert_ingredients(rows: list[dict]) -> dict:
    """Batch insert ingredient records."""
    inserted = skipped = failed = 0
    with get_connection() as conn:
        for row in rows:
            try:
                changes = _insert_ingredient(conn, row)
                if changes:
                    inserted += 1
                else:
                    skipped += 1
            except sqlite3.Error as e:
                logger.error("Insert ingredient failed for %s: %s", row.get("ingredient_id"), e)
                failed += 1
    return {"inserted": inserted, "skipped": skipped, "failed": failed}


def insert_regulatory_flags(rows: list[dict]) -> dict:
    """Batch insert regulatory flag records."""
    inserted = skipped = failed = 0
    with get_connection() as conn:
        for row in rows:
            try:
                changes = _insert_regulatory_flag(conn, row)
                if changes:
                    inserted += 1
                else:
                    skipped += 1
            except sqlite3.Error as e:
                logger.error("Insert flag failed for %s: %s", row.get("flag_id"), e)
                failed += 1
    return {"inserted": inserted, "skipped": skipped, "failed": failed}


def insert_commodities(rows: list[dict]) -> dict:
    """Batch insert commodity records."""
    inserted = skipped = failed = 0
    with get_connection() as conn:
        for row in rows:
            try:
                changes = _insert_commodity(conn, row)
                if changes:
                    inserted += 1
                else:
                    skipped += 1
            except sqlite3.Error as e:
                logger.error("Insert commodity failed for %s: %s", row.get("commodity_slug"), e)
                failed += 1
    return {"inserted": inserted, "skipped": skipped, "failed": failed}


def insert_alternatives(rows: list[dict]) -> dict:
    """Batch insert alternatives records."""
    inserted = skipped = failed = 0
    with get_connection() as conn:
        for row in rows:
            try:
                changes = _insert_alternative(conn, row)
                if changes:
                    inserted += 1
                else:
                    skipped += 1
            except sqlite3.Error as e:
                logger.error("Insert alternative failed for %s: %s", row.get("lookup_key"), e)
                failed += 1
    return {"inserted": inserted, "skipped": skipped, "failed": failed}


def log_ingest(source_name, status, inserted=0, skipped=0, failed=0,
               error_message=None, source_file=""):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO ingest_log
                (source_name, status, rows_inserted, rows_skipped, rows_failed,
                 error_message, source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (source_name, status, inserted, skipped, failed, error_message, source_file))


def log_data_version(table_name, row_id, field_name, old_value, new_value,
                     changed_by="pipeline"):
    """Record a field-level change in the data_versions audit table."""
    dedup = build_dedup_key(table_name, row_id, field_name, str(new_value))
    try:
        with get_connection() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO data_versions
                    (table_name, row_id, field_name, old_value, new_value,
                     changed_by, dedup_key)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (table_name, row_id, field_name, str(old_value), str(new_value),
                  changed_by, dedup))
    except sqlite3.Error as e:
        logger.debug("data_versions insert skipped: %s", e)


def get_data_versions(table_name=None, row_id=None, limit=100):
    """Query the data_versions audit trail."""
    conditions = []
    params = []
    if table_name:
        conditions.append("table_name = ?")
        params.append(table_name)
    if row_id is not None:
        conditions.append("row_id = ?")
        params.append(row_id)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(f"""
            SELECT table_name, row_id, field_name, old_value, new_value,
                   changed_at, changed_by
            FROM data_versions{where}
            ORDER BY changed_at DESC
            LIMIT ?
        """, params).fetchall()
    return [dict(r) for r in rows]
