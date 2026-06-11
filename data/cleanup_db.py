"""
cleanup_db.py
One-time database cleanup: removes invalid contaminant values,
anomalous water year data, and normalizes German contaminant names.

Run once before the next pipeline re-run:
    python data/cleanup_db.py
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path so we can import database module
sys.path.insert(0, str(Path(__file__).parent))
from db.database import DB_PATH, normalize_contaminant, log_data_version

STATUS_KEYWORDS = {"no residue found", "residue detected", "none found", "pesticide screen"}


def main():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print("=" * 60)
    print("Database Cleanup Script")
    print("=" * 60)

    # --- 1. Remove anomalous water year data ---
    current_year = datetime.now().year
    print(f"\n[1] Removing water_tests rows with data_year > {current_year}...")
    cur.execute("SELECT COUNT(*) FROM water_tests WHERE data_year > ?", (current_year,))
    bad_water = cur.fetchone()[0]
    if bad_water > 0:
        cur.execute("DELETE FROM water_tests WHERE data_year > ?", (current_year,))
        print(f"    Deleted {bad_water} rows with future years")
    else:
        print("    No anomalous year rows found")

    # --- 2. Remove status-string contaminants from product_tests ---
    print("\n[2] Removing status-string contaminants from product_tests...")
    placeholders = ",".join("?" for _ in STATUS_KEYWORDS)
    cur.execute(
        f"SELECT COUNT(*) FROM product_tests WHERE LOWER(contaminant) IN ({placeholders})",
        list(STATUS_KEYWORDS),
    )
    bad_pt = cur.fetchone()[0]
    if bad_pt > 0:
        cur.execute(
            f"DELETE FROM product_tests WHERE LOWER(contaminant) IN ({placeholders})",
            list(STATUS_KEYWORDS),
        )
        print(f"    Deleted {bad_pt} rows (status strings as contaminant)")
    else:
        print("    No status-string contaminant rows found")

    # --- 3. Remove status-string contaminants from category_summaries ---
    print("\n[3] Removing status-string contaminants from category_summaries...")
    cur.execute(
        f"SELECT COUNT(*) FROM category_summaries WHERE LOWER(contaminant) IN ({placeholders})",
        list(STATUS_KEYWORDS),
    )
    bad_cs = cur.fetchone()[0]
    if bad_cs > 0:
        cur.execute(
            f"DELETE FROM category_summaries WHERE LOWER(contaminant) IN ({placeholders})",
            list(STATUS_KEYWORDS),
        )
        print(f"    Deleted {bad_cs} rows (status strings as contaminant)")
    else:
        print("    No status-string contaminant rows found")

    # --- 4. Normalize German contaminant names in category_summaries ---
    print("\n[4] Normalizing German contaminant names in category_summaries...")
    # First pass: force-lowercase all contaminant values
    cur.execute("SELECT COUNT(*) FROM category_summaries WHERE contaminant != LOWER(contaminant)")
    mixed_case = cur.fetchone()[0]
    if mixed_case > 0:
        cur.execute("UPDATE category_summaries SET contaminant = LOWER(contaminant)")
        print(f"    Lowercased {cur.rowcount} rows")

    # Second pass: apply normalize_contaminant for alias/descriptive resolution
    cur.execute("SELECT DISTINCT contaminant FROM category_summaries")
    all_contaminants = [r[0] for r in cur.fetchall()]

    renames = {}  # old_name -> new_name
    for name in all_contaminants:
        normalized = normalize_contaminant(name)
        if normalized and normalized != name:
            renames[name] = normalized

    renamed_count = 0
    for old_name, new_name in renames.items():
        cur.execute(
            "UPDATE category_summaries SET contaminant = ? WHERE contaminant = ?",
            (new_name, old_name),
        )
        renamed_count += cur.rowcount

    # Log summary to data_versions (one entry per cleanup run)
    if renamed_count > 0:
        log_data_version("category_summaries", 0, "contaminant_batch",
                         f"{len(renames)} names normalized", f"{renamed_count} rows updated",
                         changed_by="cleanup_db")

    if renames:
        print(f"    Normalized {len(renames)} contaminant names ({renamed_count} rows updated)")
        print("    Key renames:")
        for old, new in sorted(renames.items())[:15]:
            print(f"      '{old}' -> '{new}'")
        if len(renames) > 15:
            print(f"      ... ({len(renames) - 15} more)")
    else:
        print("    No names needed normalization")

    # --- 5. Also normalize in product_tests and water_tests ---
    for table in ["product_tests", "water_tests"]:
        print(f"\n[5] Normalizing contaminant names in {table}...")
        # Force-lowercase first
        cur.execute(f"UPDATE {table} SET contaminant = LOWER(contaminant) WHERE contaminant != LOWER(contaminant)")
        lowercased = cur.rowcount
        # Then apply normalize_contaminant
        cur.execute(f"SELECT DISTINCT contaminant FROM {table}")
        all_cont = [r[0] for r in cur.fetchall()]
        renames_t = {}
        for name in all_cont:
            normalized = normalize_contaminant(name)
            if normalized and normalized != name:
                renames_t[name] = normalized
        cnt = 0
        for old_name, new_name in renames_t.items():
            cur.execute(f"UPDATE {table} SET contaminant = ? WHERE contaminant = ?", (new_name, old_name))
            cnt += cur.rowcount
        if renames_t:
            print(f"    Lowercased {lowercased} rows, normalized {len(renames_t)} names ({cnt} rows updated)")
        else:
            print(f"    Lowercased {lowercased} rows, no further normalization needed")

    conn.commit()

    # --- 6. Summary ---
    print("\n" + "=" * 60)
    print("Post-Cleanup Summary")
    print("=" * 60)
    for table in ["product_tests", "category_summaries", "water_tests"]:
        cur.execute(f"SELECT COUNT(*) FROM [{table}]")
        total = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(DISTINCT contaminant) FROM [{table}]")
        unique = cur.fetchone()[0]
        print(f"  {table:30s} {total:>8,} rows  {unique:>4} unique contaminants")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
