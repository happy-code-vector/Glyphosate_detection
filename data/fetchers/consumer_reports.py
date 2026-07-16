"""
fetchers/consumer_reports.py

Consumer Reports food-contaminant testing — Tier 1 (product-level).

Consumer Reports commissions independent lab testing and publishes
investigations that name specific products and the contaminants measured
in them, e.g. "a serving of Jell-O Zero Instant Pudding contained 14.2
milligrams of Red 40".

Access note: CR's contaminant-investigation articles are publicly readable
without a subscription (verified 2026-07). The fallback below is NOT for a
paywall — CR does not login-wall these investigations. It triggers only
when the search listing or article prose cannot be parsed.

MULTI-CONTAMINANT + PER-SERVING MASS
------------------------------------
CR reports amounts as MASS PER SERVING (micrograms / milligrams per
serving), NOT concentration (ppb). There is no honest per-serving -> ppb
conversion without serving weight, which CR does not state. So rows are
stored faithfully with:

    - measured_ppb    = NULL   (deliberately — we will not fake a concentration)
    - original_unit   = "mg/serving" | "µg/serving" | "g/serving"
    - unit_conversion = 1.0    (no conversion; the original unit is recorded as-is)

The detection engine renders these as risk_level "unknown" (no ppb to
score) — they are reference / display rows, not risk-tier drivers. This
keeps the ppb-based risk engine (`measured_ppb / tolerance_ppb`) free of
fabricated-unit data.

Strategy
--------
1. Discover investigation articles via the CR universal search endpoint.
2. Fetch each article's HTML.
3. Extract (product, contaminant, amount, unit) tuples from the article
   prose using the "serving of <product> contained <amount> <unit> of
   <contaminant>" pattern, resolving contaminants to registry slugs.
4. Fall back to a small set of verified product-level rows (taken from
   published CR investigations) when discovery / parsing yields nothing.

Limitation: the full per-product data tables on CR are JS-rendered widgets
and are not in the static HTML. This scraper captures the headline product
callouts embedded in article prose, not the full widget dataset.
"""

import logging
import re
from pathlib import Path
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from contaminants import CONTAMINANTS
from fetchers.base import BaseFetcher, fetch_page, RAW_DATA_DIR
from db.database import normalize_category, build_dedup_key

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source metadata
# ---------------------------------------------------------------------------
BASE_URL = "https://www.consumerreports.org"
SEARCH_URL = BASE_URL + "/search/?query={query}"

# Queries that surface contaminant-testing investigations.
SEARCH_QUERIES = (
    "food contaminants",
    "heavy metals food",
    "food additives",
    "pesticides food",
    "lead in food",
    "arsenic rice",
    "glyphosate",
)
MAX_ARTICLES = 12

DEFAULT_PUBLISHED_DATE = "2025-01-01"
DEFAULT_DATA_YEAR = 2025
METHODOLOGY_NOTE = (
    "Consumer Reports independent lab testing, reported as mass per serving "
    "(not concentration). measured_ppb is intentionally NULL — see "
    "original_unit. Confidence is 'high' for rows scraped directly from CR "
    "article prose and 'low' for the hardcoded fallback set."
)

# ---------------------------------------------------------------------------
# Contaminant name -> registry slug map (built from CONTAMINANTS aliases).
# normalize_contaminant() does not consult the registry's own alias lists,
# so we resolve scraped names here against the registry as the single
# source of truth.
# ---------------------------------------------------------------------------
_ALIAS_TO_SLUG: dict[str, str] = {}
for _slug, _cfg in CONTAMINANTS.items():
    _ALIAS_TO_SLUG[_slug] = _slug
    for _alias in _cfg.get("aliases", []):
        _ALIAS_TO_SLUG[_alias.lower()] = _slug
del _slug, _cfg

_UNIT_MAP = {
    "microgram": "µg/serving", "micrograms": "µg/serving",
    "milligram": "mg/serving", "milligrams": "mg/serving",
    "gram": "g/serving", "grams": "g/serving",
}

# Hardcoded fallback: verified product-level rows from a published CR
# investigation (used only if live scraping yields nothing). All values are
# taken verbatim from CR's article prose.
# (product_name, contaminant_slug, amount, unit_word, article_url, date, year)
_HARDCODED_ARTICLE_URL = (
    BASE_URL + "/health/food-additives/"
    "popular-snacks-contain-high-levels-of-additives-a6822743034/"
)
HARDCODED_PRODUCT_ROWS = [
    ("Little Debbie Oatmeal Creme Pies", "glycidyl_esters", 5.2, "micrograms"),
    ("Little Debbie Oatmeal Creme Pies", "titanium_dioxide", 0.03, "milligrams"),
    ("Jell-O Zero Instant Pudding", "red_40", 14.2, "milligrams"),
    ("Hostess Donettes", "titanium_dioxide", 261.0, "milligrams"),
]

# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------
# "serving of <product> <verb> <clause>" — clause runs to a sentence-ending
# period (period + whitespace / end), so decimal points like "0.03" do not
# terminate the clause prematurely.
_SERVING_RE = re.compile(
    r"(?:(?:one|a|each|a\s+single|one\s+single)\s+(?:[a-z]+\s+)?serving\s+of)\s+"
    r"(?P<product>[A-Z0-9][^.\n]{1,120}?)\s+"
    r"(?:contained|contains|had|showed|tested\s+at|registered|delivered|"
    r"packed|carried|revealed)\s+"
    r"(?P<clause>.{4,400}?)(?=[.](?:\s|$))",
    re.IGNORECASE | re.DOTALL,
)

# Within a clause: "<qty> <unit> of <contaminant>". Spelled-out units only,
# matching CR's prose style and avoiding methodology false positives.
_AMOUNT_RE = re.compile(
    r"(?P<qty>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>micrograms?|milligrams?|grams?)\s+of\s+"
    r"(?P<contaminant>[a-z0-9][a-z0-9 '\-]{1,45}?)"
    r"(?=,|\.|;|\sand\s|$)",
    re.IGNORECASE,
)

_META_URL_RE = re.compile(r"<!-- cr_url: (.+?) -->")
_META_TITLE_RE = re.compile(r"<!-- cr_title: (.+?) -->")
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r'(?:datetime="|\b)(20\d\d)-(\d{2})-(\d{2})')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_tags(html: str) -> str:
    """Strip scripts/styles/tags and collapse whitespace -> plain text."""
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = _TAG_RE.sub(" ", text)
    text = (text.replace("&nbsp;", " ")
                .replace("&amp;", "&")
                .replace("&#39;", "'")
                .replace("&rsquo;", "'")
                .replace("&ldquo;", '"').replace("&rdquo;", '"'))
    return re.sub(r"\s+", " ", text).strip()


def _read_meta(html: str) -> tuple[str, str]:
    """Read the cr_url / cr_title markers prepended to cached article files."""
    m_url = _META_URL_RE.search(html)
    m_title = _META_TITLE_RE.search(html)
    return (
        m_url.group(1) if m_url else BASE_URL,
        m_title.group(1) if m_title else "Consumer Reports",
    )


def _extract_date(html: str) -> tuple[str, int]:
    """Best-effort ISO date + year from the article; else the defaults."""
    m = _DATE_RE.search(html)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", int(m.group(1))
    return DEFAULT_PUBLISHED_DATE, DEFAULT_DATA_YEAR


def _resolve_contaminant(raw: str) -> str | None:
    """
    Resolve a scraped contaminant phrase to a registry slug.
    Tries the full phrase, then progressively shorter word-prefixes (drops
    trailing prose noise like 'a synthetic pigment').
    """
    raw = raw.strip().lower().strip(",.;:'")
    if not raw:
        return None
    if raw in _ALIAS_TO_SLUG:
        return _ALIAS_TO_SLUG[raw]
    words = raw.split()
    for n in range(len(words) - 1, 0, -1):
        candidate = " ".join(words[:n])
        if candidate in _ALIAS_TO_SLUG:
            return _ALIAS_TO_SLUG[candidate]
    return None


def _clean_product(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip(" ,;:'\"")


# Titles must mention at least one of these to be worth fetching — keeps
# discovery off product-review / lifestyle pages that share the article
# URL shape (e.g. "Best Curling Irons").
_RELEVANCE_KEYWORDS = (
    "food", "contaminant", "metal", "arsenic", "lead", "cadmium", "mercury",
    "pesticide", "glyphosate", "herbicide", "additive", "dye", "titanium",
    "nitrite", "sweetener", "aspartame", "sucralose", "plastic", "bpa",
    "pfos", "pfoa", "rice", "cereal", "oat", "formula", "protein powder",
    "water", "snack", "chip", "juice", "soda", "spice", "chocolate",
)


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _RELEVANCE_KEYWORDS)


