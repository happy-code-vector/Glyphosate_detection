import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/residueiq.db')
cursor = conn.cursor()

# Step 1: Get all distinct canonical keys used in category_summaries
cursor.execute("""
    SELECT DISTINCT ca.canonical_key
    FROM category_aliases ca
    JOIN category_summaries cs ON ca.canonical_key = cs.food_category
    ORDER BY ca.canonical_key
""")
canonical_in_summaries = [row[0] for row in cursor.fetchall()]

print(f"Canonical keys used in category_summaries: {len(canonical_in_summaries)}")

# Step 2: Get all tolerance_limits food_categories
cursor.execute("SELECT DISTINCT food_category FROM tolerance_limits ORDER BY food_category")
tolerance_cats = [row[0] for row in cursor.fetchall()]
tolerance_cats_lower = {c.lower(): c for c in tolerance_cats}

# Step 3: Get all international_mrls food_categories
cursor.execute("SELECT DISTINCT food_category FROM international_mrls ORDER BY food_category")
mrl_cats = [row[0] for row in cursor.fetchall()]
mrl_cats_lower = {c.lower(): c for c in mrl_cats}

print(f"Tolerance limits categories: {len(tolerance_cats)}")
print(f"International MRL categories: {len(mrl_cats)}")

# Step 4: For each canonical key, find matches
results = []

for key in canonical_in_summaries:
    key_lower = key.lower()
    key_display = key.replace('_', ' ')

    # Check exact match in tolerance_limits
    exact_tolerance = None
    if key_lower in tolerance_cats_lower:
        exact_tolerance = tolerance_cats_lower[key_lower]

    # Check exact match in international_mrls
    exact_mrl = None
    if key_lower in mrl_cats_lower:
        exact_mrl = mrl_cats_lower[key_lower]

    # If we have exact matches, record and continue
    if exact_tolerance or exact_mrl:
        results.append({
            'canonical_key': key,
            'tolerance_match': exact_tolerance if exact_tolerance else 'NO MATCH',
            'mrl_match': exact_mrl if exact_mrl else 'NO MATCH',
            'match_type': 'exact',
            'notes': ''
        })
        continue

    # Search for fuzzy matches
    tolerance_fuzzy = []
    mrl_fuzzy = []

    # Build variants
    key_stripped = key_lower.rstrip('s')
    key_plural_s = key_lower + 's'
    key_plural_es = key_lower + 'es'
    key_with_spaces = key_lower.replace('_', ' ')

    for cat in tolerance_cats:
        cat_lower = cat.lower()

        # Exact case-insensitive
        if key_lower == cat_lower:
            tolerance_fuzzy.append((cat, 'exact_ci'))
        # Underscore/space normalized
        elif key_with_spaces == cat_lower:
            tolerance_fuzzy.append((cat, 'underscore_space'))
        # Normalized (strip commas, spaces, underscores)
        elif key_lower.replace('_', '') == cat_lower.replace(' ', '').replace(',', ''):
            tolerance_fuzzy.append((cat, 'normalized'))
        # Plural: canonical "kale" matches benchmark "kales"
        elif key_plural_s == cat_lower or key_plural_es == cat_lower:
            tolerance_fuzzy.append((cat, 'plural'))
        # Singular: canonical "currants" matches "currant"
        elif key_lower.endswith('s') and key_lower[:-1] == cat_lower:
            tolerance_fuzzy.append((cat, 'singular'))
        elif key_lower.endswith('es') and key_lower[:-2] == cat_lower:
            tolerance_fuzzy.append((cat, 'singular_es'))
        # Substring: key appears inside benchmark name (only if key is meaningful length)
        elif len(key_lower) > 4 and key_lower in cat_lower:
            tolerance_fuzzy.append((cat, 'substring_key_in_cat'))
        # Substring: benchmark appears inside key
        elif len(cat_lower) > 4 and cat_lower in key_lower:
            tolerance_fuzzy.append((cat, 'substring_cat_in_key'))

    for cat in mrl_cats:
        cat_lower = cat.lower()

        if key_lower == cat_lower:
            mrl_fuzzy.append((cat, 'exact_ci'))
        elif key_with_spaces == cat_lower:
            mrl_fuzzy.append((cat, 'underscore_space'))
        elif key_lower.replace('_', '') == cat_lower.replace(' ', '').replace(',', ''):
            mrl_fuzzy.append((cat, 'normalized'))
        elif key_plural_s == cat_lower or key_plural_es == cat_lower:
            mrl_fuzzy.append((cat, 'plural'))
        elif key_lower.endswith('s') and key_lower[:-1] == cat_lower:
            mrl_fuzzy.append((cat, 'singular'))
        elif key_lower.endswith('es') and key_lower[:-2] == cat_lower:
            mrl_fuzzy.append((cat, 'singular_es'))
        elif len(key_lower) > 4 and key_lower in cat_lower:
            mrl_fuzzy.append((cat, 'substring_key_in_cat'))
        elif len(cat_lower) > 4 and cat_lower in key_lower:
            mrl_fuzzy.append((cat, 'substring_cat_in_key'))

    # Pick best matches by priority
    priority_order = [
        'exact_ci', 'underscore_space', 'normalized',
        'plural', 'singular', 'singular_es',
        'substring_key_in_cat', 'substring_cat_in_key'
    ]

    best_tolerance = None
    best_mrl = None
    best_type = None

    for ptype in priority_order:
        if not best_tolerance:
            for cat, mtype in tolerance_fuzzy:
                if mtype == ptype:
                    best_tolerance = cat
                    best_type = mtype
                    break
        if not best_mrl:
            for cat, mtype in mrl_fuzzy:
                if mtype == ptype:
                    best_mrl = cat
                    if not best_type:
                        best_type = mtype
                    break
        if best_tolerance and best_mrl:
            break

    # Collect all matches for notes
    all_tolerance_matches = [f"{cat} [{mtype}]" for cat, mtype in tolerance_fuzzy[:5]]
    all_mrl_matches = [f"{cat} [{mtype}]" for cat, mtype in mrl_fuzzy[:5]]

    notes_parts = []
    if len(tolerance_fuzzy) > 1:
        notes_parts.append(f"TOL options: {'; '.join(all_tolerance_matches)}")
    if len(mrl_fuzzy) > 1:
        notes_parts.append(f"MRL options: {'; '.join(all_mrl_matches)}")

    results.append({
        'canonical_key': key,
        'tolerance_match': best_tolerance if best_tolerance else 'NO MATCH',
        'mrl_match': best_mrl if best_mrl else 'NO MATCH',
        'match_type': best_type if best_type else 'none',
        'notes': ' | '.join(notes_parts)
    })

