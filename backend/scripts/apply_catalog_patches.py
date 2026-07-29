"""
Applies all catalog patches without seeding any user or transcript data.
Run after load_catalog.py — locally or against real AWS (prod).

The patch functions live in seed_matthew.py (which also seeds the dev test
user); this entry point exists so production seeding gets the catalog fixes
(ETI junk rows / missing pairs, PHYS 211/250, MATH 250/251, choose_credits
option groups) without creating matthew-test-001.

Usage:
    python scripts/apply_catalog_patches.py
"""

import sys, os
sys.path.append(os.path.dirname(__file__))

from seed_matthew import (
    patch_eti_catalog,
    patch_phys_alternatives,
    patch_known_alternatives,
    patch_choose_credits_option_groups,
)

if __name__ == "__main__":
    patch_eti_catalog()
    patch_phys_alternatives()
    patch_known_alternatives()
    patch_choose_credits_option_groups()
    print("\nAll catalog patches applied.")
