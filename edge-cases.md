# Critical Edge Cases

These are the concrete cases that *forced* our decisions. Each one records the example, the tension it exposed, and the decision it drove (cross-referenced to `decisions.md`). The assignment explicitly asks us to build our own hard cases — "the pairs that are almost the same are the interesting ones" — so this file is also our evidence that the design was pressure-tested, not guessed.

Row numbers refer to the assignment's sample table:

| # | Name | Address | Website |
|---|------|---------|---------|
| 1 | Acme Corporation | 123 Main St | acme.com |
| 2 | Acme Corp. | 123 Main Street | *(blank)* |
| 3 | ACME | *(blank)* | acme.com |
| 4 | Globex Inc | 500 Park Ave | globex.io |
| 5 | Globex Incorporated | 500 Park Avenue, Suite 200 | globex.io |
| 6 | Initech LLC | 1 Tech Plaza | initech.com |
| 7 | Initech Solutions | 1 Tech Plz | initech.co |
| 8 | Innotech | 9 Innovation Way | innotech.com |
| 9 | Globed Systems | 77 River Rd | globed.com |

---

## A. Domain edge cases

### A1. Same name + address, different TLD — `initech.com` vs `initech.co` (rows 6 & 7)
Everything except the domain says "same company": near-identical name (`Initech`) and the same address written two ways (`1 Tech Plaza` / `1 Tech Plz`). But the domains differ.

