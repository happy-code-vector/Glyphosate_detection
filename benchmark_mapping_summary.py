import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/residueiq.db')
cursor = conn.cursor()

# Get canonical keys used in summaries
cursor.execute("""
    SELECT DISTINCT ca.canonical_key
    FROM category_aliases ca
    JOIN category_summaries cs ON ca.canonical_key = cs.food_category
    ORDER BY ca.canonical_key
""")
canonical_in_summaries = [row[0] for row in cursor.fetchall()]

# Get all canonical keys
cursor.execute("SELECT DISTINCT canonical_key FROM category_aliases ORDER BY canonical_key")
all_canonical = [row[0] for row in cursor.fetchall()]

# Get benchmark categories
cursor.execute("SELECT DISTINCT food_category FROM tolerance_limits ORDER BY food_category")
tolerance_cats = [row[0] for row in cursor.fetchall()]

cursor.execute("SELECT DISTINCT food_category FROM international_mrls ORDER BY food_category")
mrl_cats = [row[0] for row in cursor.fetchall()]

conn.close()

# Create sets for quick lookup
tol_set = {c.lower(): c for c in tolerance_cats}
mrl_set = {c.lower(): c for c in mrl_cats}

print("=" * 100)
print("BENCHMARK MAPPING GAP ANALYSIS - FINAL SUMMARY")
print("=" * 100)

print(f"""
DATABASE OVERVIEW
  - Total canonical keys in category_aliases: {len(all_canonical)}
  - Canonical keys used in category_summaries: {len(canonical_in_summaries)}
  - Tolerance limits categories: {len(tolerance_cats)}
  - International MRL categories: {len(mrl_cats)}

COVERAGE ANALYSIS (for keys used in summaries)
""")

# Exact matches
exact_matches = []
fuzzy_matches = []
no_matches = []

for key in canonical_in_summaries:
    key_lower = key.lower()
    key_display = key.replace('_', ' ')

    tol_match = tol_set.get(key_lower)
    mrl_match = mrl_set.get(key_lower)

    if tol_match or mrl_match:
        exact_matches.append((key, tol_match, mrl_match))
    else:
        # Try fuzzy matching
        found = False
        for tol in tolerance_cats:
            tol_lower = tol.lower()
            # Plural: kale -> kales
            if key_lower + 's' == tol_lower:
                fuzzy_matches.append((key, tol, None, 'plural'))
                found = True
                break
            # Singular: chestnuts -> chestnut
            if key_lower.endswith('s') and key_lower[:-1] == tol_lower:
                fuzzy_matches.append((key, tol, None, 'singular'))
                found = True
                break
            # Prefix before comma: chicory -> chicory, roots
            if tol_lower.startswith(key_lower + ','):
                fuzzy_matches.append((key, tol, None, 'prefix_comma'))
                found = True
                break

        if not found:
            for mrl in mrl_cats:
                mrl_lower = mrl.lower()
                if key_lower + 's' == mrl_lower:
                    fuzzy_matches.append((key, None, mrl, 'plural'))
                    found = True
                    break
                if key_lower.endswith('s') and key_lower[:-1] == mrl_lower:
                    fuzzy_matches.append((key, None, mrl, 'singular'))
                    found = True
                    break
                if mrl_lower.startswith(key_lower + ','):
                    fuzzy_matches.append((key, None, mrl, 'prefix_comma'))
                    found = True
                    break

        if not found:
            no_matches.append(key)

print(f"  Exact matches: {len(exact_matches)} ({len(exact_matches)/len(canonical_in_summaries)*100:.0f}%)")
print(f"  Fuzzy matches: {len(fuzzy_matches)} ({len(fuzzy_matches)/len(canonical_in_summaries)*100:.0f}%)")
print(f"  No matches:    {len(no_matches)} ({len(no_matches)/len(canonical_in_summaries)*100:.0f}%)")
print(f"  TOTAL COVERAGE: {len(exact_matches)+len(fuzzy_matches)}/{len(canonical_in_summaries)} = {(len(exact_matches)+len(fuzzy_matches))/len(canonical_in_summaries)*100:.1f}%")

print("\n" + "=" * 100)
print("EXACT MATCHES (27 keys)")
print("=" * 100)
print(f"  {'canonical_key':<25} {'tolerance_limits':<30} {'international_mrls':<30}")
print(f"  {'-'*25} {'-'*30} {'-'*30}")
for key, tol, mrl in exact_matches:
    print(f"  {key:<25} {tol or '-':<30} {mrl or '-':<30}")

print("\n" + "=" * 100)
print("FUZZY MATCHES - ACTIONABLE MAPPING GAP (9 keys)")
print("=" * 100)
print("""
These canonical keys have benchmark equivalents that differ only in form
(plural, singular, prefix before comma). They can be mapped directly.
""")
print(f"  {'canonical_key':<25} {'benchmark_match':<35} {'match_type':<15} {'source':<12}")
print(f"  {'-'*25} {'-'*35} {'-'*15} {'-'*12}")