conn.close()

# Categorize results
exact_matches = [r for r in results if r['match_type'] == 'exact']
fuzzy_matches = [r for r in results if r['match_type'] not in ('exact', 'none')]
no_matches = [r for r in results if r['match_type'] == 'none']

print(f"\n{'='*120}")
print(f"MAPPING ANALYSIS SUMMARY")
print(f"{'='*120}")
print(f"Total canonical keys in category_summaries: {len(canonical_in_summaries)}")
print(f"  - Exact matches (both TOL + MRL or one): {len(exact_matches)}")
print(f"  - Fuzzy matches found (tolerance_limits or mrls): {len(fuzzy_matches)}")
print(f"  - No matches at all: {len(no_matches)}")
print(f"  - Coverage with fuzzy: {len(exact_matches) + len(fuzzy_matches)}/{len(canonical_in_summaries)} = {(len(exact_matches)+len(fuzzy_matches))/len(canonical_in_summaries)*100:.1f}%")

print(f"\n{'='*120}")
print(f"SECTION 1: EXACT MATCHES")
print(f"{'='*120}")
print(f"{'canonical_key':<30} {'TOL match':<35} {'MRL match':<35}")
print(f"{'-'*30} {'-'*35} {'-'*35}")
for r in exact_matches:
    tol = r['tolerance_match'] if r['tolerance_match'] != 'NO MATCH' else '-'
    mrl = r['mrl_match'] if r['mrl_match'] != 'NO MATCH' else '-'
    print(f"{r['canonical_key']:<30} {tol:<35} {mrl:<35}")

print(f"\n{'='*120}")
print(f"SECTION 2: FUZZY MATCHES (should be added to mapping)")
print(f"{'='*120}")
print(f"{'canonical_key':<30} {'TOL match':<35} {'MRL match':<30} {'match_type':<20}")
print(f"{'-'*30} {'-'*35} {'-'*30} {'-'*20}")
for r in fuzzy_matches:
    tol = r['tolerance_match'] if r['tolerance_match'] != 'NO MATCH' else '-'
    mrl = r['mrl_match'] if r['mrl_match'] != 'NO MATCH' else '-'
    print(f"{r['canonical_key']:<30} {tol:<35} {mrl:<30} {r['match_type']:<20}")

print(f"\n{'='*120}")
print(f"SECTION 3: NO MATCHES FOUND (truly unmapped)")
print(f"{'='*120}")
for r in no_matches:
    print(f"  {r['canonical_key']}")

# Detailed fuzzy match notes
print(f"\n{'='*120}")
print(f"DETAILED FUZZY MATCH NOTES (multiple candidates)")
print(f"{'='*120}")
for r in fuzzy_matches:
    if r['notes']:
        print(f"\n  {r['canonical_key']}:")
        print(f"    {r['notes']}")

# Also check: canonical keys NOT used in category_summaries but exist in aliases
print(f"\n{'='*120}")
print(f"SECTION 4: CANONICAL KEYS NOT USED IN CATEGORY_SUMMARIES")
print(f"{'='*120}")
cursor2 = sqlite3.connect('data/residueiq.db').cursor()
cursor2.execute("""
    SELECT DISTINCT ca.canonical_key
    FROM category_aliases ca
    WHERE ca.canonical_key NOT IN (
        SELECT DISTINCT food_category FROM category_summaries
    )
    ORDER BY ca.canonical_key
""")
unused = [row[0] for row in cursor2.fetchall()]
print(f"Count: {len(unused)}")
for k in unused:
    print(f"  {k}")
cursor2.close()
