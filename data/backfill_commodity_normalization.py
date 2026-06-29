"""Re-derive ``food_category`` from ``raw_category`` using the shared resolver.

One-shot, idempotent. ``raw_category`` is the immutable source of truth;
``food_category`` is the re-derivable resolved value. This fixes the legacy
mis-normalizations — the ~4.4k false-positive ``dairy`` rows from the old
longest-substring matcher, plus any other substring mis-fires — by routing
every raw through ``resolve_commodity``.

Behavior:
  * resolvable raw  -> canonical key (e.g. "APPLE, JAM, ..., BUTTER" -> apple)
  * unresolved raw  -> ``"unknown"`` + a row in ``unresolved_commodities``
    (the precision-first triage path; nothing is silently left as the raw).

Efficiency: there are only ~2.8k distinct raw_category strings vs ~736k rows,
so we resolve once per distinct raw and issue one bulk UPDATE per (raw -> new)
mapping instead of one UPDATE per row.

Usage (from the data/ directory, like seed_ingredients.py):
    python backfill_commodity_normalization.py
"""

from __future__ import annotations

import logging

# Dual import root: run from data/ (runtime) or project root (tests).
try:
    from db.database import get_connection
    from commodity_resolver import resolve_commodity, load_index, invalidate_index, upsert_unresolved
except ImportError:  # project-root / test context
    from data.db.database import get_connection
    from data.commodity_resolver import (
        resolve_commodity, load_index, invalidate_index, upsert_unresolved,
    )

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill")

TABLES = ("category_summaries", "product_tests")

# Non-NULL sentinel so the (raw_category, source) PK dedupes across the two
# tables. SQLite treats NULL as distinct in conflict detection, so a NULL
# source would create duplicate rows for any raw present in both tables. A
# raw in both tables accumulates both counts into one weighted row.
BACKFILL_SOURCE = "backfill"


def backfill(conn=None) -> dict:
    """Re-normalize food_category in every row of TABLES. Returns counts."""
    own = conn is None
    if conn is None:
        # get_connection is a context manager — open it here and recurse so the
        # caller's signature stays simple.
        with get_connection() as c:
            return backfill(c)

    load_index(conn)
    stats = {"examined": 0, "resolved": 0, "to_unknown": 0,
             "rows_changed": 0, "unresolved_logged": 0}

    # The backfill is the authoritative triage source for legacy data: clear
    # its own (BACKFILL_SOURCE) entries so re-runs don't accumulate counts.
    # Fetcher-sourced rows (other source values) are preserved.
    conn.execute(
        "DELETE FROM unresolved_commodities WHERE source = ?", (BACKFILL_SOURCE,)
    )

    for table in TABLES:
        # distinct raw_category -> row count, so the triage log can be weighted
        # by real frequency rather than one hit per distinct raw.
        rows = conn.execute(
            f"SELECT raw_category, COUNT(*) AS n FROM {table} "
            f"WHERE raw_category IS NOT NULL GROUP BY raw_category"
        ).fetchall()
        stats["examined"] += len(rows)
        logger.info("%s: %d distinct raw_category values", table, len(rows))

        for raw, n in rows:
            new = resolve_commodity(raw, conn)
            if new:
                stats["resolved"] += 1
            else:
                new = "unknown"
                stats["to_unknown"] += 1
                # weight triage by affected row count; BACKFILL_SOURCE lets the
                # PK dedupe a raw that appears in both tables (counts add up).
                upsert_unresolved(raw, BACKFILL_SOURCE, conn, count=n)
                stats["unresolved_logged"] += 1
            # Bulk-update only rows whose value actually changes (incl. NULL).
            cur = conn.execute(
                f"UPDATE {table} SET food_category = ? "
                f"WHERE raw_category = ? "
                f"AND (food_category IS NOT ? OR food_category IS NULL)",
                (new, raw, new),
            )
            stats["rows_changed"] += cur.rowcount

    if own:
        conn.commit()
    invalidate_index()
    return stats


def main():
    stats = backfill()
    logger.info(
        "backfill complete: examined=%(examined)d distinct raws "
        "(resolved=%(resolved)d, to_unknown=%(to_unknown)d, "
        "unresolved_logged=%(unresolved_logged)d); rows_changed=%(rows_changed)d",
        stats,
    )
    return stats


if __name__ == "__main__":
    main()
