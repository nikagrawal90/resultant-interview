# app/similarity.py
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein
from app.config import DOMAIN_VARIANT_SCORE, TYPO_MAX_EDITS

def name_sim(a, b):
    if not a or not b:
        return 0.0
    # token_sort_ratio: order-insensitive, but EXTRA tokens still lower the score.
    return fuzz.token_sort_ratio(a, b) / 100.0

def address_sim(a, b):
    if not a or not b:
        return 0.0
    # partial_ratio: containment — a shorter address contained in a longer one scores ~1.0.
    return fuzz.partial_ratio(a, b) / 100.0

def _split_domain(d):
    labels = d.split(".")
    return labels[0], ".".join(labels[1:])   # registrable name, tld-ish

def compare_domain(a, b):
    if not a or not b:
        return "missing"
    if a == b:
        return "exact"
    name_a, tld_a = _split_domain(a)
    name_b, tld_b = _split_domain(b)
    if name_a == name_b:
        return "variant"                     # same name, different TLD -> likely one company
    if Levenshtein.distance(name_a, name_b) <= TYPO_MAX_EDITS:
        return "near"                        # 1-edit name: ambiguous (typo OR different co.)
    return "different"                        # >1 edit: treat as unrelated
