# Record Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A FastAPI service that reconciles messy company records into groups, each represented by one canonical record with a confidence score, incrementally.

**Architecture:** A linear pipeline — normalize → generate candidates → score/decide → union → merge. Pure-Python owns the algorithm (normalization, similarity, scoring, union-find, merge); file-backed SQLite owns storage and candidate generation (indexed exact lookups + FTS5 trigram BM25). A group is one canonical record in the active set; every raw row is kept in an audit table.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, Pydantic v2, RapidFuzz (string similarity), SQLite (stdlib `sqlite3`, FTS5 trigram), pytest, httpx (TestClient).

## Global Constraints

- **Cost asymmetry:** a false merge is worse than a false split. When in doubt, do not merge.
- **All comparisons run on normalized strings.** "Exact" means `sim == 1.0` after normalization.
- **Normalization is formatting-noise only** — never strip descriptor tokens (`Solutions`, `Systems`, `Group`).
- **Weights:** domain 0.50, name 0.30, address 0.20 (re-normalized over scored fields).
- **Thresholds by scored-field count:** 3 → 0.82, 2 → 0.90, 1 → exact-only (domain exact merges; name/address exact = review).
- **Review band:** within 0.05 below threshold → left unmerged + logged (no human queue).
- **Domain in score:** exact → 1.0; same-registrable-name/different-TLD variant → 0.8; different registrable name → excluded from score (and a veto candidate per the veto rule).
- **SQLite:** file-backed, WAL mode; FTS5 with `tokenize='trigram'` (requires SQLite ≥ 3.34); single shared connection, `check_same_thread=False`.
- All tunable values (weights, thresholds, band, top-K) live in `app/config.py`.
- See `decisions.md` (13 decisions) and `edge-cases.md` for the full rationale each task implements.

---

## File Structure

```
app/
  config.py       # weights, thresholds, review band, BM25 top-K — all tunable
  models.py       # RawRecord, NormalizedRecord, CanonicalRecord, PairDecision
  normalize.py    # normalize_name / _address / _domain / _record (formatting-noise only)
  similarity.py   # name_sim, address_sim, compare_domain
  scoring.py      # score_pair → PairDecision (weighted score + tiered gate + veto + confidence)
  grouping.py     # UnionFind
  merge.py        # build_canonical (fill blanks, conflict precedence)
  store.py        # SQLite: schema, exact lookups, FTS5 trigram search, canonical+audit, index upkeep
  reconcile.py    # Reconciler: add_record (candidate→score→union→merge→persist), reconcile_batch
  api.py          # FastAPI: POST /records, POST /reconcile, GET /groups, GET /groups/{id}
tests/
  test_normalize.py test_similarity.py test_scoring.py test_grouping.py
  test_merge.py test_store.py test_reconcile.py test_api.py
data/sample.json  # the 9 assignment rows
requirements.txt
```

---

### Task 1: Project scaffold, config, models, sample data

**Files:**
- Create: `requirements.txt`, `app/__init__.py`, `app/config.py`, `app/models.py`, `data/sample.json`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `app.config` constants `WEIGHTS: dict[str,float]`, `THRESHOLDS: dict[int,float]`, `REVIEW_BAND: float`, `BM25_TOP_K: int`, `DOMAIN_VARIANT_SCORE: float`, `TYPO_MAX_EDITS: int`.
- Produces: `app.models.RawRecord`, `NormalizedRecord`, `CanonicalRecord`, `PairDecision` (Pydantic models / dataclasses with the fields below).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from app import config

def test_weights_sum_to_one():
    assert abs(sum(config.WEIGHTS.values()) - 1.0) < 1e-9
    assert set(config.WEIGHTS) == {"domain", "name", "address"}

def test_thresholds_present():
    assert config.THRESHOLDS[3] == 0.82
    assert config.THRESHOLDS[2] == 0.90
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: Write the files**

```python
# app/config.py
WEIGHTS = {"domain": 0.50, "name": 0.30, "address": 0.20}
THRESHOLDS = {3: 0.82, 2: 0.90}      # 1 field handled specially (exact-only)
REVIEW_BAND = 0.05
BM25_TOP_K = 5
DOMAIN_VARIANT_SCORE = 0.8           # same registrable name, different TLD
TYPO_MAX_EDITS = 1                   # registrable-name Levenshtein still "same"
MIN_TOKEN_LEN = 4                    # tokens with < this many chars are treated as blank
```

