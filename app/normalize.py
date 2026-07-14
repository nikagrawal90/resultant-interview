import re
from app.models import RawRecord, NormalizedRecord
from app.config import MIN_TOKEN_LEN

_LEGAL_SUFFIXES = {
    "corp", "corporation", "co", "inc", "incorporated", "llc", "ltd",
    "limited", "limitd", "plc", "gmbh", "lp", "llp",
}
_ADDRESS_ABBR = {
    "st": "street", "ave": "avenue", "av": "avenue", "rd": "road",
    "blvd": "boulevard", "ln": "lane", "dr": "drive", "plz": "plaza",
    "sq": "square", "ste": "suite",
}
_MULTI_TLDS = {"co.uk", "com.au", "co.in", "co.jp", "com.br"}

def _clean_tokens(s):
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)          # punctuation -> space
    return [t for t in s.split() if t]

def normalize_name(s):
    if not s:
        return ""
    tokens = [t for t in _clean_tokens(s) if t not in _LEGAL_SUFFIXES]
    tokens = sorted(tokens)                  # token reorder is noise
    joined = " ".join(tokens)
    return joined if len(joined) >= MIN_TOKEN_LEN else ""

def normalize_address(s):
    if not s:
        return ""
    tokens = [_ADDRESS_ABBR.get(t, t) for t in _clean_tokens(s)]
    joined = " ".join(tokens)
    return joined if len(joined) >= MIN_TOKEN_LEN else ""

def normalize_domain(s):
    if not s:
        return ""
    s = s.strip().lower()
    s = re.sub(r"^[a-z]+://", "", s)         # scheme
    s = s.split("/")[0].split("?")[0].split("#")[0]   # path/query/fragment
    s = s.split(":")[0]                       # port
    if s.startswith("www."):
        s = s[4:]
    labels = s.split(".")
    if len(labels) <= 2:
        return s
    last2 = ".".join(labels[-2:])
    last3 = ".".join(labels[-3:])
    if last2 in _MULTI_TLDS:                  # keep 3 labels for co.uk etc.
        return last3
    return last2                              # collapse subdomains

def normalize_record(raw):
    return NormalizedRecord(
        id=raw.id,
        name=normalize_name(raw.name),
        address=normalize_address(raw.address),
        domain=normalize_domain(raw.website),
        raw=raw,
    )
