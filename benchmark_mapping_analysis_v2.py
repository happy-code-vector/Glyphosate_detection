import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/residueiq.db')
cursor = conn.cursor()

# Get all distinct canonical keys from category_aliases
cursor.execute("SELECT DISTINCT canonical_key FROM category_aliases ORDER BY canonical_key")
all_canonical = [row[0] for row in cursor.fetchall()]

# Get canonical keys actually used in category_summaries
cursor.execute("""
    SELECT DISTINCT ca.canonical_key
    FROM category_aliases ca
    JOIN category_summaries cs ON ca.canonical_key = cs.food_category
    ORDER BY ca.canonical_key
""")
canonical_in_summaries = set(row[0] for row in cursor.fetchall())

# Get all tolerance_limits food_categories
cursor.execute("SELECT DISTINCT food_category FROM tolerance_limits ORDER BY food_category")
tolerance_cats = [row[0] for row in cursor.fetchall()]
tolerance_cats_lower = {c.lower(): c for c in tolerance_cats}

# Get all international_mrls food_categories
cursor.execute("SELECT DISTINCT food_category FROM international_mrls ORDER BY food_category")
mrl_cats = [row[0] for row in cursor.fetchall()]
mrl_cats_lower = {c.lower(): c for c in mrl_cats}

# Known semantic mappings (manual knowledge)
SEMANTIC_MAPPINGS = {
    'poultry': {'tolerance': ['chicken', 'turkey', 'duck', 'goose'], 'mrl': ['poultry']},
    'currants': {'tolerance': ['currant'], 'mrl': ['currant']},
    'kale': {'tolerance': ['kales'], 'mrl': ['kales']},
    'potato': {'tolerance': ['potatoes'], 'mrl': ['potato']},
    'tomato': {'tolerance': ['tomatoes'], 'mrl': ['tomato']},
    'carrot': {'tolerance': ['carrots'], 'mrl': ['carrot']},
    'cabbage': {'tolerance': ['cabbages'], 'mrl': ['cabbage']},
}

def find_matches(key, tolerance_list, mrl_list):
    """Find all possible matches for a canonical key in benchmark lists."""
    key_lower = key.lower()
    key_display = key.replace('_', ' ')
    key_stripped_s = key_lower.rstrip('s')
    key_stripped_es = key_lower[:-2] if key_lower.endswith('es') else key_stripped_s
    key_plural_s = key_lower + 's'
    key_plural_es = key_lower + 'es'
    key_with_spaces = key_lower.replace('_', ' ')

    results = {
        'tolerance': [],
        'mrl': []
    }

    for source_name, cat_list in [('tolerance', tolerance_list), ('mrl', mrl_list)]:
        for cat in cat_list:
            cat_lower = cat.lower()
            match_type = None

            # Exact match (case-insensitive)
            if key_lower == cat_lower:
                match_type = 'exact'
            # Underscore/space normalization
            elif key_with_spaces == cat_lower:
                match_type = 'underscore_to_space'
            # Comma-space normalization (e.g. "chicory" in "chicory, roots")
            elif key_with_spaces + ',' in cat_lower or cat_lower.startswith(key_with_spaces + ','):
                match_type = 'prefix_before_comma'
            # Plural variations
            elif key_plural_s == cat_lower:
                match_type = 'plural_s'
            elif key_plural_es == cat_lower:
                match_type = 'plural_es'
            # Singular variations
            elif key_lower.endswith('s') and key_lower[:-1] == cat_lower:
                match_type = 'singular'
            elif key_lower.endswith('es') and key_lower[:-2] == cat_lower:
                match_type = 'singular_es'
            # Substring: key appears in benchmark (meaningful length)
            elif len(key_lower) > 4 and key_lower in cat_lower:
                match_type = 'substring_key_in_cat'
            # Substring: benchmark appears in key (meaningful length)
            elif len(cat_lower) > 4 and cat_lower in key_lower:
                match_type = 'substring_cat_in_key'
            # Strip all punctuation and compare
            elif key_lower.replace('_', '').replace(' ', '').replace('-', '') == cat_lower.replace(',', '').replace(' ', '').replace('-', ''):
                match_type = 'normalized'

            if match_type:
                results[source_name].append((cat, match_type))

    return results

# Priority order for match types
MATCH_PRIORITY = [
    'exact', 'underscore_to_space', 'normalized', 'prefix_before_comma',
    'plural_s', 'plural_es', 'singular', 'singular_es',
    'substring_key_in_cat', 'substring_cat_in_key'
]

def pick_best(matches_list):
    """Pick the best match from a list based on priority."""
    for ptype in MATCH_PRIORITY:
        for cat, mtype in matches_list:
            if mtype == ptype:
                return cat, mtype
    return None, None

# Analyze ALL canonical keys
all_results = []

for key in all_canonical:
    matches = find_matches(key, tolerance_cats, mrl_cats)

    best_tol, tol_type = pick_best(matches['tolerance'])
    best_mrl, mrl_type = pick_best(matches['mrl'])

    # Determine overall match type
    if tol_type == 'exact' or mrl_type == 'exact':
        overall_type = 'exact'
    elif tol_type or mrl_type:
        overall_type = tol_type or mrl_type
    else:
        overall_type = 'none'

    # Collect alternatives for notes
    tol_alts = [f"{cat} [{mt}]" for cat, mt in matches['tolerance'][:6]]
    mrl_alts = [f"{cat} [{mt}]" for cat, mt in matches['mrl'][:6]]

    notes = []
    if len(matches['tolerance']) > 1:
        notes.append(f"TOL: {'; '.join(tol_alts)}")
    if len(matches['mrl']) > 1:
        notes.append(f"MRL: {'; '.join(mrl_alts)}")

    all_results.append({
        'canonical_key': key,
        'in_summaries': key in canonical_in_summaries,
        'tolerance_match': best_tol,
        'tolerance_type': tol_type,
        'mrl_match': best_mrl,
        'mrl_type': mrl_type,
        'overall_type': overall_type,
        'notes': ' | '.join(notes)
    })