```python
# app/models.py
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class RawRecord:
    id: str
    name: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    source: Optional[str] = None

@dataclass
class NormalizedRecord:
    id: str
    name: str = ""       # normalized; "" means absent/too-short
    address: str = ""
    domain: str = ""     # registrable domain, e.g. "acme.com"; "" means absent
    raw: Optional[RawRecord] = None

@dataclass
class CanonicalRecord:
    group_id: int
    name: str = ""
    address: str = ""
    domain: str = ""
    confidence: int = 100
    member_ids: list[str] = field(default_factory=list)

@dataclass
class PairDecision:
    score: float
    decision: str        # "merge" | "review" | "no_merge"
    confidence: int
    reason: str
```

```python
# app/__init__.py  (empty)
```

```json
// data/sample.json
[
  {"id": "1", "name": "Acme Corporation", "address": "123 Main St", "website": "acme.com"},
  {"id": "2", "name": "Acme Corp.", "address": "123 Main Street", "website": null},
  {"id": "3", "name": "ACME", "address": null, "website": "acme.com"},
  {"id": "4", "name": "Globex Inc", "address": "500 Park Ave", "website": "globex.io"},
  {"id": "5", "name": "Globex Incorporated", "address": "500 Park Avenue, Suite 200", "website": "globex.io"},
  {"id": "6", "name": "Initech LLC", "address": "1 Tech Plaza", "website": "initech.com"},
  {"id": "7", "name": "Initech Solutions", "address": "1 Tech Plz", "website": "initech.co"},
  {"id": "8", "name": "Innotech", "address": "9 Innovation Way", "website": "innotech.com"},
  {"id": "9", "name": "Globed Systems", "address": "77 River Rd", "website": "globed.com"}
]
```

```
# requirements.txt
fastapi>=0.110
uvicorn>=0.29
pydantic>=2.6
rapidfuzz>=3.6
httpx>=0.27
pytest>=8.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add requirements.txt app/ data/ tests/test_config.py
git commit -m "chore: scaffold app config, models, and sample data"
```

---

### Task 2: Normalization (formatting-noise only)

**Files:**
- Create: `app/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Consumes: `RawRecord`, `NormalizedRecord`, `config.MIN_TOKEN_LEN`.
- Produces: `normalize_name(s: str|None) -> str`, `normalize_address(s: str|None) -> str`, `normalize_domain(s: str|None) -> str`, `normalize_record(raw: RawRecord) -> NormalizedRecord`.

- [ ] **Step 1: Write the failing tests** (cases drawn from `edge-cases.md` A/B)

```python
# tests/test_normalize.py
from app.normalize import normalize_name, normalize_address, normalize_domain, normalize_record
from app.models import RawRecord

def test_name_strips_legal_suffix_and_casing():
    assert normalize_name("Acme Corporation") == "acme"
    assert normalize_name("Acme Corp.") == "acme"
    assert normalize_name("ACME") == "acme"

def test_name_keeps_descriptor_tokens():
    assert normalize_name("Initech LLC") == "initech"
    assert normalize_name("Initech Solutions") == "initech solutions"  # descriptor kept

def test_name_token_reorder_is_canonicalized():
    assert normalize_name("Corporation Acme") == "acme"

def test_address_abbreviations_expand():
    assert normalize_address("123 Main St") == "123 main street"
    assert normalize_address("1 Tech Plz") == "1 tech plaza"

def test_domain_strips_scheme_www_path_subdomain():
    assert normalize_domain("https://www.acme.com/about?x=1") == "acme.com"
    assert normalize_domain("ACME.COM") == "acme.com"
    assert normalize_domain("blog.acme.com") == "acme.com"

def test_short_tokens_become_blank():
    assert normalize_name("AB") == ""   # 1-3 char token dropped

def test_normalize_record_maps_website_to_domain():
    r = normalize_record(RawRecord(id="3", name="ACME", address=None, website="acme.com"))
    assert r.domain == "acme.com" and r.name == "acme" and r.address == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.normalize'`

- [ ] **Step 3: Write the implementation**

