"""
Phase 4A: Static Key Collision Audit
Parses app.py and extracts every key= argument from Streamlit widget calls.
Asserts all keys are unique.
"""

import re
import sys


def extract_keys(filepath: str) -> list[str]:
    """Extract all key= string values from Streamlit widget calls."""
    with open(filepath, "r") as f:
        source = f.read()

    # Match key=f"..." and key="..." patterns
    # Pattern 1: key=f"..." (f-strings) — extract the template
    fstring_keys = re.findall(r'\bkey\s*=\s*f"([^"]+)"', source)
    # Pattern 2: key="..." (plain strings)
    plain_keys = re.findall(r'\bkey\s*=\s*"([^"]+)"', source)

    return fstring_keys + plain_keys


def expand_fstring_keys(templates: list[str]) -> list[str]:
    """
    Expand f-string key templates by substituting known prefixes.
    e.g., '{key_prefix}_dte' -> ['csp_dte', 'cc_dte']
    """
    expanded = []
    for tmpl in templates:
        variants = [tmpl]
        # Expand all known template variables
        new_variants = []
        for v in variants:
            if "{key_prefix}" in v:
                new_variants.extend([v.replace("{key_prefix}", p) for p in ["csp", "cc"]])
            else:
                new_variants.append(v)
        variants = new_variants

        new_variants = []
        for v in variants:
            if "{tab_id}" in v:
                new_variants.extend([v.replace("{tab_id}", t) for t in ["csp", "cc"]])
            else:
                new_variants.append(v)
        variants = new_variants

        new_variants = []
        for v in variants:
            if "{detail_key}" in v:
                new_variants.extend([v.replace("{detail_key}", d) for d in ["detail_put", "detail_call"]])
            else:
                new_variants.append(v)
        variants = new_variants

        new_variants = []
        for v in variants:
            if "{top_n}" in v:
                new_variants.append(v.replace("{top_n}", "25"))
            else:
                new_variants.append(v)
        variants = new_variants

        expanded.extend(variants)
    return expanded


def run_audit(filepath: str = "app.py") -> bool:
    raw_keys = extract_keys(filepath)
    all_keys = expand_fstring_keys(raw_keys)

    print(f"Found {len(raw_keys)} key templates -> {len(all_keys)} expanded keys:")
    for k in sorted(all_keys):
        print(f"  {k}")

    seen = {}
    duplicates = []
    for k in all_keys:
        if k in seen:
            duplicates.append(k)
        seen[k] = True

    if duplicates:
        print(f"\nDuplicates: {duplicates}")
        print("RESULT: FAIL")
        return False
    else:
        print(f"\nDuplicates: NONE")
        print("RESULT: PASS")
        return True


if __name__ == "__main__":
    success = run_audit()
    sys.exit(0 if success else 1)
