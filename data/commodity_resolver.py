"""Single shared commodity resolver.

Maps any raw commodity string to a ``canonical_key`` (the ``food_category``
namespace shared by ``category_summaries``, ``product_tests``, the views,
``tolerance_limits`` and ``international_mrls``) using ONE unified alias
vocabulary and a prefix-based first-segment rule.

Why this exists
---------------
The pipeline previously had five resolver implementations with two different
algorithms (exact-only in the query layer; longest-substring at ingest). The
substring matcher produced false-positives: a buried token such as ``butter``
or ``milk`` inside a long fruit/jam group string (e.g.
``APPLE, JAM, JELLY, PRESERVES, MARMALADE, BUTTER AND CANDIED``) matched the
dairy alias and the row was mis-classified as ``dairy`` (~4,425 rows).

The fix is the **first-segment prefix rule**: the alias must equal the LEADING
token(s) of the first comma-segment. Group strings lead with their primary
commodity, so ``APPLE, JAM, ..., BUTTER -> apple`` while the buried ``butter``
is never considered. In every sized false-positive the danger token was *not*
the first token, so prefix position alone fixes them.

Unresolved raws return ``None``; callers write ``"unknown"`` and log the miss
via :func:`upsert_unresolved` so taxonomy gaps stay visible and shrinkable
instead of silently leaking the raw string into the database.
"""

from __future__ import annotations

import json
import re
from typing import Optional

__all__ = [
    "resolve_commodity",
    "resolve_benchmark",
    "extract_forms",
    "load_index",
    "invalidate_index",
    "upsert_unresolved",
]

_PUNCT_RE = re.compile(r"[,;/\t]+")
_WS_RE = re.compile(r"\s+")

# Commodity *forms* that the benchmark tables (tolerance_limits, international_mrls)
# distinguish with a comma-suffix — e.g. EPA sets a different glyphosate-class
# tolerance for ``basil, dried leaves`` (200,000 ppb) than ``basil, fresh leaves``
# (30,000 ppb), a 6.7x divergence. Recognising these is what lets the form-aware
# benchmark lookup (resolve_benchmark) pick the correct tolerance for a specific
# raw instead of the generic one — collapsing to the canonical key for grouping
# does NOT lose accuracy because the form is re-introduced here, at lookup time.
_FORM_TOKENS = ("dried", "fresh", "juice")
_WORD_RE = re.compile(r"[a-z]+")


def extract_forms(raw: Optional[str]) -> set[str]:
    """Whole-word form tokens (subset of _FORM_TOKENS) present in ``raw``.

    Whole-word on purpose: ``refreshing`` must not yield ``fresh``.
    """
    if not raw:
        return set()
    return set(_WORD_RE.findall(raw.lower())) & set(_FORM_TOKENS)

# Module-level unified alias index (alias -> canonical_key) + overrides.
# Mirrors the proven cache pattern in database.normalize_category: loaded once,
# reused; tests invalidate + reload per DB. See resolve_commodity() for the
# reload decision.
_index: dict[str, str] = {}
_group_map: dict[str, str] = {}
# canonical_key (lower) -> [alias (lower), ...]. Lets resolve_benchmark match a
# benchmark key filed under an ALIAS of the canonical (e.g. 'sweet basil' for
# 'basil'), so it is a strict superset of the per-table resolvers.
_reverse_aliases: dict[str, list[str]] = {}
_loaded_from: object | None = None  # id() of the conn the cache was built from
_ALLOWED_BENCHMARK_TABLES = ("tolerance_limits", "international_mrls")


def _bridge_slug_to_canonical(conn) -> dict[str, str]:
    """commodity_slug -> canonical_key. For the large majority of commodities
    the slug string is itself a canonical_key, so this is identity; the hook
    exists so future non-identity pairs can be reconciled without touching
    callers."""
    canon = {row[0] for row in conn.execute(
        "SELECT DISTINCT canonical_key FROM category_aliases").fetchall()}
    bridge: dict[str, str] = {}
    for (slug,) in conn.execute(
        "SELECT commodity_slug FROM commodities").fetchall():
        bridge[slug] = slug if slug in canon else slug
    return bridge


def _get_get_connection():
    """Return database.get_connection, working under both import roots
    (project-root ``data.db.database`` and runtime ``db.database``)."""
    try:
        from data.db.database import get_connection
    except ImportError:  # runtime context: data/ is the path root
        from db.database import get_connection
    return get_connection


