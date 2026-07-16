"""
cleanup_water_states.py
One-time repair of water_tests.state values polluted by the USGS_WQP fetcher.

Background: data/fetchers/water_quality.py derived `state` from the raw filename
by stripping a fixed number of underscore tokens. The contaminant slug
``inorganic_arsenic`` itself contains an underscore, so files named
``wqp_inorganic_arsenic_california.csv`` were parsed as state ``Arsenic
California`` (and date-range files as ``Arsenic 01-01-2012 12-31-2017``). The
fetcher is fixed; this script repairs the rows already in the DB.

Two repairs:
  * ``Arsenic <StateName>``  -> ``<StateName>``   (real per-state arsenic rows)
  * ``Arsenic <date-range>`` -> ``National``      (date-range fallback files)

Idempotent: the WHERE clauses match nothing once the data is clean, so this is
safe to re-run. Run once:
    python data/cleanup_water_states.py
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db.database import DB_PATH  # noqa: E402


def main() -> None:
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("=" * 60)
    print("Water state cleanup (USGS_WQP arsenic pollution)")
    print("=" * 60)

    # --- 1. 'Arsenic <StateName>' -> '<StateName>' (strip the 8-char prefix) ---
    cur.execute("SELECT COUNT(*) FROM water_tests WHERE state GLOB 'Arsenic [A-Za-z]*'")
    prefixed = cur.fetchone()[0]
    print(f"\n[1] 'Arsenic <State>' rows: {prefixed}")
    if prefixed:
        cur.execute(
            "UPDATE water_tests SET state = substr(state, 9) "
            "WHERE state GLOB 'Arsenic [A-Za-z]*'"
        )
        print(f"    Repaired {cur.rowcount} rows (stripped 'Arsenic ' prefix)")

    # --- 2. 'Arsenic <date-range>' -> 'National' (date-range fallback files) ---
    cur.execute("SELECT COUNT(*) FROM water_tests WHERE state GLOB 'Arsenic [0-9]*'")
    daterange = cur.fetchone()[0]
    print(f"\n[2] 'Arsenic <date-range>' rows: {daterange}")
    if daterange:
        cur.execute(
            "UPDATE water_tests SET state = 'National' "
            "WHERE state GLOB 'Arsenic [0-9]*'"
        )
        print(f"    Repaired {cur.rowcount} rows (-> 'National', matching the "
              "corrected fetcher)")

    conn.commit()

    # --- 3. Verify nothing 'Arsenic %' remains ---
    cur.execute("SELECT COUNT(*) FROM water_tests WHERE state LIKE 'Arsenic %'")
    leftover = cur.fetchone()[0]
    print(f"\n[verify] remaining 'Arsenic %' rows: {leftover}")
    if leftover:
        print("  WARNING: unexpected leftover values:")
        for state, n in cur.execute(
            "SELECT state, COUNT(*) FROM water_tests "
            "WHERE state LIKE 'Arsenic %' GROUP BY state LIMIT 20"
        ):
            print(f"    {n:>5}  {state!r}")

    # --- 4. Summary ---
    print("\n" + "=" * 60)
    print("Post-cleanup water_tests by state (top 10 + arsenic check)")
    print("=" * 60)
    for state, n in cur.execute(
        "SELECT state, COUNT(*) FROM water_tests GROUP BY state "
        "ORDER BY COUNT(*) DESC LIMIT 10"
    ):
        print(f"  {n:>6}  {state}")
    ca_total = cur.execute(
        "SELECT COUNT(*) FROM water_tests WHERE state = 'California'"
    ).fetchone()[0]
    ca_arsenic = cur.execute(
        "SELECT COUNT(*) FROM water_tests WHERE state = 'California' "
        "AND contaminant = 'inorganic_arsenic'"
    ).fetchone()[0]
    print(f"\n  California total: {ca_total}  (inorganic_arsenic: {ca_arsenic})")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
