WEIGHTS = {"domain": 0.50, "name": 0.30, "address": 0.20}
THRESHOLDS = {3: 0.82, 2: 0.90}      # 1 field handled specially (exact-only)
REVIEW_BAND = 0.05
BM25_TOP_K = 5
DOMAIN_VARIANT_SCORE = 0.8           # same registrable name, different TLD
TYPO_MAX_EDITS = 1                   # registrable-name Levenshtein still "same"
MIN_TOKEN_LEN = 4                    # tokens with < this many chars are treated as blank