conn.close()

# Separate by usage
used_results = [r for r in all_results if r['in_summaries']]
unused_results = [r for r in all_results if not r['in_summaries']]

# Further categorize used results
exact_used = [r for r in used_results if r['overall_type'] == 'exact']
fuzzy_used = [r for r in used_results if r['overall_type'] not in ('exact', 'none')]
no_match_used = [r for r in used_results if r['overall_type'] == 'none']

# Categorize unused results
exact_unused = [r for r in unused_results if r['overall_type'] == 'exact']
fuzzy_unused = [r for r in unused_results if r['overall_type'] not in ('exact', 'none')]
no_match_unused = [r for r in unused_results if r['overall_type'] == 'none']

print("=" * 130)
print("BENCHMARK MAPPING GAP ANALYSIS")
print("=" * 130)
print(f"\nTotal canonical keys in category_aliases: {len(all_canonical)}")
print(f"  - Used in category_summaries: {len(used_results)}")
print(f"  - NOT used in category_summaries: {len(unused_results)}")
print(f"\nFor USED canonical keys ({len(used_results)}):")
print(f"  - Exact matches: {len(exact_used)}")
print(f"  - Fuzzy matches: {len(fuzzy_used)}")
print(f"  - No matches: {len(no_match_used)}")
print(f"  - Coverage with fuzzy: {len(exact_used)+len(fuzzy_used)}/{len(used_results)} = {(len(exact_used)+len(fuzzy_used))/len(used_results)*100:.1f}%")
print(f"\nFor UNUSED canonical keys ({len(unused_results)}):")
print(f"  - Exact matches: {len(exact_unused)}")
print(f"  - Fuzzy matches: {len(fuzzy_unused)}")
print(f"  - No matches: {len(no_match_unused)}")

def print_match_table(title, results_list):
    print(f"\n{'='*130}")
    print(f"  {title}")
    print(f"{'='*130}")
    if not results_list:
        print("  (none)")
        return
    print(f"  {'canonical_key':<28} {'tolerance_match':<38} {'mrl_match':<32} {'match_type':<22} {'used?':<6}")
    print(f"  {'-'*28} {'-'*38} {'-'*32} {'-'*22} {'-'*6}")
    for r in results_list:
        tol = r['tolerance_match'] or '-'
        mrl = r['mrl_match'] or '-'
        used = 'YES' if r['in_summaries'] else 'no'
        print(f"  {r['canonical_key']:<28} {tol:<38} {mrl:<32} {r['overall_type']:<22} {used:<6}")

# Section 1: Exact matches (used in summaries)
print_match_table("USED KEYS WITH EXACT BENCHMARK MATCHES", exact_used)

# Section 2: Fuzzy matches (used in summaries) - the actionable gap
print_match_table("USED KEYS WITH FUZZY MATCHES (ACTIONABLE MAPPING GAP)", fuzzy_used)

# Section 3: No matches (used in summaries) - truly unmapped
print_match_table("USED KEYS WITH NO BENCHMARK MATCHES (TRULY UNMAPPED)", no_match_used)

# Section 4: Unused keys that have fuzzy matches (potential future coverage)
print_match_table("UNUSED KEYS WITH FUZZY MATCHES (FUTURE COVERAGE)", fuzzy_unused)

# Section 5: Unused keys with exact matches
print_match_table("UNUSED KEYS WITH EXACT BENCHMARK MATCHES", exact_unused)

# Section 6: Unused keys with no matches
print_match_table("UNUSED KEYS WITH NO BENCHMARK MATCHES", no_match_unused)

# Detailed notes for fuzzy matches
print(f"\n{'='*130}")
print(f"DETAILED FUZZY MATCH NOTES")
print(f"{'='*130}")
for r in fuzzy_used + fuzzy_unused:
    if r['notes']:
        print(f"\n  {r['canonical_key']}:")
        print(f"    {r['notes']}")

# Summary table: recommended mappings
print(f"\n{'='*130}")
print(f"RECOMMENDED BENCHMARK MAPPINGS TO ADD")
print(f"{'='*130}")
print(f"  {'canonical_key':<28} {'suggested_benchmark':<38} {'match_type':<22} {'source':<12}")
print(f"  {'-'*28} {'-'*38} {'-'*22} {'-'*12}")

actionable = []
for r in fuzzy_used + fuzzy_unused:
    tol = r['tolerance_match']
    mrl = r['mrl_match']
    if tol:
        actionable.append((r['canonical_key'], tol, r['tolerance_type'], 'tolerance'))
    if mrl:
        actionable.append((r['canonical_key'], mrl, r['mrl_type'], 'mrl'))

for key, suggested, mtype, source in actionable:
    print(f"  {key:<28} {suggested:<38} {mtype:<22} {source:<12}")

print(f"\n{'='*130}")
print(f"UNMAPPED CANONICAL KEYS (NO BENCHMARK EXISTS)")
print(f"{'='*130}")
for r in no_match_used + no_match_unused:
    status = "USED in summaries" if r['in_summaries'] else "unused"
    print(f"  {r['canonical_key']:<28} ({status})")
