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
    "load_index",
    "invalidate_index",
    "upsert_unresolved",
]

_PUNCT_RE = re.compile(r"[,;/\t]+")
_WS_RE = re.compile(r"\s+")

# Module-level unified alias index (alias -> canonical_key) + overrides.
# Mirrors the proven cache pattern in database.normalize_category: loaded once,
# reused; tests invalidate + reload per DB. See resolve_commodity() for the
# reload decision.
_index: dict[str, str] = {}
_group_map: dict[str, str] = {}
_loaded_from: object | None = None  # id() of the conn the cache was built from


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


def _build_index(conn) -> tuple[dict[str, str], dict[str, str]]:
    """Read both alias tables from ``conn`` into a unified index.

    Returns (index, group_map). group_map is seeded empty — the first-segment
    rule handles every known case; it is the extension point for triage.
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

    return index, {}


def load_index(conn=None) -> None:
    """Build the unified alias index from BOTH alias tables.

    Idempotent. When ``conn`` is None the dev DB connection is used (via the
    ``get_connection`` context manager). Caches the result module-level; tests
    call :func:`invalidate_index` between DBs.
    """
    global _index, _group_map, _loaded_from
    if conn is None:
        gc = _get_get_connection()
        with gc() as c:
            index, group_map = _build_index(c)
        _loaded_from = None
    else:
        index, group_map = _build_index(conn)
        _loaded_from = id(conn)
    _index = index
    _group_map = group_map


def invalidate_index() -> None:
    """Clear the cached alias index. Call after modifying alias tables."""
    global _index, _group_map, _loaded_from
    _index, _group_map, _loaded_from = {}, {}, None


def _parts(raw: str) -> tuple[str, str]:
    cleaned = (raw or "").lower().strip()
    norm = _WS_RE.sub(" ", _PUNCT_RE.sub(" ", cleaned)).strip()
    return cleaned, norm


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
    #    Variants (singular/plural) of the leading candidate are also tried, so
    #    "ackees, ..." still resolves via singular "ackee". Only the FIRST
    #    segment is consulted, so buried tokens (e.g. "milk" in segment 3) are
    #    never reached.
    first = norm.split(",", 1)[0].strip()
    tokens = first.split()
    for i in range(len(tokens), 0, -1):
        cand = " ".join(tokens[:i])
        for form in (cand, *_variants(cand)):
            if len(form) >= 3 and form in _index:
                return _index[form]

    # 5. miss
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


def resolve_benchmark(canonical_key: Optional[str], conn=None) -> list[str]:
    """Canonical key -> matching benchmark-table keys (``tolerance_limits`` /
    ``international_mrls`` ``food_category`` values). Returns ``[]`` when none
    match — the caller surfaces 'no benchmark' honestly rather than guessing.
    """
    if not canonical_key:
        return []
    if (not _index) or (conn is not None and _loaded_from != id(conn)):
        load_index(conn)

    candidates = {canonical_key.lower()}
    for v in _variants(canonical_key.lower()):
        candidates.add(v)

    bench: set[str] = set()
    for table in ("tolerance_limits", "international_mrls"):
        for (fc,) in conn.execute(
            f"SELECT DISTINCT food_category FROM {table} "
            "WHERE food_category IS NOT NULL"
        ).fetchall():
            if fc and fc.lower() in candidates:
                bench.add(fc)
    return sorted(bench)
