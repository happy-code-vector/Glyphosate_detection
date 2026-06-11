"""
audit_category_aliases.py

Audit script to find food categories with measurement data but no
regulatory benchmark (MRL or tolerance). Output is sorted by row count
so you can fix high-volume categories first.

Run:
    python data/audit_category_aliases.py

Output:
    A report showing which categories have data but no benchmark,
    how many rows are affected, and what regulatory data exists.
"""

import sqlite3
from pathlib import Path
from collections import defaultdict

DB_PATH = Path(__file__).parent / "residueiq.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print("=" * 80)
    print("CATEGORY ALIAS AUDIT REPORT")
    print("=" * 80)

    # 1. Categories with measurement data (category_summaries)
    cur.execute("""
        SELECT food_category, COUNT(*) as row_count,
               COUNT(DISTINCT contaminant) as contaminant_count,
               SUM(samples_total) as total_samples
        FROM category_summaries
        WHERE detection_rate > 0
        GROUP BY food_category
        ORDER BY row_count DESC
    """)
    data_categories = {}
    for r in cur.fetchall():
        data_categories[r["food_category"]] = {
            "rows": r["row_count"],
            "contaminants": r["contaminant_count"],
            "samples": r["total_samples"],
        }

    # 2. Categories with MRL data (international_mrls)
    cur.execute("SELECT DISTINCT food_category FROM international_mrls")
    mrl_categories = set(r[0] for r in cur.fetchall())

    # 3. Categories with tolerance data (tolerance_limits)
    cur.execute("SELECT DISTINCT food_category FROM tolerance_limits")
    tolerance_categories = set(r[0] for r in cur.fetchall())

    # 4. Categories with product_tests data
    cur.execute("""
        SELECT food_category, COUNT(*) as row_count
        FROM product_tests
        GROUP BY food_category
        ORDER BY row_count DESC
    """)
    product_categories = {}
    for r in cur.fetchall():
        product_categories[r["food_category"]] = r["row_count"]

    # 5. Find unmatched categories
    benchmark_categories = mrl_categories | tolerance_categories
    unmatched = {}
    for cat, stats in data_categories.items():
        if cat not in benchmark_categories:
            unmatched[cat] = stats

    # Print report
    print(f"\nTotal categories with measurement data: {len(data_categories)}")
    print(f"Categories with MRL data: {len(mrl_categories)}")
    print(f"Categories with tolerance data: {len(tolerance_categories)}")
    print(f"Categories with ANY benchmark: {len(benchmark_categories)}")
    print(f"Categories with NO benchmark: {len(unmatched)}")

    total_unmatched_rows = sum(s["rows"] for s in unmatched.values())
    total_rows = sum(s["rows"] for s in data_categories.values())
    print(f"\nUnmatched rows: {total_unmatched_rows:,} of {total_rows:,} ({total_unmatched_rows/total_rows*100:.1f}%)")

    # Top 50 unmatched categories
    print(f"\n{'=' * 80}")
    print("TOP 50 CATEGORIES WITHOUT REGULATORY BENCHMARK")
    print(f"{'=' * 80}")
    print(f"{'Category':35s} {'Rows':>8s} {'Contams':>8s} {'Samples':>10s} {'Has Products':>12s}")
    print("-" * 80)
    for i, (cat, stats) in enumerate(sorted(unmatched.items(), key=lambda x: x[1]["rows"], reverse=True)[:50]):
        has_products = "YES" if cat in product_categories else "no"
        prod_count = product_categories.get(cat, 0)
        print(f"{cat:35s} {stats['rows']:>8,} {stats['contaminants']:>8,} {stats['samples']:>10,} {has_products:>12s}")

    # Categories that have both MRL and tolerance data
    both = mrl_categories & tolerance_categories
    print(f"\n{'=' * 80}")
    print(f"CATEGORIES WITH BOTH MRL AND TOLERANCE DATA ({len(both)})")
    print(f"{'=' * 80}")
    for cat in sorted(both):
        cur.execute("SELECT COUNT(*) FROM international_mrls WHERE food_category = ?", (cat,))
        mrl_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tolerance_limits WHERE food_category = ?", (cat,))
        tol_count = cur.fetchone()[0]
        data_count = data_categories.get(cat, {}).get("rows", 0)
        print(f"  {cat:35s} MRLs={mrl_count:>4}  tolerances={tol_count:>4}  data_rows={data_count:>8,}")

    # Categories with MRL but no data
    print(f"\n{'=' * 80}")
    mrl_no_data = mrl_categories - set(data_categories.keys())
    print(f"CATEGORIES WITH MRL BUT NO MEASUREMENT DATA ({len(mrl_no_data)})")
    print(f"{'=' * 80}")
    for cat in sorted(mrl_no_data):
        cur.execute("SELECT COUNT(*) FROM international_mrls WHERE food_category = ?", (cat,))
        mrl_count = cur.fetchone()[0]
        print(f"  {cat:35s} MRLs={mrl_count:>4}")

    # Alias coverage analysis
    print(f"\n{'=' * 80}")
    print("ALIAS COVERAGE ANALYSIS")
    print(f"{'=' * 80}")
    cur.execute("SELECT alias, canonical_key FROM category_aliases")
    aliases = {r[0]: r[1] for r in cur.fetchall()}

    # Check if unmatched categories have aliases
    print(f"\nUnmatched categories with aliases in category_aliases:")
    found = 0
    for cat in sorted(unmatched.keys(), key=lambda x: unmatched[x]["rows"], reverse=True)[:30]:
        if cat in aliases:
            found += 1
            print(f"  {cat:35s} -> {aliases[cat]}")
    print(f"  Found: {found}")

    # Check if unmatched categories are substrings of MRL categories
    print(f"\nUnmatched categories that are substrings of MRL categories:")
    found = 0
    for cat in sorted(unmatched.keys(), key=lambda x: unmatched[x]["rows"], reverse=True)[:30]:
        for mrl_cat in mrl_categories:
            if cat in mrl_cat or mrl_cat in cat:
                found += 1
                print(f"  {cat:35s} ~= {mrl_cat}")
                break
    print(f"  Found: {found}")

    conn.close()

    print(f"\n{'=' * 80}")
    print("RECOMMENDATIONS")
    print(f"{'=' * 80}")
    print("1. Add aliases for top 20 unmatched categories to category_aliases.csv")
    print("2. Expand EFSA MRL data to cover more food categories")
    print("3. Consider adding 'grain' or 'cereal' as a parent category for wheat/oat/barley")
    print("4. Map 'fresh_vegetables', 'fresh_fruit' to specific categories where possible")


if __name__ == "__main__":
    main()
