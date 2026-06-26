"""
seed_plu_codes.py

One-time seed script for the `plu_codes` table (IFPS Price Look-Up codes).

Produce has no UPC barcode, so a 4-5 digit PLU code is how a bulk produce
item resolves to a commodity slug -> Layer 2 (USDA PDP) residue data.

Sources (in data/raw_data/plu/), deduped by PLU with priority:
    1. commodities.csv          (authoritative IFPS fruits export, 61 fruits)
    2. Official NRS PLU Database.pdf  (current rotation; adds veg/herbs/nuts)
    3. 2011-PLU-Listing1.pdf    (alphabetical; fills remaining gaps)

Idempotent: INSERT OR REPLACE keyed on dedup_key = build_dedup_key('PLU', plu),
so re-running with improved parsing/mapping updates existing rows.

Usage:
    python seed_plu_codes.py              # seed from all sources
    python seed_plu_codes.py --dry-run    # print counts/sources, no insert
"""

import argparse
import csv
import logging
import os
import re
import sys
from collections import Counter

# Make `from db.database import ...` resolve regardless of cwd.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from db.database import initialize, build_dedup_key, insert_plu_codes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_plu")

PLU_DIR = os.path.join(_HERE, "raw_data", "plu")
CSV_PATH = os.path.join(PLU_DIR, "commodities.csv")
NRS_PDF = os.path.join(PLU_DIR, "Official NRS PLU Database.pdf")
PDF_2011 = os.path.join(PLU_DIR, "2011-PLU-Listing1.pdf")

# ═══════════════════════════════════════════════════════════════════════════
# Commodity -> slug mapping (PLU commodity name -> commodities.commodity_slug)
# Keys are normalized via _norm() (lowercase, parentheticals stripped, "/" and
# punctuation -> spaces, collapsed). Unmapped exotic produce -> commodity_slug
# is None, which is the honest "no PDP residue data" path.
# ═══════════════════════════════════════════════════════════════════════════
SLUG_MAP = {
    # ── Fruits ───────────────────────────────────────────────────────────
    "apples": "apple", "apple": "apple",
    "apricots": "apricot", "apricot": "apricot",
    "avocados": "avocado", "avocado": "avocado",
    "bananas": "banana", "banana": "banana", "plantain": "banana",
    "cherries": "cherry", "cherry": "cherry",
    "coconuts": "coconut", "coconut": "coconut",
    "currants": "currants", "currant": "currants",
    "dates": "dates", "date": "dates",
    "figs": "fig", "fig": "fig",
    "grapefruit": "grapefruit", "grapefruits": "grapefruit",
    "grapes": "grape", "grape": "grape", "raisins": "grape",
    "kiwifruit": "kiwi", "kiwi": "kiwi", "kiwi fruit": "kiwi",
    "lemons": "lemon", "lemon": "lemon",
    "limes": "lime", "lime": "lime",
    "mango": "mango", "mangoes": "mango", "mangos": "mango",
    "nectarine": "nectarine", "nectarines": "nectarine",
    "oranges": "orange", "orange": "orange",
    "tangerines mandarins": "orange", "tangerine mandarin": "orange",
    "tangerines": "orange", "tangerine": "orange", "mandarins": "orange",
    "mandarin": "orange", "clementines": "orange", "clementine": "orange",
    "tangelos": "orange", "tangelo": "orange",
    "papaya pawpaw": "papaya", "papaya": "papaya", "pawpaw": "papaya",
    "peaches": "peach", "peach": "peach",
    "pears": "pear", "pear": "pear",
    "persimmon": "persimmon", "persimmons": "persimmon",
    "pineapple": "pineapple", "pineapples": "pineapple",
    "plums": "plum", "plum": "plum", "prunes": "plum",
    "plumcot": "plum", "plumcots": "plum",
    # ── Vegetables ───────────────────────────────────────────────────────
    "peppers": "pepper", "pepper": "pepper", "chili pepper": "chili pepper",
    "chili peppers": "chili pepper", "chili": "chili pepper", "chilli": "chili pepper",
    "squash": "squash", "zucchini": "squash",
    "pumpkin": "pumpkin", "pumpkins": "pumpkin",
    "onions": "onion", "onion": "onion", "shallots": "onion",
    "scallion": "onion", "scallions": "onion", "green onion": "onion",
    "lettuce": "lettuce", "romaine": "lettuce", "iceberg": "lettuce",
    "tomatoes": "tomato", "tomato": "tomato",
    "cucumbers": "cucumber", "cucumber": "cucumber", "gherkin": "cucumber",
    "corn": "corn", "sweetcorn": "corn", "maize": "corn",
    "potatoes": "potato", "potato": "potato",
    "carrots": "carrot", "carrot": "carrot",
    "celery": "celery",
    "cabbage": "cabbage",
    "cauliflower": "cauliflower",
    "broccoli": "broccoli",
    "artichokes": "artichoke", "artichoke": "artichoke",
    "asparagus": "asparagus",
    "eggplant": "eggplant", "eggplants": "eggplant", "aubergine": "eggplant",
    "mushrooms": "mushroom", "mushroom": "mushroom",
    "radish": "radish", "radishes": "radish", "radicchio": "radish",
    "beets": "beet", "beet": "beet", "beetroot": "beet",
    "kale": "kale",
    "spinach": "spinach",
    "turnips": "turnip", "turnip": "turnip",
    "rutabaga": "rutabaga", "swede": "rutabaga", "turnip rutabaga swede": "rutabaga",
    "parsnip": "parsnip", "parsnips": "parsnip",
    "leek": "leek", "leeks": "leek",
    "fennel": "fennel",
    "kohlrabi": "kohlrabi",
    "rhubarb": "rhubarb",
    "brussels sprouts": "brussels sprouts", "brussels sprout": "brussels sprouts",
    "okra": "okra",
    "beans": "beans", "bean": "beans", "green beans": "beans",
    "peas": "peas", "pea": "peas",
    "garlic": "garlic",
    "chard": "chard", "swiss chard": "chard",
    "horseradish": "horseradish", "horseradish root": "horseradish",
    "yucca root": "cassava", "yucca": "cassava", "yuca": "cassava", "cassava": "cassava",
    "collard greens": "collard greens",
    # ── Herbs ────────────────────────────────────────────────────────────
    "herbs": "herbs", "mint": "mint", "parsley": "parsley", "ginger": "ginger",
    "turmeric": "turmeric", "marjoram": "marjoram", "tarragon": "tarragon",
    "anise": "anise", "aniseed": "anise",
    # ── Nuts ─────────────────────────────────────────────────────────────
    "walnuts": "walnut", "walnut": "walnut",
    "almonds": "almond", "almond": "almond",
    "cashews": "cashew", "cashew": "cashew",
    "hazelnuts": "hazelnut", "hazelnut": "hazelnut",
    "chestnuts": "chestnut", "chestnut": "chestnut",
    "peanuts": "peanut", "peanut": "peanut",
}