```python
# app/normalize.py
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_normalize.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add app/normalize.py tests/test_normalize.py
git commit -m "feat: per-field formatting-noise normalization"
```

---

### Task 3: Similarity functions

**Files:**
- Create: `app/similarity.py`
- Test: `tests/test_similarity.py`

**Interfaces:**
- Consumes: `rapidfuzz`, `config.DOMAIN_VARIANT_SCORE`, `config.TYPO_MAX_EDITS`.
- Produces:
  - `name_sim(a: str, b: str) -> float` (0–1, extra tokens penalize).
  - `address_sim(a: str, b: str) -> float` (0–1, containment).
  - `compare_domain(a: str, b: str) -> str` — one of `"exact"`, `"variant"`, `"near"`, `"different"`, `"missing"` (four-state classification per decision #4).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_similarity.py
from app.similarity import name_sim, address_sim, compare_domain

def test_name_exact_after_suffix_strip():
    assert name_sim("acme", "acme") == 1.0

def test_name_extra_descriptor_token_penalized():
    assert 0.4 < name_sim("initech", "initech solutions") < 0.8   # not 1.0

def test_address_containment_not_penalized():
    assert address_sim("500 park avenue", "500 park avenue suite 200") > 0.95

def test_domain_states():
    assert compare_domain("acme.com", "acme.com") == "exact"
    assert compare_domain("initech.com", "initech.co") == "variant"   # same name, diff TLD
    assert compare_domain("globex.io", "globed.com") == "near"        # 1-edit name: ambiguous
    assert compare_domain("infitech.com", "inftech.com") == "near"    # typo in name: ambiguous
    assert compare_domain("foo.com", "zzzbar.com") == "different"     # >1 edit: unrelated
    assert compare_domain("", "acme.com") == "missing"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_similarity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.similarity'`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_similarity.py -v`
Expected: PASS (4 tests)

> Note (record in review): `name_sim` uses `token_sort_ratio` (extra tokens penalize, per #B2); `address_sim` uses `partial_ratio` (containment, per #5). This split is the refinement raised at plan time. `compare_domain` is four-state (#4): `exact`/`variant` score 1.0/0.8; a 1-edit registrable name is `near` (ambiguous — excluded, never vetoes); only `different` (>1 edit) is a veto candidate. `near` is what makes globex/globed and a genuine typo pair both resolve on name+address.

- [ ] **Step 5: Commit**

```bash
git add app/similarity.py tests/test_similarity.py
git commit -m "feat: field similarity — name (token-sort), address (partial), domain (structured 3-state)"
```

---

### Task 4: Pair scoring & decision

**Files:**
- Create: `app/scoring.py`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `NormalizedRecord`, `PairDecision`, `name_sim`, `address_sim`, `compare_domain`, all of `config`.
- Produces: `score_pair(a: NormalizedRecord, b: NormalizedRecord) -> PairDecision`.

**Logic (from #4/#6/#7/#10/#11):**
1. Determine fields present on **both** records: name, address, domain.
2. Domain contributes to the score only when `compare_domain` is `"exact"` (1.0) or `"variant"` (0.8); `"near"`/`"different"`/`"missing"` → domain excluded from scored fields.
3. **Veto:** if name AND address both present with `sim == 1.0` (exact) and `compare_domain == "different"` → `no_merge` (veto), regardless of score. Note `"near"` does **not** veto (it is ambiguous, per #4).
4. Weighted score over scored fields, weights re-normalized.
5. Gate by scored-field count: 1 field → merge only if exact (domain exact → merge; name/address exact → review); else compare to `THRESHOLDS[count]`; within `REVIEW_BAND` below → review; below that → no_merge.
6. Confidence = `round(score*100)` capped by scored-field count (3→99, 2→95, 1→90).

- [ ] **Step 1: Write the failing tests** (the sample-row assertions from `decisions.md` #11)

```python
# tests/test_scoring.py
from app.normalize import normalize_record
from app.models import RawRecord
from app.scoring import score_pair

def _n(id, name, addr, web):
    return normalize_record(RawRecord(id=id, name=name, address=addr, website=web))

def test_acme_1_3_merge_on_domain_and_name():
    d = score_pair(_n("1","Acme Corporation","123 Main St","acme.com"),
                   _n("3","ACME",None,"acme.com"))
    assert d.decision == "merge" and d.score > 0.95

def test_initech_6_7_review_band():
    d = score_pair(_n("6","Initech LLC","1 Tech Plaza","initech.com"),
                   _n("7","Initech Solutions","1 Tech Plz","initech.co"))
    assert d.decision == "review"

def test_initech_innotech_no_merge():
    d = score_pair(_n("6","Initech LLC","1 Tech Plaza","initech.com"),
                   _n("8","Innotech","9 Innovation Way","innotech.com"))
    assert d.decision == "no_merge"

def test_globex_globed_no_merge():
    d = score_pair(_n("4","Globex Inc","500 Park Ave","globex.io"),
                   _n("9","Globed Systems","77 River Rd","globed.com"))
    assert d.decision == "no_merge"

def test_veto_blocks_exact_name_address_with_different_domain():
    d = score_pair(_n("a","Foo Bar","1 Main Street","foo.com"),
                   _n("b","Foo Bar","1 Main Street","zzzbar.com"))
    assert d.decision == "no_merge" and "veto" in d.reason
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_scoring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scoring'`

- [ ] **Step 3: Write the implementation**

```python
# app/scoring.py
from app.models import NormalizedRecord, PairDecision
from app.similarity import name_sim, address_sim, compare_domain
from app.config import WEIGHTS, THRESHOLDS, REVIEW_BAND, DOMAIN_VARIANT_SCORE

_CONF_CAP = {3: 99, 2: 95, 1: 90}

def score_pair(a: NormalizedRecord, b: NormalizedRecord) -> PairDecision:
    sims = {}
    if a.name and b.name:
        sims["name"] = name_sim(a.name, b.name)
    if a.address and b.address:
        sims["address"] = address_sim(a.address, b.address)

    dom = compare_domain(a.domain, b.domain)
    if dom == "exact":
        sims["domain"] = 1.0
    elif dom == "variant":
        sims["domain"] = DOMAIN_VARIANT_SCORE

    # Veto (#10): exact name+address but a genuinely different registrable-name domain.
    if (sims.get("name") == 1.0 and sims.get("address") == 1.0 and dom == "different"):
        return PairDecision(0.0, "no_merge", 0, "veto: conflicting domain")

    if not sims:
        return PairDecision(0.0, "no_merge", 0, "no comparable fields")

    total_w = sum(WEIGHTS[f] for f in sims)
    score = sum(WEIGHTS[f] * s for f, s in sims.items()) / total_w
    n = len(sims)
    conf = min(round(score * 100), _CONF_CAP[n])

    if n == 1:
        field, sim = next(iter(sims.items()))
        if sim == 1.0 and field == "domain":
            return PairDecision(score, "merge", conf, "single exact domain")
        if sim == 1.0:
            return PairDecision(score, "review", conf, f"single exact {field} (collides)")
        return PairDecision(score, "no_merge", conf, "single non-exact field")

    threshold = THRESHOLDS[n]
    if score >= threshold:
        return PairDecision(score, "merge", conf, f"score {score:.2f} >= {threshold}")
    if score >= threshold - REVIEW_BAND:
        return PairDecision(score, "review", conf, f"score {score:.2f} in review band")
    return PairDecision(score, "no_merge", conf, f"score {score:.2f} < band")
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_scoring.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add app/scoring.py tests/test_scoring.py
git commit -m "feat: pair scoring, tiered gate, domain veto, evidence-capped confidence"
```

---

### Task 5: Union-find grouping

**Files:**
- Create: `app/grouping.py`
- Test: `tests/test_grouping.py`

**Interfaces:**
- Produces: `UnionFind` with `find(x) -> x`, `union(x, y) -> None`, `groups() -> dict[root, list[members]]`, `add(x) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_grouping.py
from app.grouping import UnionFind

def test_transitive_grouping():
    uf = UnionFind()
    for x in ["1", "2", "3", "9"]:
        uf.add(x)
    uf.union("1", "2")       # name+address
    uf.union("1", "3")       # domain
    groups = {frozenset(v) for v in uf.groups().values()}
    assert frozenset({"1", "2", "3"}) in groups
    assert frozenset({"9"}) in groups
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_grouping.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.grouping'`

- [ ] **Step 3: Write the implementation**

```python
# app/grouping.py
from collections import defaultdict

class UnionFind:
    def __init__(self):
        self.parent = {}

    def add(self, x):
        self.parent.setdefault(x, x)

    def find(self, x):
        self.add(x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:          # path compression
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[ry] = rx

    def groups(self):
        out = defaultdict(list)
        for x in self.parent:
            out[self.find(x)].append(x)
        return dict(out)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_grouping.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add app/grouping.py tests/test_grouping.py
git commit -m "feat: union-find for connected-component grouping"
```

---

### Task 6: Canonical merge

**Files:**
- Create: `app/merge.py`
- Test: `tests/test_merge.py`

**Interfaces:**
- Consumes: `NormalizedRecord`, `CanonicalRecord`.
- Produces: `build_canonical(group_id: int, members: list[NormalizedRecord], confidence: int) -> CanonicalRecord`.

**Logic (#8):** for each of name/address/domain, pick the **longest** non-empty raw value (fill blanks); tie → first-seen. Name/address use the raw strings (readable); domain uses the normalized registrable domain. `member_ids` lists all members.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_merge.py
from app.normalize import normalize_record
from app.models import RawRecord
from app.merge import build_canonical

def _n(id, name, addr, web):
    return normalize_record(RawRecord(id=id, name=name, address=addr, website=web))

def test_fill_blanks_and_prefer_longest():
    members = [_n("1","Acme Corporation","123 Main St","acme.com"),
               _n("3","ACME",None,"acme.com")]
    c = build_canonical(10, members, confidence=99)
    assert c.name == "Acme Corporation"     # longest raw name
    assert c.address == "123 Main St"        # filled from the member that has it
    assert c.domain == "acme.com"
    assert set(c.member_ids) == {"1", "3"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_merge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.merge'`

- [ ] **Step 3: Write the implementation**

```python
# app/merge.py
from app.models import NormalizedRecord, CanonicalRecord

def _pick_longest(values):
    # values in member (first-seen) order; longest wins, tie -> first-seen
    best = ""
    for v in values:
        if v and len(v) > len(best):
            best = v
    return best

def build_canonical(group_id, members, confidence):
    names = [m.raw.name or "" for m in members]
    addrs = [m.raw.address or "" for m in members]
    domains = [m.domain for m in members]        # normalized registrable domain
    return CanonicalRecord(
        group_id=group_id,
        name=_pick_longest(names),
        address=_pick_longest(addrs),
        domain=_pick_longest(domains),
        confidence=confidence,
        member_ids=[m.id for m in members],
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_merge.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add app/merge.py tests/test_merge.py
git commit -m "feat: canonical merge — fill blanks, longest value wins"
```

---

### Task 7: SQLite store (storage + candidate generation)

**Files:**
- Create: `app/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `CanonicalRecord`, `RawRecord`.
- Produces: `Store(db_path: str)` with:
  - `init_schema() -> None`
  - `upsert_canonical(c: CanonicalRecord) -> None`
  - `delete_canonical(group_id: int) -> None`
  - `get_canonical(group_id: int) -> CanonicalRecord | None`
  - `all_canonicals() -> list[CanonicalRecord]`
  - `add_audit(group_id: int, raw: RawRecord) -> None`
  - `candidate_group_ids(name: str, address: str, domain: str, top_k: int) -> set[int]` (exact domain + exact name + exact address + trigram BM25 over `name+address`)

- [ ] **Step 1: Write the failing test** (use `:memory:` shared cache for the test)

```python
# tests/test_store.py
import sqlite3, pytest
from app.store import Store
from app.models import CanonicalRecord, RawRecord

@pytest.fixture
def store():
    s = Store("file:teststore?mode=memory&cache=shared")
    s.init_schema()
    return s

def test_fts5_trigram_available():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")  # raises if unsupported

def test_exact_domain_candidate(store):
    store.upsert_canonical(CanonicalRecord(1, "Acme Corporation", "123 Main St", "acme.com", 99, ["1"]))
    assert 1 in store.candidate_group_ids(name="acme", address="", domain="acme.com", top_k=5)

def test_trigram_typo_candidate(store):
    store.upsert_canonical(CanonicalRecord(1, "Initech", "1 Tech Plaza", "initech.com", 99, ["6"]))
    # a typo'd name still surfaces via trigram BM25
    assert 1 in store.candidate_group_ids(name="intech", address="1 tech plaza", domain="", top_k=5)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.store'`

- [ ] **Step 3: Write the implementation**

```python
# app/store.py
import sqlite3
from app.models import CanonicalRecord, RawRecord

class Store:
    def __init__(self, db_path):
        uri = db_path.startswith("file:")
        self.con = sqlite3.connect(db_path, uri=uri, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")

    def init_schema(self):
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS canonical (
                group_id INTEGER PRIMARY KEY,
                name TEXT, address TEXT, domain TEXT,
                norm_name TEXT, norm_address TEXT,
                confidence INTEGER, member_ids TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_domain ON canonical(domain);
            CREATE INDEX IF NOT EXISTS ix_name ON canonical(norm_name);
            CREATE INDEX IF NOT EXISTS ix_address ON canonical(norm_address);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER, raw_id TEXT,
                name TEXT, address TEXT, website TEXT
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS canonical_fts
                USING fts5(text, group_id UNINDEXED, tokenize='trigram');
        """)
        self.con.commit()

    def upsert_canonical(self, c):
        self.delete_canonical(c.group_id)
        self.con.execute(
            "INSERT INTO canonical VALUES (?,?,?,?,?,?,?,?)",
            (c.group_id, c.name, c.address, c.domain,
             _norm(c.name), _norm(c.address), c.confidence, ",".join(c.member_ids)),
        )
        self.con.execute(
            "INSERT INTO canonical_fts(text, group_id) VALUES (?,?)",
            (f"{_norm(c.name)} {_norm(c.address)}".strip(), c.group_id),
        )
        self.con.commit()

    def delete_canonical(self, group_id):
        self.con.execute("DELETE FROM canonical WHERE group_id=?", (group_id,))
        self.con.execute("DELETE FROM canonical_fts WHERE group_id=?", (group_id,))
        self.con.commit()

    def get_canonical(self, group_id):
        row = self.con.execute("SELECT * FROM canonical WHERE group_id=?", (group_id,)).fetchone()
        return _row_to_canonical(row) if row else None

    def all_canonicals(self):
        return [_row_to_canonical(r) for r in self.con.execute("SELECT * FROM canonical")]

    def add_audit(self, group_id, raw):
        self.con.execute(
            "INSERT INTO audit(group_id, raw_id, name, address, website) VALUES (?,?,?,?,?)",
            (group_id, raw.id, raw.name, raw.address, raw.website),
        )
        self.con.commit()

    def candidate_group_ids(self, name, address, domain, top_k):
        ids = set()
        if domain:
            ids |= {r["group_id"] for r in self.con.execute(
                "SELECT group_id FROM canonical WHERE domain=?", (domain,))}
        if name:
            ids |= {r["group_id"] for r in self.con.execute(
                "SELECT group_id FROM canonical WHERE norm_name=?", (name,))}
        if address:
            ids |= {r["group_id"] for r in self.con.execute(
                "SELECT group_id FROM canonical WHERE norm_address=?", (address,))}
        query = f"{name} {address}".strip()
        if query:
            escaped = '"' + query.replace('"', '""') + '"'
            ids |= {r["group_id"] for r in self.con.execute(
                "SELECT group_id FROM canonical_fts WHERE canonical_fts MATCH ? "
                "ORDER BY bm25(canonical_fts) LIMIT ?", (escaped, top_k))}
        return ids

def _norm(s):
    return (s or "").lower().strip()

def _row_to_canonical(r):
    return CanonicalRecord(
        group_id=r["group_id"], name=r["name"], address=r["address"], domain=r["domain"],
        confidence=r["confidence"], member_ids=r["member_ids"].split(",") if r["member_ids"] else [],
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_store.py -v`
Expected: PASS (3 tests). If `test_fts5_trigram_available` fails, the Python build lacks FTS5/trigram — document in README and fall back to a Python trigram index (stretch).

- [ ] **Step 5: Commit**

```bash
git add app/store.py tests/test_store.py
git commit -m "feat: SQLite store — canonical/audit tables, exact indexes, FTS5 trigram candidates"
```

---

### Task 8: Reconciler orchestrator + end-to-end sample test

**Files:**
- Create: `app/reconcile.py`
- Test: `tests/test_reconcile.py`

**Interfaces:**
- Consumes: `Store`, `UnionFind`, `normalize_record`, `score_pair`, `build_canonical`, `RawRecord`, `CanonicalRecord`, `config.BM25_TOP_K`.
- Produces: `Reconciler(store: Store)` with `add_record(raw: RawRecord) -> int` (returns group_id) and `reconcile_batch(raws: list[RawRecord]) -> list[CanonicalRecord]`.

**Logic (#12):** normalize → get candidate group ids from store → score new record against each candidate group's canonical → collect groups with a `merge` decision → union new record with those groups (bridging if ≥2) → recompute the canonical for the resulting group from all its members (kept in a `norm` cache keyed by group) → upsert canonical, add audit, index. New group id if no merges.

- [ ] **Step 1: Write the failing test** (the whole assignment, end to end)

```python
# tests/test_reconcile.py
import json
from app.store import Store
from app.reconcile import Reconciler
from app.models import RawRecord

def _load():
    with open("data/sample.json") as f:
        return [RawRecord(**row) for row in json.load(f)]

def test_sample_groups():
    store = Store("file:recon?mode=memory&cache=shared")
    store.init_schema()
    r = Reconciler(store)
    canon = r.reconcile_batch(_load())
    groups = sorted(sorted(c.member_ids, key=int) for c in canon)
    assert ["1", "2", "3"] in groups
    assert ["4", "5"] in groups
    assert ["6"] in groups and ["7"] in groups    # Initech pair left separate (review band)
    assert ["8"] in groups and ["9"] in groups
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_reconcile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reconcile'`

- [ ] **Step 3: Write the implementation**

```python
# app/reconcile.py
from app.normalize import normalize_record
from app.scoring import score_pair
from app.merge import build_canonical
from app.grouping import UnionFind
from app.models import NormalizedRecord, CanonicalRecord
from app.config import BM25_TOP_K

class Reconciler:
    def __init__(self, store):
        self.store = store
        self.uf = UnionFind()
        self.members: dict[int, list[NormalizedRecord]] = {}   # group_id -> normalized members
        self._next_id = 1

    def _canonical_as_norm(self, c):
        from app.models import RawRecord
        return normalize_record(RawRecord(id=f"g{c.group_id}", name=c.name,
                                          address=c.address, website=c.domain))

    def add_record(self, raw):
        nr = normalize_record(raw)
        cand_ids = self.store.candidate_group_ids(nr.name, nr.address, nr.domain, BM25_TOP_K)

        merge_roots = set()
        for gid in cand_ids:
            canon = self.store.get_canonical(gid)
            if canon and score_pair(nr, self._canonical_as_norm(canon)).decision == "merge":
                merge_roots.add(self.uf.find(gid))

        if not merge_roots:
            gid = self._next_id
            self._next_id += 1
            self.uf.add(gid)
            self.members[gid] = [nr]
            root = gid
        else:
            root = min(merge_roots)
            self.uf.add(root)
            for other in merge_roots:
                self.uf.union(root, other)
            root = self.uf.find(root)
            merged = [nr]
            for r in merge_roots:                 # gather members of every bridged group
                merged += self.members.pop(r, [])
            self.members[root] = merged
            for r in merge_roots:                 # drop stale canonicals from the store/index
                if r != root:
                    self.store.delete_canonical(r)

        members = self.members[self.uf.find(root)]
        conf = self._group_confidence(members)
        canon = build_canonical(self.uf.find(root), members, conf)
        self.store.upsert_canonical(canon)
        self.store.add_audit(canon.group_id, raw)
        return canon.group_id

    def _group_confidence(self, members):
        if len(members) == 1:
            return 100
        worst = 100
        for i in range(len(members)):             # weakest pairwise edge in the group
            for j in range(i + 1, len(members)):
                worst = min(worst, score_pair(members[i], members[j]).confidence)
        return worst

    def reconcile_batch(self, raws):
        for raw in raws:
            self.add_record(raw)
        return self.store.all_canonicals()
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_reconcile.py -v`
Expected: PASS. If Initech 6–7 merge instead of staying separate, confirm scoring Task 4 returns `review` (not `merge`) for that pair.

- [ ] **Step 5: Commit**

```bash
git add app/reconcile.py tests/test_reconcile.py
git commit -m "feat: incremental reconciler with candidate gen, bridging, group confidence"
```

---

### Task 9: FastAPI surface

**Files:**
- Create: `app/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `Store`, `Reconciler`, `RawRecord`.
- Produces: a FastAPI `app` with `POST /records`, `POST /reconcile`, `GET /groups`, `GET /groups/{group_id}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api.py
import os
# Point the app at an isolated in-memory DB BEFORE importing it, so the test
# never touches the on-disk reconciliation.db (avoids cross-run state).
os.environ["RECONCILIATION_DB"] = "file:apitest?mode=memory&cache=shared"
from fastapi.testclient import TestClient
from app.api import app

def test_batch_then_get_groups():
    client = TestClient(app)
    rows = [
        {"id": "1", "name": "Acme Corporation", "address": "123 Main St", "website": "acme.com"},
        {"id": "3", "name": "ACME", "address": None, "website": "acme.com"},
    ]
    r = client.post("/reconcile", json={"records": rows})
    assert r.status_code == 200
    groups = client.get("/groups").json()
    assert any(set(g["member_ids"]) == {"1", "3"} for g in groups)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api'`

- [ ] **Step 3: Write the implementation**

```python
# app/api.py
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.store import Store
from app.reconcile import Reconciler
from app.models import RawRecord

app = FastAPI(title="Record Reconciliation")
# File-backed and durable by default; override with RECONCILIATION_DB (tests use an in-memory DB).
_store = Store(os.environ.get("RECONCILIATION_DB", "file:reconciliation.db"))
_store.init_schema()
_recon = Reconciler(_store)

class RecordIn(BaseModel):
    id: str
    name: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    source: Optional[str] = None

class BatchIn(BaseModel):
    records: list[RecordIn]

def _raw(r: RecordIn) -> RawRecord:
    return RawRecord(id=r.id, name=r.name, address=r.address, website=r.website, source=r.source)

@app.post("/records")
def add_record(r: RecordIn):
    gid = _recon.add_record(_raw(r))
    return _store.get_canonical(gid)

@app.post("/reconcile")
def reconcile(batch: BatchIn):
    _recon.reconcile_batch([_raw(r) for r in batch.records])
    return _store.all_canonicals()

@app.get("/groups")
def all_groups():
    return _store.all_canonicals()

@app.get("/groups/{group_id}")
def get_group(group_id: int):
    c = _store.get_canonical(group_id)
    if not c:
        raise HTTPException(404, "group not found")
    return c
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api.py tests/test_api.py
git commit -m "feat: FastAPI endpoints for add, batch reconcile, and group reads"
```

---

### Task 10: README + full-suite green

**Files:**
- Create: `README.md`

- [ ] **Step 1: Run the full suite**

Run: `pytest -v`
Expected: all tests pass.

- [ ] **Step 2: Write `README.md`** — under one page: how to run (`pip install -r requirements.txt`, `uvicorn app.api:app --reload`, `pytest`), the key decisions (link `decisions.md`), and a "where it breaks" section (link `edge-cases.md` §E). Include the sample-run output showing the six groups.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README with run instructions, decisions summary, and where-it-breaks"
```

---

## Self-Review Notes

- **Spec coverage:** normalization (#2/#3 → Task 2), similarity incl. structured domain (#4/#5 → Task 3), scoring/tiered gate/veto/confidence (#6/#7/#10/#11 → Task 4), grouping/union (#9 → Task 5), canonical merge/precedence (#8 → Task 6), SQLite + trigram candidates (#12/#13 → Task 7), incremental reconcile + bridging (#12 → Task 8), API (#13 → Task 9). All 13 decisions map to a task.
- **Known assumption to verify first:** FTS5 + trigram tokenizer must be present in the runtime's SQLite (Task 7 Step 1 checks it). If absent, the fallback is a ~30-line Python trigram inverted index behind the same `candidate_group_ids` interface.
- **Refinement flagged for user review:** name uses `token_sort_ratio` (extras penalize), address uses `partial_ratio` (containment). Recorded in Task 3.
- **`_group_confidence` is O(k²) in group size** — fine for the small groups this domain produces; noted for scale.