def _build_index(conn) -> tuple[dict[str, str], dict[str, str], dict[str, list[str]]]:
    """Read both alias tables from ``conn`` into a unified index.

    Returns ``(index, group_map, reverse_aliases)``. ``group_map`` is seeded
    empty — the first-segment rule handles every known case; it is the extension
    point for triage. ``reverse_aliases`` (canonical_key -> [alias]) lets
    :func:`resolve_benchmark` match a benchmark key filed under an alias of the
    canonical, making it a strict superset of the per-table resolvers.
    """
    index: dict[str, str] = {}

    # 1) category_aliases  ->  alias : canonical_key
    for alias, key in conn.execute(
        "SELECT alias, canonical_key FROM category_aliases"
    ).fetchall():
        index[alias] = key

    # 2) commodities.ingredient_aliases  ->  token : bridged canonical_key
    bridge = _bridge_slug_to_canonical(conn)
    for slug, blob in conn.execute(
        "SELECT commodity_slug, ingredient_aliases FROM commodities "
        "WHERE ingredient_aliases IS NOT NULL"
    ).fetchall():
        try:
            tokens = json.loads(blob) if blob else []
        except (ValueError, TypeError):
            tokens = []
        canon = bridge.get(slug, slug)
        for tok in tokens:
            tok = (tok or "").lower().strip()
            if tok:
                index.setdefault(tok, canon)

    # 3) reverse: canonical_key (lower) -> [alias (lower), ...]. Derived from
    #    the unified index so it covers both alias tables in one place.
    reverse: dict[str, list[str]] = {}
    for alias, canon in index.items():
        reverse.setdefault(canon, []).append(alias)

    return index, {}, reverse


def load_index(conn=None) -> None:
    """Build the unified alias index from BOTH alias tables.

    Idempotent. When ``conn`` is None the dev DB connection is used (via the
    ``get_connection`` context manager). Caches the result module-level; tests
    call :func:`invalidate_index` between DBs.
    """
    global _index, _group_map, _reverse_aliases, _loaded_from
    if conn is None:
        gc = _get_get_connection()
        with gc() as c:
            index, group_map, reverse = _build_index(c)
        _loaded_from = None
    else:
        index, group_map, reverse = _build_index(conn)
        _loaded_from = id(conn)
    _index = index
    _group_map = group_map
    _reverse_aliases = reverse


def invalidate_index() -> None:
    """Clear the cached alias index. Call after modifying alias tables."""
    global _index, _group_map, _reverse_aliases, _loaded_from
    _index, _group_map, _reverse_aliases, _loaded_from = {}, {}, {}, None


def _parts(raw: str) -> tuple[str, str]:
    cleaned = (raw or "").lower().strip()
    norm = _WS_RE.sub(" ", _PUNCT_RE.sub(" ", cleaned)).strip()
    return cleaned, norm


def _strip_leading_form_token(segment: str) -> str:
    """Drop a leading dried/fresh/juice qualifier from ``segment`` so the base
    commodity resolves (``dried basil`` -> ``basil``, ``Juice - Apple`` ->
    ``apple``). Returns '' when the first token isn't a form qualifier.

    Only the FIRST token is considered, so a buried form word is never stripped
    (mirrors the first-segment prefix rule's precision guarantee). The remainder
    must still resolve on its own — this never guesses a commodity.
    """
    toks = segment.split()
    if not toks:
        return ""
    if toks[0].lower().strip(",-/:;") not in _FORM_TOKENS:
        return ""
    rest = toks[1:]
    while rest and rest[0].strip(",-/:;") == "":  # drop a lone separator
        rest = rest[1:]
    return " ".join(rest)


def _variants(s: str) -> list[str]:
    out = [s, s.replace(" ", "_"), s.replace("_", " ")]
    if s.endswith("s") and not s.endswith("ss"):
        out.append(s[:-1])          # plural -> singular
    else:
        out.append(s + "s")         # singular -> plural
    seen, res = set(), []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            res.append(v)
    return res


def _prefix_match(segment: str) -> Optional[str]:
    """Longest-leading-token alias match within a single comma-segment.

    Tries the full segment first, then progressively shorter leading prefixes
    (with singular/plural variants), so ``ackees, ...`` resolves via ``ackee``.
    Only tokens of length >= 3 match, suppressing noise like ``or``/``and``.
    """
    tokens = segment.split()
    for i in range(len(tokens), 0, -1):
        cand = " ".join(tokens[:i])
        for form in (cand, *_variants(cand)):
            if len(form) >= 3 and form in _index:
                return _index[form]
    return None


def resolve_commodity(raw: Optional[str], conn=None) -> Optional[str]:
    """Raw commodity string -> canonical_key, or ``None`` if unresolved.

    Algorithm: exact (cleaned / punctuation-normalized) -> singular/plural and
    underscore<->space variants -> curated group overrides -> first-segment
    prefix match -> miss (``None``).
    """
    if not raw:
        return None

    # Reload when empty, or when the caller passes a different connection than
    # the one the cache was built from (e.g. an in-memory test DB).
    if (not _index) or (conn is not None and _loaded_from != id(conn)):
        load_index(conn)

    cleaned, norm = _parts(raw)

    # 1. exact
    if cleaned in _index:
        return _index[cleaned]
    if norm in _index:
        return _index[norm]

    # 2. variants (plural/singular, underscore<->space)
    for v in _variants(cleaned):
        if v in _index:
            return _index[v]
    if norm != cleaned:
        for v in _variants(norm):
            if v in _index:
                return _index[v]

    # 3. curated full-string overrides
    if norm in _group_map:
        return _group_map[norm]

    # 4. first-segment prefix match (longest leading-token alias wins).
    #    Only the FIRST comma-segment is consulted, so buried tokens (e.g.
    #    "milk" in segment 3) are never reached.
    first = norm.split(",", 1)[0].strip()
    hit = _prefix_match(first)
    if hit:
        return hit

    # 5. leading form-qualifier fallback: strip a leading dried/fresh/juice
    #    qualifier so the base commodity resolves ("dried basil" -> "basil").
    #    The form stays in the raw for form-aware tolerance lookup. The WHOLE
    #    remainder must be a known commodity (exact/variant), not just a leading
    #    prefix — otherwise "fresh water bass" would wrongly match "water".
    stripped = _strip_leading_form_token(first)
    if stripped:
        for v in (stripped, *_variants(stripped)):
            if len(v) >= 3 and v in _index:
                return _index[v]

    # 6. miss
    return None


