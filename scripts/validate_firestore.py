"""
scripts/validate_firestore.py

Side-by-side validation: run the same queries against SQLite and Firestore,
compare results, report discrepancies.

Usage:
    python scripts/validate_firestore.py
    python scripts/validate_firestore.py --db data/residueiq.db --cred firebase-service-account.json
    python scripts/validate_firestore.py --categories oats,wheat,rice --contaminants glyphosate,lead
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.sqlite_store import SqliteDataStore
from data.firestore_store import FirestoreDataStore


# ── Test queries ────────────────────────────────────────────────────────────

CATEGORIES = ["oats", "wheat", "rice", "strawberry", "corn", "spinach", "apple"]
CONTAMINANTS = ["glyphosate", "lead", "cadmium"]
STATES = ["California", "Iowa", "Texas", "New York"]


def compare(label: str, sqlite_val, firestore_val, tolerance: float = 0.01):
    """Compare two values. Returns (match: bool, detail: str)."""
    if sqlite_val is None and firestore_val is None:
        return True, "both None"
    if sqlite_val is None or firestore_val is None:
        return False, f"sqlite={sqlite_val} vs firestore={firestore_val}"

    # Numeric comparison with tolerance
    if isinstance(sqlite_val, (int, float)) and isinstance(firestore_val, (int, float)):
        if abs(sqlite_val - firestore_val) <= tolerance * max(abs(sqlite_val), 1):
            return True, f"{sqlite_val}"
        return False, f"sqlite={sqlite_val} vs firestore={firestore_val}"

    # String comparison
    if str(sqlite_val) == str(firestore_val):
        return True, f"{sqlite_val}"
    return False, f"sqlite={sqlite_val!r} vs firestore={firestore_val!r}"


def compare_dicts(label: str, sqlite_rows: list[dict], firestore_rows: list[dict],
                  key_fields: list[str], value_fields: list[str]) -> list[dict]:
    """Compare two lists of dicts by key fields, checking value fields."""
    issues = []

    # Index by key
    def make_key(d):
        return tuple(str(d.get(f, "")) for f in key_fields)

    sqlite_idx = {make_key(r): r for r in sqlite_rows}
    firestore_idx = {make_key(r): r for r in firestore_rows}

    # Check keys present in SQLite but missing in Firestore
    for key in sqlite_idx:
        if key not in firestore_idx:
            issues.append({
                "test": label, "issue": "missing_in_firestore",
                "key": dict(zip(key_fields, key)),
            })

    # Check keys present in Firestore but missing in SQLite
    for key in firestore_idx:
        if key not in sqlite_idx:
            issues.append({
                "test": label, "issue": "extra_in_firestore",
                "key": dict(zip(key_fields, key)),
            })

    # Compare values for matching keys
    for key in sqlite_idx:
        if key not in firestore_idx:
            continue
        s_row = sqlite_idx[key]
        f_row = firestore_idx[key]
        for field in value_fields:
            s_val = s_row.get(field)
            f_val = f_row.get(field)
            match, detail = compare(f"{label}.{field}", s_val, f_val)
            if not match:
                issues.append({
                    "test": label, "issue": "value_mismatch",
                    "key": dict(zip(key_fields, key)),
                    "field": field,
                    "detail": detail,
                })

    return issues


# ── Validation tests ────────────────────────────────────────────────────────

def validate_food_overview(store_s, store_f) -> list[dict]:
    """Compare food_overview for all category+contaminant combos."""
    issues = []
    for cat in CATEGORIES:
        for contam in CONTAMINANTS:
            label = f"food_overview({cat}, {contam})"
            try:
                s_rows = store_s.get_food_overview(cat, contam)
            except Exception as e:
                issues.append({"test": label, "issue": "sqlite_error", "detail": str(e)})
                continue
            try:
                f_rows = store_f.get_food_overview(cat, contam)
            except Exception as e:
                issues.append({"test": label, "issue": "firestore_error", "detail": str(e)})
                continue

            if len(s_rows) != len(f_rows):
                issues.append({
                    "test": label, "issue": "row_count_mismatch",
                    "detail": f"sqlite={len(s_rows)} vs firestore={len(f_rows)}",
                })
                continue

            for i, (s, f) in enumerate(zip(s_rows, f_rows)):
                for field in ["food_category", "contaminant", "best_source",
                              "detection_rate", "avg_ppb", "max_ppb",
                              "samples_total", "samples_detected", "risk_level"]:
                    match, detail = compare(f"{label}[{i}].{field}", s.get(field), f.get(field))
                    if not match:
                        issues.append({
                            "test": label, "issue": "value_mismatch",
                            "index": i, "field": field, "detail": detail,
                        })
    return issues


def validate_product_lookup(store_s, store_f) -> list[dict]:
    """Compare product lookup results."""
    issues = []
    queries = ["Cheerios", "oat", "wheat", "rice"]
    for q in queries:
        label = f"product_lookup({q!r})"
        try:
            s_rows = store_s.get_product_lookup(q)
            f_rows = store_f.get_product_lookup(q)
        except Exception as e:
            issues.append({"test": label, "issue": "error", "detail": str(e)})
            continue

        if len(s_rows) != len(f_rows):
            issues.append({
                "test": label, "issue": "row_count_mismatch",
                "detail": f"sqlite={len(s_rows)} vs firestore={len(f_rows)}",
            })
            # Don't compare values if counts differ — but still report
            continue

        # Compare by product_name (order may differ)
        s_by_name = {r["product_name"]: r for r in s_rows}
        f_by_name = {r["product_name"]: r for r in f_rows}
        for name in s_by_name:
            if name not in f_by_name:
                issues.append({"test": label, "issue": "missing_in_firestore", "product": name})
            else:
                for field in ["contaminant", "measured_ppb", "risk_level"]:
                    match, detail = compare(
                        f"{label}({name}).{field}",
                        s_by_name[name].get(field),
                        f_by_name[name].get(field),
                    )
                    if not match:
                        issues.append({
                            "test": label, "issue": "value_mismatch",
                            "product": name, "field": field, "detail": detail,
                        })
    return issues


def validate_water_overview(store_s, store_f) -> list[dict]:
    """Compare water overview results."""
    issues = []
    for state in STATES:
        for contam in CONTAMINANTS:
            label = f"water_overview({state}, {contam})"
            try:
                s_rows = store_s.get_water_overview(state=state, contaminant=contam)
                f_rows = store_f.get_water_overview(state=state, contaminant=contam)
            except Exception as e:
                issues.append({"test": label, "issue": "error", "detail": str(e)})
                continue

            if len(s_rows) != len(f_rows):
                issues.append({
                    "test": label, "issue": "row_count_mismatch",
                    "detail": f"sqlite={len(s_rows)} vs firestore={len(f_rows)}",
                })
                continue

            for i, (s, f) in enumerate(zip(s_rows, f_rows)):
                for field in ["contaminant", "state", "water_type",
                              "detection_rate", "avg_ppb", "max_ppb"]:
                    match, detail = compare(f"{label}[{i}].{field}", s.get(field), f.get(field))
                    if not match:
                        issues.append({
                            "test": label, "issue": "value_mismatch",
                            "index": i, "field": field, "detail": detail,
                        })
    return issues


def validate_international_comparison(store_s, store_f) -> list[dict]:
    """Compare international MRL comparisons."""
    issues = []
    for cat in CATEGORIES[:4]:
        for contam in CONTAMINANTS[:2]:
            label = f"intl_comparison({cat}, {contam})"
            try:
                s_rows = store_s.get_international_comparison(cat, contam)
                f_rows = store_f.get_international_comparison(cat, contam)
            except Exception as e:
                issues.append({"test": label, "issue": "error", "detail": str(e)})
                continue

            if len(s_rows) != len(f_rows):
                issues.append({
                    "test": label, "issue": "row_count_mismatch",
                    "detail": f"sqlite={len(s_rows)} vs firestore={len(f_rows)}",
                })
                continue

            for i, (s, f) in enumerate(zip(s_rows, f_rows)):
                for field in ["country_region", "mrl_ppb", "regulatory_body"]:
                    match, detail = compare(f"{label}[{i}].{field}", s.get(field), f.get(field))
                    if not match:
                        issues.append({
                            "test": label, "issue": "value_mismatch",
                            "index": i, "field": field, "detail": detail,
                        })
    return issues


def validate_biomonitoring(store_s, store_f) -> list[dict]:
    """Compare biomonitoring data."""
    issues = []
    label = "biomonitoring(all)"
    try:
        s_rows = store_s.get_biomonitoring()
        f_rows = store_f.get_biomonitoring()
    except Exception as e:
        issues.append({"test": label, "issue": "error", "detail": str(e)})
        return issues

    if len(s_rows) != len(f_rows):
        issues.append({
            "test": label, "issue": "row_count_mismatch",
            "detail": f"sqlite={len(s_rows)} vs firestore={len(f_rows)}",
        })
        return issues

    for i, (s, f) in enumerate(zip(s_rows, f_rows)):
        for field in ["analyte", "cycle", "sample_size", "detection_rate"]:
            match, detail = compare(f"{label}[{i}].{field}", s.get(field), f.get(field))
            if not match:
                issues.append({
                    "test": label, "issue": "value_mismatch",
                    "index": i, "field": field, "detail": detail,
                })
    return issues


def validate_ingredients(store_s, store_f) -> list[dict]:
    """Compare ingredient lookups."""
    issues = []
    names = ["potassium_bromate", "red_40", "glyphosate", "lead"]
    for name in names:
        label = f"ingredient({name})"
        try:
            s_row = store_s.get_ingredient(ingredient_id=name)
            f_row = store_f.get_ingredient(ingredient_id=name)
        except Exception as e:
            issues.append({"test": label, "issue": "error", "detail": str(e)})
            continue

        if s_row is None and f_row is None:
            continue
        if s_row is None or f_row is None:
            issues.append({
                "test": label, "issue": "presence_mismatch",
                "detail": f"sqlite={'found' if s_row else 'None'} vs firestore={'found' if f_row else 'None'}",
            })
            continue

        for field in ["ingredient_id", "display_name", "contaminant_type"]:
            match, detail = compare(f"{label}.{field}", s_row.get(field), f_row.get(field))
            if not match:
                issues.append({
                    "test": label, "issue": "value_mismatch",
                    "field": field, "detail": detail,
                })
    return issues


def validate_commodities(store_s, store_f) -> list[dict]:
    """Compare commodity lookups."""
    issues = []
    slugs = ["oats", "wheat", "strawberry", "corn", "rice"]
    for slug in slugs:
        label = f"commodity({slug})"
        try:
            s_row = store_s.get_commodity(slug)
            f_row = store_f.get_commodity(slug)
        except Exception as e:
            issues.append({"test": label, "issue": "error", "detail": str(e)})
            continue

        if s_row is None and f_row is None:
            continue
        if s_row is None or f_row is None:
            issues.append({
                "test": label, "issue": "presence_mismatch",
                "detail": f"sqlite={'found' if s_row else 'None'} vs firestore={'found' if f_row else 'None'}",
            })
            continue

        for field in ["commodity_slug", "display_name", "consumption_tier", "dirty_dozen"]:
            match, detail = compare(f"{label}.{field}", s_row.get(field), f_row.get(field))
            if not match:
                issues.append({
                    "test": label, "issue": "value_mismatch",
                    "field": field, "detail": detail,
                })
    return issues


def validate_regulatory(store_s, store_f) -> list[dict]:
    """Compare tolerance limits and MRLs."""
    issues = []
    for cat in CATEGORIES[:4]:
        for contam in CONTAMINANTS[:2]:
            # Tolerance limits
            label = f"tolerance({contam}, {cat})"
            try:
                s_tol = store_s.get_tolerance_limit(contam, cat)
                f_tol = store_f.get_tolerance_limit(contam, cat)
            except Exception as e:
                issues.append({"test": label, "issue": "error", "detail": str(e)})
                continue

            if s_tol is None and f_tol is None:
                pass
            elif s_tol is None or f_tol is None:
                issues.append({
                    "test": label, "issue": "presence_mismatch",
                    "detail": f"sqlite={'found' if s_tol else 'None'} vs firestore={'found' if f_tol else 'None'}",
                })
            else:
                match, detail = compare(f"{label}.tolerance_ppb",
                                        s_tol.get("tolerance_ppb"), f_tol.get("tolerance_ppb"))
                if not match:
                    issues.append({"test": label, "issue": "value_mismatch", "detail": detail})

            # MRLs
            label = f"mrl({contam}, {cat})"
            try:
                s_mrl = store_s.get_strictest_mrl(contam, cat)
                f_mrl = store_f.get_strictest_mrl(contam, cat)
            except Exception as e:
                issues.append({"test": label, "issue": "error", "detail": str(e)})
                continue

            if s_mrl is None and f_mrl is None:
                pass
            elif s_mrl is None or f_mrl is None:
                issues.append({
                    "test": label, "issue": "presence_mismatch",
                    "detail": f"sqlite={'found' if s_mrl else 'None'} vs firestore={'found' if f_mrl else 'None'}",
                })
            else:
                match, detail = compare(f"{label}.mrl_ppb",
                                        s_mrl.get("mrl_ppb"), f_mrl.get("mrl_ppb"))
                if not match:
                    issues.append({"test": label, "issue": "value_mismatch", "detail": detail})
    return issues


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Validate Firestore data against SQLite")
    parser.add_argument("--db", default=str(Path(__file__).parent.parent / "data" / "residueiq.db"))
    parser.add_argument("--cred", default=str(Path(__file__).parent.parent / "firebase-service-account.json"))
    parser.add_argument("--database", default="purityiq")
    parser.add_argument("--categories", default=None, help="Comma-separated categories to test")
    parser.add_argument("--contaminants", default=None, help="Comma-separated contaminants to test")
    args = parser.parse_args()

    global CATEGORIES, CONTAMINANTS
    if args.categories:
        CATEGORIES = args.categories.split(",")
    if args.contaminants:
        CONTAMINANTS = args.contaminants.split(",")

    print("=" * 60)
    print("  ResidueIQ - SQLite vs Firestore Validation")
    print("=" * 60)
    print(f"  SQLite:    {args.db}")
    print(f"  Firestore: {args.database}")
    print(f"  Categories: {CATEGORIES}")
    print(f"  Contaminants: {CONTAMINANTS}")
    print("=" * 60)

    # Connect
    print("\n[1/9] Connecting to SQLite...")
    try:
        store_s = SqliteDataStore(db_path=args.db)
        print("  [OK] SQLite connected")
    except Exception as e:
        print(f"  [FAIL] SQLite connection failed: {e}")
        sys.exit(1)

    print("\n[2/9] Connecting to Firestore...")
    try:
        store_f = FirestoreDataStore(cred_path=args.cred, database_id=args.database)
        print("  [OK] Firestore connected")
    except Exception as e:
        print(f"  [FAIL] Firestore connection failed: {e}")
        sys.exit(1)

    # Run validations
    all_issues = []
    tests = [
        ("3/9  Food Overview", validate_food_overview),
        ("4/9  Product Lookup", validate_product_lookup),
        ("5/9  Water Overview", validate_water_overview),
        ("6/9  International Comparison", validate_international_comparison),
        ("7/9  Biomonitoring", validate_biomonitoring),
        ("8/9  Ingredients", validate_ingredients),
        ("9/9  Commodities", validate_commodities),
        ("     Regulatory", validate_regulatory),
    ]

    for step_label, test_fn in tests:
        print(f"\n[{step_label}]")
        try:
            issues = test_fn(store_s, store_f)
            if not issues:
                print("  [OK] All matched")
            else:
                print(f"  [FAIL] {len(issues)} discrepancy(ies):")
                for issue in issues[:10]:  # Show first 10
                    print(f"    - {issue}")
                if len(issues) > 10:
                    print(f"    ... and {len(issues) - 10} more")
                all_issues.extend(issues)
        except Exception as e:
            print(f"  [FAIL] Test failed with error: {e}")
            all_issues.append({"test": step_label, "issue": "test_error", "detail": str(e)})

    # Summary
    print("\n" + "=" * 60)
    if not all_issues:
        print("  [OK] ALL VALIDATIONS PASSED - Firestore matches SQLite")
    else:
        print(f"  [FAIL] {len(all_issues)} DISCREPANCY(IES) FOUND")
        print()
        # Group by issue type
        by_type = {}
        for issue in all_issues:
            t = issue.get("issue", "unknown")
            by_type.setdefault(t, []).append(issue)
        for issue_type, items in sorted(by_type.items()):
            print(f"  {issue_type}: {len(items)} occurrence(s)")
    print("=" * 60)

    store_s.close()
    store_f.close()

    return 0 if not all_issues else 1


if __name__ == "__main__":
    sys.exit(main())
