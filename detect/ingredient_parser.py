"""
detect/ingredient_parser.py

Parse raw ingredient text (from Open Food Facts) into individual tokens.
Handles common formats: comma-separated, parenthetical sub-ingredients,
allergen warnings, percentages, etc.
"""

import re
from typing import List


# Common non-ingredient noise to strip from tokens
_NOISE_PATTERNS = [
    r'\d+\.?\d*\s*%',                          # percentages like "2.5%"
    r'\*',                                       # asterisks
    r'^\s*-\s*',                                 # leading dashes
    r'\s*\(.*?\)',                               # parenthetical content (keep separately)
    r'\b(?:contains|may contain|traces of)\b.*',  # allergen warnings
    r'\b(?:organic|conventional)\b',             # organic labels
    r'\b(?:enriched|fortified|fortified with)\b', # enrichment notes
]

# Sub-ingredient patterns (inside parentheses)
_SUB_INGREDIENT_PATTERNS = [
    r'\(([^)]+)\)',                              # standard parentheses
    r'\[([^\]]+)\]',                             # square brackets
]


def parse_ingredients(ingredients_text: str) -> List[str]:
    """
    Parse a raw ingredients string into a list of individual ingredient tokens.

    Handles:
    - Comma-separated ingredients
    - Parenthetical sub-ingredients (extracted separately)
    - Allergen warnings (stripped)
    - Percentages (stripped)
    - Common noise patterns

    Args:
        ingredients_text: Raw ingredients string from Open Food Facts
            Example: "Whole grain oats (70%), sugar, corn starch, salt,
                      malt extract. May contain wheat."

    Returns:
        List of cleaned ingredient strings (lowercased, stripped)
        Example: ["whole grain oats", "sugar", "corn starch", "salt", "malt extract"]
    """
    if not ingredients_text or not ingredients_text.strip():
        return []

    # Normalize whitespace and separators
    text = ingredients_text.strip()
    text = re.sub(r'\s+', ' ', text)  # collapse multiple spaces

    # Split by common separators: comma, semicolon, period
    # But be careful with parenthetical content
    raw_tokens = _split_ingredients(text)

    # Clean each token
    cleaned = []
    for token in raw_tokens:
        token = _clean_token(token)
        if token and _is_valid_ingredient(token):
            cleaned.append(token)

    return cleaned


def _split_ingredients(text: str) -> List[str]:
    """
    Split ingredient text by commas, semicolons, and periods.
    Respects parenthetical content.
    """
    tokens = []
    current = []
    paren_depth = 0
    bracket_depth = 0

    for char in text:
        if char == '(':
            paren_depth += 1
            current.append(char)
        elif char == ')':
            paren_depth -= 1
            current.append(char)
        elif char == '[':
            bracket_depth += 1
            current.append(char)
        elif char == ']':
            bracket_depth -= 1
            current.append(char)
        elif char in (',', ';', '.') and paren_depth == 0 and bracket_depth == 0:
            # Split point
            token = ''.join(current).strip()
            if token:
                tokens.append(token)
            current = []
        else:
            current.append(char)

    # Don't forget the last token
    token = ''.join(current).strip()
    if token:
        tokens.append(token)

    return tokens


def _clean_token(token: str) -> str:
    """Clean a single ingredient token."""
    # Remove percentages
    token = re.sub(r'\d+\.?\d*\s*%', '', token)

    # Remove asterisks
    token = token.replace('*', '')

    # Remove leading/trailing dashes and whitespace
    token = re.sub(r'^\s*-\s*', '', token)
    token = token.strip()

    # Remove parenthetical content but keep the main ingredient
    # e.g., "wheat flour (enriched)" -> "wheat flour"
    token = re.sub(r'\s*\([^)]*\)', '', token)
    token = re.sub(r'\s*\[[^\]]*\]', '', token)

    # Remove common suffixes that aren't part of the ingredient name
    suffixes_to_remove = [
        r'\b(?:contains|may contain|traces of)\b.*',
        r'\b(?:organic|conventional)\b',
        r'\b(?:enriched|fortified)\b',
    ]
    for pattern in suffixes_to_remove:
        token = re.sub(pattern, '', token, flags=re.IGNORECASE)

    # Normalize whitespace
    token = re.sub(r'\s+', ' ', token).strip()

    # Lowercase
    token = token.lower()

    return token


def _is_valid_ingredient(token: str) -> bool:
    """Check if a token looks like a valid ingredient."""
    # Must be at least 2 characters
    if len(token) < 2:
        return False

    # Must contain at least one letter
    if not re.search(r'[a-z]', token):
        return False

    # Skip common non-ingredient patterns
    invalid_patterns = [
        r'^(?:and|or|with|contains|may contain|traces of)$',
        r'^(?:ingredients?|composition|made with|prepared with)$',
        r'^\d+$',  # just numbers
        r'^[^a-z]+$',  # no letters at all
    ]
    for pattern in invalid_patterns:
        if re.match(pattern, token, re.IGNORECASE):
            return False

    return True


def extract_sub_ingredients(ingredients_text: str) -> List[str]:
    """
    Extract sub-ingredients from parenthetical content.

    Example: "wheat flour (enriched with iron, niacin)" -> ["enriched with iron", "niacin"]
    """
    sub_ingredients = []
    for pattern in _SUB_INGREDIENT_PATTERNS:
        matches = re.findall(pattern, ingredients_text)
        for match in matches:
            # Split by comma and clean
            parts = [p.strip() for p in match.split(',') if p.strip()]
            sub_ingredients.extend(parts)
    return sub_ingredients