# Sub-category keyword resolvers for grouped commodities.
BERRY_KW = {
    "strawberr": "strawberry", "blueberr": "blueberry", "raspberr": "raspberry",
    "blackberr": "blackberry", "cranberr": "cranberry",
    "boysenberr": "blackberry", "currant": "currants",
}
MELON_KW = {
    "watermelon": "watermelon", "cantaloup": "cantaloupe",
    "muskmelon": "cantaloupe", "honeydew": "melon", "galia": "melon",
    "charentais": "melon", "canary": "melon", "casaba": "melon",
    "crenshaw": "melon",
}
NUT_KW = {
    "walnut": "walnut", "almond": "almond", "cashew": "cashew",
    "pecan": "walnut", "hazelnut": "hazelnut", "filbert": "hazelnut",
    "chestnut": "chestnut", "peanut": "peanut", "pistachio": "walnut",
}

_HERBS = {
    "herbs", "mint", "parsley", "ginger", "turmeric", "basil", "oregano",
    "rosemary", "thyme", "sage", "cilantro", "coriander", "dill", "marjoram",
    "tarragon", "anise", "ajwain", "lemongrass", "chives", "lavender",
}
_NUTS = {
    "nuts", "almond", "almonds", "walnut", "walnuts", "cashew", "cashews",
    "pecan", "pecans", "hazelnut", "hazelnuts", "chestnut", "chestnuts",
    "peanut", "peanuts", "pistachio", "pistachios",
}
_VEG = {
    "pepper", "peppers", "squash", "zucchini", "pumpkin", "pumpkins",
    "onion", "onions", "shallots", "scallion", "scallions", "lettuce",
    "romaine", "iceberg", "tomato", "tomatoes", "cucumber", "cucumbers",
    "corn", "potato", "potatoes", "carrot", "carrots", "celery", "cabbage",
    "cauliflower", "broccoli", "artichoke", "artichokes", "asparagus",
    "eggplant", "eggplants", "aubergine", "mushroom", "mushrooms", "radish",
    "radishes", "radicchio", "beet", "beets", "beetroot", "kale", "spinach",
    "turnip", "turnips", "rutabaga", "swede", "parsnip", "parsnips", "leek",
    "leeks", "fennel", "kohlrabi", "rhubarb", "brussels", "okra", "beans",
    "bean", "peas", "pea", "garlic", "chard", "horseradish", "cassava",
    "yuca", "yucca", "greens", "collard", "jicama", "taro", "lotus",
    "endive", "chicory", "cactus", "cardoon", "choy", "gobo", "arracach",
    "malanga", "fiddlehead", "waterchestnut", "waterchestnuts", "tamarillo",
    "yam", "chili", "yams",
}