- **Tension:** if a domain *difference* means "different company," these wrongly stay apart; a company can legitimately own both `.com` and `.co`.
- **Drove:** domain is **evidence, not a verdict** (#1); a differing domain is not automatically negative (#4). Same registrable name + different TLD = a *variant*, not a conflict → does **not** veto a merge (#10).

### A2. One-character registrable name, different company — `globex.io` vs `globed.com` (rows 4/5 vs 9)
`globex` vs `globed` is a single character apart.

- **Tension:** proportional / edit-distance string similarity rates these ~90% similar → it would push toward *merge*. But they are different companies, and our own rule says "a small domain change can mean a different company."
- **Drove:** **raw string similarity is the wrong tool for domains** (#4). Compare domains **structurally** (registrable name vs TLD), not by character overlap. A different *registrable name* is a real signal of a different company (#10). Also: name (`Globex` vs `Globed Systems`) and address (`500 Park Ave` vs `77 River Rd`) differ, so these never even reach the name+address-exact branch — context filters them out.

### A3. Typo in the registrable name — `infitech.com` vs `inftech.com` (constructed)
A one-character difference that is almost certainly a **typo of one real domain**.

- **Tension:** this is character-for-character the *same shape* of difference as A2 (globex/globed), yet the correct answer is the opposite — same company. Edit distance alone cannot tell A2 from A3.
- **Drove:** a near-domain match is **ambiguous** → neutral weight on its own; **defer to name + address** (#4). We never merge on a fuzzy domain alone (respects the cost asymmetry). Fuzzy-domain similarity is instead reserved for **candidate generation** (recall), not the merge decision (precision). The typo case is why the veto rule has a "modulo typo" exception (#10).

### A4. Exact-but-different domains on otherwise-matching records (the #4-meets-#7 seam)
Two records that match on name and address but each carry a *different, clean* domain (e.g. via a domain-less hub bridging `initech.com` and `innotech.com`, or a franchise sharing name+address).

- **Tension:** name+address say "merge"; a clean conflicting domain says "different." Which wins?
- **Drove:** the **conflicting-domain veto** (#10): when name+address already match, a differing domain vetoes the merge **only if the registrable names differ by more than a typo**; a different TLD alone does not veto. This is the one place we lean on a fuzzy domain notion, and it is only safe because it fires exclusively inside the name+address-exact branch — logged in "where it breaks."

---

## B. Name / address edge cases

### B1. Near name, different company — `Initech` vs `Innotech` (rows 6/7 vs 8)
Two names a couple of characters apart, but different companies (different domains, different addresses).

- **Tension:** a fuzzy name match scores high; if a lone name match could merge, these collapse.
- **Drove:** names **collide**, so a single fuzzy name/address match is never sufficient on its own — it needs corroboration (#7, field-aware tiered rule).

### B2. Descriptor tokens are signal, not noise — `Initech LLC` vs `Initech Solutions` (rows 6 & 7)
If normalization stripped *descriptor* tokens, both collapse to `initech` → an "exact" match that could merge two possibly-different companies on a lone name.

- **Tension:** aggressive normalization makes "exact match" achievable but turns our strictest merge rule into a foot-gun.
- **Drove:** **formatting-noise-only normalization** (#3). Strip legal-suffix noise (`LLC`, `Corp.`) but keep descriptor tokens (`Solutions`, `Systems`, `Group`) as identifying signal.

### B3. Truncation / abbreviation — `Acme` vs `Acme Corporation`; `1 Tech Plz` vs `1 Tech Plaza`
One value is a shortened form of the other.

- **Tension:** symmetric similarity penalizes the shorter string for "missing" tokens, hiding a real match.
- **Drove:** match against the **shorter string** (containment / token-subset), and normalize abbreviations (`Plz`→`Plaza`, `St`→`Street`) as formatting noise (#3, #5).

### B4. Tokens in a different order
The assignment warns tokens may be reordered.

- **Drove:** **token reordering** counts as formatting noise and is normalized away before comparison (#3).

### B5. Very short tokens — 1–3 characters
A 1–3 character token matches almost anything.

- **Tension:** basing a match on a tiny string produces garbage merges.
- **Drove:** tokens of **1–3 characters are treated as blank** — too short to match reliably (#5).

---

## C. Missing-field edge cases

### C1. Strong signal present, weak signal absent — rows 1 & 3 (exact domain, no address)
Rows 1 and 3 share an **exact domain** (`acme.com`) but row 3 has no address and only a partial name (`ACME`).

- **Tension:** if a missing field counts as 0 in the score while still counting in the "perfect" denominator, this pair is penalized for a missing address and may fall below threshold — even though an exact domain ≈ same company.
- **Drove:** **missing fields drop out of both numerator and denominator** — weights re-normalize over the fields actually present (#6). Confidence is computed over present fields.

### C2. "Present" must mean present on *both* records
A field on only one record (e.g. domain on row 1, blank on row 2) has nothing to compare against.

- **Drove:** **"present" = present on both** (#6). A one-sided field can be *filled in* at merge time but cannot *support* the match.

### C3. Sparse records — how little evidence is enough?
A record with only one or two populated fields.

- **Tension:** the fewer fields shared, the easier an accidental match — and a wrong merge is the expensive error.
- **Drove:** the **field-aware tiered rule** (#7): 3 fields → each may be fuzzy if combined score is high; 2 fields → both need a really high score; 1 field → it must match **exactly**, and a lone name/address (which collide) is weaker than a lone exact domain.

---

## D. Grouping & merge edge cases

### D1. Transitive grouping — the Acme trio (rows 1, 2, 3)
1↔2 link on name+address (row 2 has no website); 1↔3 link on domain (row 3 has no address); 2↔3 share almost nothing directly.

- **Tension:** the correct output `{1,2,3}` only exists via transitivity — 2 and 3 come together *through* 1.
- **Drove:** grouping by **connected components / union** of above-threshold pairs (#9).

### D2. Runaway over-merge via a weak chain (why union is still safe here)
Constructed chain `Initech LLC → Initech Solutions Grp → Innotech ...` that would collapse Initech and Innotech into one group.

- **Tension:** union only compares adjacent pairs, so a chain of weak links could bridge two different companies and bypass the domain veto.
- **Resolution:** the chain **cannot form** under our rules — the middle links fail the tiered exact-match requirement (`Grp` is a kept descriptor so names aren't exact; `1 Tech Plz` ≠ `2 Tech Plaza`). Because every edge needs an **exact anchor**, and exact-normalized matches are effectively transitive, union cannot drag in a stranger. **Precision lives in edge creation (#7), which lets grouping stay a dumb union (#9).**

### D3. Canonical merge — filling and conflicts — rows 1 & 3 → merged
Merging `Acme Corporation / 123 Main St / acme.com` with `ACME / (blank) / acme.com`.

- **Drove:** fill each field from the **most complete value** (`Acme Corporation`, `123 Main St`, `acme.com`) (#8). For *filling blanks* this is safe; for genuinely **conflicting** non-empty values "bigger wins" is arbitrary → retain provenance so the choice is auditable/reversible (open item).

---

## E. Where it breaks (residual failures we accept, for the writeup)

- **Two truly different companies that share an exact name *and* exact address with no domains** — no field can separate them, so they merge. Unavoidable given the data.
- **The conflicting-domain veto leans on a fuzzy domain notion** inside the name+address-exact branch — defensible only because of that narrow scope (A4).
- **A single shared domain across genuine subsidiaries/branches** would over-merge, since we treat an exact domain as ~99% same (open risk in `decisions.md`).
- **Confidence can read over-optimistically** when very few fields are present (matching 1 of 1 fields is less certain than 3 of 3) — pending the evidence-aware confidence refinement.
- **A typo'd domain is not used for candidate *generation*.** The trigram/BM25 index covers name+address only; domain candidates are exact-hash. So two records whose *only* link is a mistyped domain (e.g. `infitech.com` / `inftech.com`) with no name/address overlap are never proposed as a candidate pair, so they can't merge. This is the deferred "fuzzy domain for candidate generation" idea from decision #4 — a known recall gap, not yet implemented.
- **The review band is not persisted.** A borderline pair's `review` vs `no_merge` distinction exists only in the returned `PairDecision.reason`/`decision`; the running pipeline does not yet log or store it for offline threshold tuning (decision #11 describes the intent; the log itself is future work).