def upsert_unresolved(raw: str, source: Optional[str], conn=None, count: int = 1) -> None:
    """Record a resolver miss in ``unresolved_commodities`` (insert-or-increment).

    Opens a short-lived connection (via ``get_connection``) when ``conn`` is
    None so callers without a live connection (e.g. fetcher ``parse()``) can
    still triage. ``count`` is the weight added to ``hit_count`` (default 1,
    one occurrence; the backfill passes the affected row count so the triage
    log is prioritized by real frequency).
    """
    if not raw:
        return
    count = max(1, int(count))
    sql = (
        "INSERT INTO unresolved_commodities (raw_category, source, hit_count) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(raw_category, source) DO UPDATE SET "
        "  hit_count = hit_count + ?"
    )
    params = (raw, source, count, count)
    if conn is None:
        gc = _get_get_connection()
        with gc() as c:
            c.execute(sql, params)
    else:
        conn.execute(sql, params)


def resolve_benchmark(
    canonical_key: Optional[str], conn=None, raw: Optional[str] = None,
    table: Optional[str] = None,
) -> list[str]:
    """Canonical key -> ranked matching benchmark-table keys
    (``tolerance_limits`` / ``international_mrls`` ``food_category`` values),
    form-aware when ``raw`` is supplied.

    A benchmark row matches when its leading comma-segment equals the canonical
    key OR one of its aliases (so ``basil`` pulls in ``basil``,
    ``basil, dried leaves`` and an alias-keyed ``sweet basil``). When ``raw``
    carries a form token (dried/fresh/juice) the form-specific key whose suffix
    shares that form ranks FIRST, so the caller applies the correct tolerance
    for that form rather than the generic one. With no ``raw`` (or no form
    token) the generic key ranks first — identical to the historical behavior.

    ``table`` restricts the query to a single benchmark table
    (``"tolerance_limits"`` or ``"international_mrls"``) instead of both —
    needed by per-table callers (e.g. ``IngredientRiskQuery``) that then look
    the resolved key up in one specific table.

    Returns ``[]`` when nothing matches — the caller surfaces 'no benchmark'
    honestly rather than guessing.
    """
    if not canonical_key:
        return []
    if (not _index) or (conn is not None and _loaded_from != id(conn)):
        load_index(conn)

    if table is not None and table not in _ALLOWED_BENCHMARK_TABLES:
        raise ValueError(f"unknown benchmark table: {table!r}")

    key_low = canonical_key.lower()
    base_keys = {key_low}
    for v in _variants(key_low):
        base_keys.add(v)
    # Reverse-alias expansion: a benchmark key filed under an ALIAS of the
    # canonical (e.g. 'sweet basil' for 'basil') must also match. Monotonic —
    # only adds candidates, so no existing match is lost.
    for alias in _reverse_aliases.get(key_low, []):
        base_keys.add(alias)
        for v in _variants(alias):
            base_keys.add(v)

    tables = (table,) if table else _ALLOWED_BENCHMARK_TABLES
    ordered: list[str] = []
    seen: set[str] = set()
    for tbl in tables:
        for (fc,) in conn.execute(
            f"SELECT DISTINCT food_category FROM {tbl} "
            "WHERE food_category IS NOT NULL"
        ).fetchall():
            if not fc:
                continue
            head = fc.split(",", 1)[0].strip().lower()
            if head in base_keys and fc not in seen:
                seen.add(fc)
                ordered.append(fc)

    raw_forms = extract_forms(raw)
    if not raw_forms or len(ordered) <= 1:
        # No form signal, or nothing to choose between: generic (shortest) first.
        ordered.sort(key=lambda fc: (fc.count(","), len(fc)))
        return ordered

    def _score(fc: str) -> tuple[int, int]:
        suffix = fc.split(",", 1)[1].lower() if "," in fc else ""
        cand_forms = extract_forms(suffix)
        # +1: this benchmark form matches the raw's form (prefer).
        #  0: generic, no form suffix (neutral fallback).
        # -1: a DIFFERENT form (e.g. fresh when raw says dried) — rank last.
        primary = 1 if (cand_forms & raw_forms) else (-1 if cand_forms else 0)
        # Tie-break toward the MORE specific form (longer suffix), so
        # 'basil, dried leaves' outranks 'basil, dried' for raw 'Dried Basil'.
        return (primary, len(fc))

    ordered.sort(key=_score, reverse=True)
    return ordered