_MOJIBAKE = {"madroa": "madroña"}  # post-�-strip repair tokens

_SIZE_WORDS = {
    "small", "large", "medium", "med", "extra", "extra large", "jumbo",
    "mini", "nominal", "long", "short", "regular", "standard", "fancy",
}


# ═══════════════════════════════════════════════════════════════════════════
# Normalization / mapping helpers
# ═══════════════════════════════════════════════════════════════════════════
def _norm(name: str) -> str:
    name = (name or "").lower()
    name = re.sub(r"\([^)]*\)", " ", name)          # strip parentheticals
    name = name.replace("/", " ")
    name = re.sub(r"[^a-z0-9\s]", " ", name)         # drop punctuation
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _clean(s):
    """Strip replacement chars (Latin-1 mojibake) + repair known tokens."""
    if not s:
        return None
    s = s.replace("�", "").strip()
    s = re.sub(r"\s+", " ", s)
    low = s.lower()
    for bad, good in _MOJIBAKE.items():
        if bad in low:
            s = re.sub(re.escape(bad), good, s, flags=re.IGNORECASE)
    s = s.strip(" ,/-")
    return s or None


def _display(name: str) -> str:
    """Title-case each Unicode alpha run: 'APPLES'->'Apples', 'MADROÑA'->'Madroña'."""
    if not name:
        return name
    lowered = name.lower()
    return re.sub(r"[^\W\d_]+", lambda m: m.group(0).capitalize(), lowered, flags=re.UNICODE)


def _kw(text, table):
    t = (text or "").lower()
    for needle, slug in table.items():
        if needle in t:
            return slug
    return None


def _resolve_slug(commodity, variety):
    """Map a PLU commodity (+variety) to a commodity slug, or None if exotic."""
    disp = commodity or ""
    var = variety or ""
    cnorm = _norm(disp)
    fnorm = _norm(f"{disp} {var}")
    vnorm = _norm(var)

    if cnorm == "berries":
        return _kw(f"{disp} {var}", BERRY_KW)
    if cnorm == "melon":
        return _kw(fnorm, MELON_KW) or "melon"
    if cnorm == "nuts":
        return _kw(f"{disp} {var}", NUT_KW)

    for key in (cnorm, fnorm, vnorm):
        if key and key in SLUG_MAP:
            return SLUG_MAP[key]
    return None


def _classify(commodity, variety=""):
    """Best-effort produce category from commodity/variety text."""
    toks = set(_norm(f"{commodity or ''} {variety or ''}").split())
    if toks & _HERBS:
        return "Herbs"
    if toks & _NUTS:
        return "Nuts"
    if toks & _VEG:
        return "Vegetables"
    return "Fruits"


def _record(plu, commodity, variety, size, source, **extra):
    commodity = _clean(commodity)
    variety = _clean(variety)
    size = _clean(size)
    rec = {
        "plu": str(plu),
        "commodity_slug": _resolve_slug(commodity, variety),
        "commodity_display": _display(commodity),
        "variety": variety,
        "size": size,
        "category": _classify(commodity, variety),
        "source_file": source,
        "dedup_key": build_dedup_key("PLU", str(plu)),
    }
    rec.update(extra)
    return rec


# ═══════════════════════════════════════════════════════════════════════════
# Loaders
# ═══════════════════════════════════════════════════════════════════════════
def _pdf_lines(path):
    import pdfplumber
    out = []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            t = pg.extract_text() or ""
            out.extend(ln.rstrip() for ln in t.splitlines())
    return out