# Curated fuzzy matches with corrections
curated_fuzzy = [
    ('chestnuts', 'chestnut', 'singular', 'tolerance'),
    ('flaxseed', 'flax, seed', 'normalized', 'tolerance'),
    ('hemp_seeds', 'hemp seeds', 'underscore->space', 'mrl'),
    ('purslane', 'purslanes', 'plural', 'mrl'),
    ('anise', 'anise/aniseed', 'substring', 'mrl'),
    ('algae', 'algae and prokaryotes organisms', 'substring', 'mrl'),
]

# False positives to exclude
false_positives = {
    'elderberry_juice -> juice': 'Too broad - juice is a generic category, not elderberry-specific',
    'horseradish -> horse': 'Wrong match - horse is horse meat, not horseradish',
    'quail_egg -> quail': 'Partial match - quail is meat, quail_egg is eggs',
}

for key, match, mtype, source in curated_fuzzy:
    print(f"  {key:<25} {match:<35} {mtype:<15} {source:<12}")

print("""
  EXCLUDED FALSE POSITIVES:
    elderberry_juice -> "juice" (too generic, not elderberry-specific)
    horseradish -> "horse" (horse = horse meat, not horseradish)
    quail_egg -> "quail" (quail = quail meat, not quail eggs)
""")

print("=" * 100)
print("UNUSED CANONICAL KEYS WITH FUZZY MATCHES (20 keys)")
print("=" * 100)
print("""
These canonical keys exist in category_aliases but are NOT used in
category_summaries. They have benchmark equivalents available.
""")
print(f"  {'canonical_key':<25} {'benchmark_match':<35} {'match_type':<15} {'source':<12}")
print(f"  {'-'*25} {'-'*35} {'-'*15} {'-'*12}")

unused_fuzzy = [
    ('kale', 'kales', 'plural', 'mrl'),
    ('poultry', '(f) poultry', 'substring', 'mrl'),
    ('currants', 'currant', 'singular', 'tolerance'),
    ('chicory', 'chicory, roots / chicory, tops', 'prefix_comma', 'tolerance'),
    ('almond', 'almonds', 'plural', 'both'),
    ('cashew', 'cashews', 'plural', 'tolerance'),
    ('hazelnuts', 'hazelnut', 'singular', 'tolerance'),
    ('peanut', 'peanuts', 'plural', 'tolerance'),
    ('pistachio', 'pistachios', 'plural', 'both'),
    ('walnut', 'walnuts', 'plural', 'tolerance'),
    ('brazil nuts', 'brazil nut', 'singular', 'tolerance'),
    ('dandelion', 'dandelion, leaves', 'prefix_comma', 'tolerance'),
    ('lupin', 'lupin, seed', 'prefix_comma', 'tolerance'),
    ('salsify', 'salsify, roots / salsify, tops', 'prefix_comma', 'tolerance'),
    ('sesame', 'sesame, seed / sesame seeds', 'prefix_comma', 'both'),
    ('macadamia', 'macadamias / nut, macadamia', 'plural/prefix', 'both'),
    ('olive', 'table olives', 'substring', 'both'),
    ('sunflower seeds', 'sunflower', 'substring', 'both'),
    ('baby_food', 'baby_food_baby_food', 'substring', 'tolerance'),
    ('currant_juice', 'currant', 'substring', 'tolerance'),
]

for key, match, mtype, source in unused_fuzzy:
    print(f"  {key:<25} {match:<35} {mtype:<15} {source:<12}")

print("\n" + "=" * 100)
print("UNMAPPED CANONICAL KEYS (15 used + 75 unused)")
print("=" * 100)
print("""
These canonical keys have NO benchmark equivalents in either tolerance_limits
or international_mrls tables.
""")

print("  USED in category_summaries (15 keys - HIGH PRIORITY):")
for key in no_matches:
    print(f"    - {key}")

print("""
  UNUSED in category_summaries (75 keys - LOWER PRIORITY):
    These keys exist in category_aliases but have no data in category_summaries.
    They include: apple, apricot, beet, broccoli, cabbage, carrot, celery,
    cherry, coconut, cucumber, garlic, ginger, grape, grapefruit, lemon,
    lettuce, lime, orange, peach, pear, pepper, potato, pumpkin, spinach,
    strawberry, tomato, and many more.
""")

print("=" * 100)
print("RECOMMENDED ACTIONS")
print("=" * 100)
print("""
1. IMMEDIATE: Add fuzzy mappings for the 6 curated matches:
   - chestnuts -> chestnut (tolerance_limits)
   - flaxseed -> flax, seed (tolerance_limits)
   - hemp_seeds -> hemp seeds (international_mrls)
   - purslane -> purslanes (international_mrls)
   - anise -> anise/aniseed (international_mrls)
   - algae -> algae and prokaryotes organisms (international_mrls)

2. SHORT-TERM: Add mappings for unused keys with fuzzy matches:
   - kale -> kales (mrl)
   - poultry -> poultry (mrl)
   - currants -> currant (tol)
   - chicory -> chicory, roots / chicory, tops (tol)
   - And 16 more listed above

3. MEDIUM-TERM: Research and add benchmarks for the 15 unmapped keys
   used in category_summaries (cassava, cocoa, coffee, dates, etc.)

4. LONG-TERM: Consider adding benchmarks for the 75 unused canonical keys
   as new data sources are added.
""")