def _discover_articles() -> list[dict]:
    """
    Query the CR search endpoint and return deduped article descriptors:
    [{"title", "url"}]. Only CR article paths with a numeric article id and a
    contaminant-relevant title are kept (filters out nav/ads/topic pages and
    off-topic product reviews).
    """
    found: dict[str, dict] = {}
    for query in SEARCH_QUERIES:
        url = SEARCH_URL.format(query=quote(query))
        try:
            html = fetch_page(url, timeout=25)
        except Exception as e:
            logger.warning("CR search fetch failed for %r: %s", query, e)
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if len(text) < 12:
                continue
            abs_url = urljoin(BASE_URL + "/", href)
            # Article path ends in an id like "...-a6822743034/".
            if not re.search(r"/(?:health|babies-kids|product-safety|"
                             r"water-quality|food-recalls|cro-news)/.+a\d{7,}",
                             abs_url):
                continue
            if not _is_relevant(text):
                continue
            found[abs_url] = {"title": text, "url": abs_url}
        if len(found) >= MAX_ARTICLES:
            break
    logger.info("Discovered %d Consumer Reports articles", len(found))
    return list(found.values())[:MAX_ARTICLES]


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class ConsumerReportsFetcher(BaseFetcher):
    """Fetch product-level contaminant measurements from Consumer Reports."""

    SOURCE_NAME = "ConsumerReports"
    # Multi-contaminant: each row sets its own `contaminant` (resolved to a
    # registry slug). BaseFetcher.run() does not inject a default.
    CONTAMINANT = None

    # ------------------------------------------------------------------
    # fetch
    # ------------------------------------------------------------------
    def fetch(self) -> list[Path]:
        """
        Discover and download CR investigation articles to the raw-data cache.
        Each cached file is prefixed with cr_url / cr_title markers so parse()
        can recover the source URL. Returns a sentinel if nothing was fetched.
        """
        paths: list[Path] = []
        articles = _discover_articles()

        for i, art in enumerate(articles):
            cache = RAW_DATA_DIR / f"consumerreports_article_{i}.html"
            if cache.exists():
                logger.info("Cache hit: %s", cache.name)
            else:
                try:
                    html = fetch_page(art["url"], timeout=25)
                except Exception as e:
                    logger.warning("Failed to fetch CR article %s: %s", art["url"], e)
                    continue
                cache.write_text(
                    f"<!-- cr_url: {art['url']} -->\n"
                    f"<!-- cr_title: {art['title']} -->\n{html}",
                    encoding="utf-8",
                )
                logger.info("Cached %s (%d bytes)", cache.name, len(html))
            paths.append(cache)

        if not paths:
            sentinel = RAW_DATA_DIR / "consumerreports_fallback.html"
            sentinel.write_text(
                "<!-- CR fallback: no articles discovered/fetched -->",
                encoding="utf-8",
            )
            paths.append(sentinel)

        return paths

    # ------------------------------------------------------------------
    # parse
    # ------------------------------------------------------------------
    def parse(self, files: list[Path]) -> list[dict]:
        """Parse cached articles into tier-1 product_tests rows; fall back
        to the hardcoded set if scraping yields nothing."""
        rows: list[dict] = []
        for path in files:
            try:
                html = path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("Could not read %s: %s", path, e)
                continue
            if "CR fallback" in html:
                continue
            url, _title = _read_meta(html)
            rows.extend(self._extract_from_article(html, url, path))

        if rows:
            logger.info("%s: %d rows scraped from articles",
                        self.SOURCE_NAME, len(rows))
            return rows

        fallback = self._build_hardcoded_rows()
        logger.info("%s: %d rows from hardcoded fallback",
                    self.SOURCE_NAME, len(fallback))
        return fallback

    # ------------------------------------------------------------------
    # article extraction
    # ------------------------------------------------------------------
    def _extract_from_article(self, html: str, url: str,
                              path: Path) -> list[dict]:
        text = _strip_tags(html)
        published, year = _extract_date(html)
        rows: list[dict] = []
        seen: set[str] = set()

        for m in _SERVING_RE.finditer(text):
            product = _clean_product(m.group("product"))
            if len(product) < 3:
                continue
            clause = m.group("clause")
            for amt in _AMOUNT_RE.finditer(clause):
                slug = _resolve_contaminant(amt.group("contaminant"))
                if not slug:
                    continue
                unit = _UNIT_MAP.get(amt.group("unit").lower())
                if not unit:
                    continue
                key = (product, slug)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(self._make_row(
                    product=product,
                    slug=slug,
                    qty=float(amt.group("qty")),
                    unit=unit,
                    url=url,
                    published=published,
                    year=year,
                    path=path,
                    scraped=True,
                ))
        return rows

    # ------------------------------------------------------------------
    # row builder
    # ------------------------------------------------------------------
    def _make_row(self, *, product: str, slug: str, qty: float, unit: str,
                  url: str, published: str, year: int, path: Path,
                  scraped: bool) -> dict:
        food_category = normalize_category(product) or "consumer_reports_product"
        return {
            "tier": 1,
            "source_name": self.SOURCE_NAME,
            "source_url": url,
            "report_label": "Consumer Reports product testing",
            "published_date": published,
            "data_year": year,
            "food_category": food_category,
            "raw_category": product,
            "contaminant": slug,
            "product_name": product,
            "measured_ppb": None,          # per-serving mass -> no concentration
            "below_detection": 0,
            "original_unit": unit,
            "unit_conversion": 1.0,
            "methodology_note": f"{METHODOLOGY_NOTE} Reported: {qty} {unit}.",
            "confidence": "high" if scraped else "low",
            "raw_file_path": str(path),
            "dedup_key": build_dedup_key(self.SOURCE_NAME, product, slug, year),
        }

    # ------------------------------------------------------------------
    # hardcoded fallback
    # ------------------------------------------------------------------
    def _build_hardcoded_rows(self) -> list[dict]:
        rows: list[dict] = []
        path = RAW_DATA_DIR / "consumerreports_fallback.html"
        for product, slug, qty, unit_word in HARDCODED_PRODUCT_ROWS:
            unit = _UNIT_MAP[unit_word]
            rows.append(self._make_row(
                product=product,
                slug=slug,
                qty=qty,
                unit=unit,
                url=_HARDCODED_ARTICLE_URL,
                published="2025-06-01",
                year=2025,
                path=path,
                scraped=False,
            ))
        return rows