def load_csv():
    """Loader 1 (priority 1): commodities.csv — authoritative fruits export."""
    rows = []
    if not os.path.exists(CSV_PATH):
        logger.warning("CSV not found: %s", CSV_PATH)
        return rows
    seen = set()
    with open(CSV_PATH, encoding="utf-8-sig", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            plu = (r.get("Plu") or "").strip()
            if not re.fullmatch(r"\d{4,5}", plu) or plu in seen:
                continue
            seen.add(plu)
            commodity = (r.get("Commodity") or "").strip()
            variety = (r.get("Variety") or "").strip() or None
            rows.append(_record(
                plu, commodity, variety, (r.get("Size") or "").strip() or None,
                "commodities.csv",
                botanical=(r.get("Botanical") or "").strip() or None,
                aka=(r.get("Aka") or "").strip() or None,
                restrictions=(r.get("Restrictions") or "").strip() or None,
                notes=(r.get("Notes") or "").strip() or None,
                status=(r.get("Status") or "Approved").strip() or "Approved",
            ))
    return rows


_NRS_LINE = re.compile(r"^(\d{4,5})\s+(.+?)\s+\((\d{4,5})\)\s*(.*)$")


def load_nrs():
    """Loader 2 (priority 2): Official NRS PLU Database.pdf — current rotation.

    Line format: ``{PLU} {Commodity} {Variety} ({PLU}) {Size?}``
    The commodity is the first token; the rest is the variety; trailing text
    after the parenthesized PLU is a free-text size (Small, Extra Large,
    500g/1 Litre, 3-7 LBS, ...). Adds vegetables/herbs/nuts the CSV lacks.
    """
    rows = []
    if not os.path.exists(NRS_PDF):
        logger.warning("NRS PDF not found: %s", NRS_PDF)
        return rows
    for ln in _pdf_lines(NRS_PDF):
        m = _NRS_LINE.match(ln)
        if not m:
            continue
        plu, body, plu2, size = m.group(1), m.group(2).strip(), m.group(3), m.group(4).strip()
        if plu != plu2:
            continue
        toks = body.split()
        commodity = toks[0] if toks else body
        variety = " ".join(toks[1:]) if len(toks) > 1 else None
        rows.append(_record(plu, commodity, variety, size or None, "NRS"))
    return rows


_PAREN = re.compile(r"\((\d{4,5})\)")
_BULLET_PAIR = re.compile(r"(.*?)\s*\((\d{4,5})\)")


def _split_variety_size(text):
    """'Akane, small' -> ('Akane','small'); 'Cox Orange Pippin' -> (text, None)."""
    if "," in text:
        head, tail = text.rsplit(",", 1)
        tail_low = tail.strip().lower()
        if tail_low in _SIZE_WORDS or tail_low.replace(" ", "") == "extralarge":
            return head.strip(), tail_low
    return text, None


def _parse_2011_bullet(header, body):
    """Parse one grouped bullet line into >=1 PLU record(s)."""
    body = re.sub(r"^[••�\-\*\s]+", "", body).strip()  # strip bullet glyph
    recs = []
    matches = list(_BULLET_PAIR.finditer(body))
    if not matches:
        return recs
    base_variety, base_size = _split_variety_size(matches[0].group(1).strip())
    for i, m in enumerate(matches):
        plu = m.group(2)
        if i == 0:
            variety, size = base_variety, base_size
        else:
            qualifier = m.group(1).strip().strip(",").strip()
            variety, size = base_variety, (qualifier or None)
        recs.append(_record(plu, header, variety, size, "2011_innvista"))
    return recs


def load_2011():
    """Loader 3 (priority 3): 2011-PLU-Listing1.pdf — alphabetical grouped list.

    Commodity header line, then ``• variety (plu)`` / ``• variety, small (plu), large (plu)``
    bullets. Fills herbs/sprouts/exotics the other sources lack.
    """
    rows = []
    if not os.path.exists(PDF_2011):
        logger.warning("2011 PDF not found: %s", PDF_2011)
        return rows
    header = None
    for ln in _pdf_lines(PDF_2011):
        s = ln.strip()
        if not s or "PLU Listing" in s:
            continue
        if _PAREN.search(s):
            if header is None:
                continue
            rows.extend(_parse_2011_bullet(header, s))
        elif len(s) <= 30 and s[0].isalpha():
            header = s
    return rows


def merge(*sources):
    """Dedupe by PLU; earlier sources win (call in priority order)."""
    by_plu = {}
    for src in sources:
        for rec in src:
            by_plu.setdefault(rec["plu"], rec)
    return list(by_plu.values())


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Seed plu_codes from CSV + PDFs")
    parser.add_argument("--dry-run", action="store_true", help="Print counts without inserting")
    args = parser.parse_args()

    logger.info("Initializing database")
    initialize()

    csv_rows = load_csv()
    nrs_rows = load_nrs()
    rows_2011 = load_2011()
    logger.info("Loaded CSV=%d, NRS=%d, 2011=%d", len(csv_rows), len(nrs_rows), len(rows_2011))

    merged = merge(csv_rows, nrs_rows, rows_2011)
    mapped = sum(1 for r in merged if r["commodity_slug"])
    logger.info("Unique PLUs: %d  (mapped to a commodity slug: %d, unmapped: %d)",
                len(merged), mapped, len(merged) - mapped)
    logger.info("By source (after dedupe): %s", dict(Counter(r["source_file"] for r in merged)))
    logger.info("By category: %s", dict(Counter(r["category"] for r in merged)))

    if args.dry_run:
        for r in merged[:25]:
            logger.info("  [DRY RUN] %s -> %-14s | %s / %s",
                        r["plu"], r["commodity_slug"], r["commodity_display"], r["variety"])
        logger.info("[DRY RUN] would insert %d rows", len(merged))
        return

    result = insert_plu_codes(merged)
    logger.info("PLU codes: inserted=%d, skipped=%d, failed=%d",
                result["inserted"], result["skipped"], result["failed"])
    logger.info("Done!")


if __name__ == "__main__":
    main()
