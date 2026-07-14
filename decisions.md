# Record Reconciliation Decisions

This is a living record of our reasoning. We update it incrementally as we discuss the problem. An item belongs under **Decided** only after we have explicitly agreed on it. Each decision records *what* we decided and *why*, so the trade-offs are auditable later.

## Problem Understanding

We are given a list of company records (`name`, `address`, `website`) that are dirty: typos, abbreviations, missing fields, and tokens in a different order. We need to decide which records refer to the same real-world company, group them, and produce one merged (canonical) record per group with a confidence score. A group of one (a genuinely unmatched record) is valid.

Guiding principle throughout: **a wrong merge is more costly than a missed one.** Over-merging silently corrupts data and is hard to undo, so wherever a rule is a judgment call, we bias toward *not* merging.

---

## Decided

### 1. Website domain is the highest-quality identity field

- Of the three fields, the website domain is the strongest identity signal, so it carries the **highest weight** when combining evidence.
- An **exact** normalized-domain match is very strong positive evidence of the same company (~99% in the expected data).
- A domain *difference* is **not** automatically evidence of different companies — see decision #4 for the nuance.

### 2. Website (domain) normalization

Before comparing, normalize each website to its registrable domain:

- lowercase;
- remove the scheme (`http://`, `https://`);
- remove the `www.` prefix;
- remove **subdomains**, collapsing to the parent/registrable domain (e.g. `blog.acme.com` → `acme.com`);
- remove path, query string, and fragment;
- remove any port;
- remove a trailing slash.

So `https://www.acme.com/about`, `ACME.COM`, and `www.acme.com/` all compare as `acme.com`.

*Implementation caveat (not yet handled):* multi-part TLDs like `co.uk` — naive "strip everything but the last two labels" would wrongly reduce `acme.co.uk` to `co.uk`. Flagged for the implementation stage.

### 3. Normalization is per-field and **formatting-noise only**

- All comparisons operate on **normalized** strings, so "exact match" always means "exact after normalization."
- We normalize only **formatting noise** — the kind of variation that cannot, on its own, distinguish two different companies:
  - casing, surrounding/collapsing whitespace, punctuation;
  - legal-suffix variants (`Corp.`/`Corporation`/`Co.`, `Ltd`/`Limited`/`Limitd`);
  - token **reordering** (handles the assignment's "tokens in a different order").
- We deliberately do **not** do *semantic* normalization — i.e. we do **not** strip meaningful descriptor tokens like `Solutions`, `Systems`, `Group`, `Technologies`. Those tokens are treated as **signal**, not noise.

**Why this matters (the coupling):** our strictest merge rule (decision #7) lets a single field, if it matches *exactly*, carry a merge. "Exact" only means "exact after normalization," so the aggressiveness of normalization directly decides whether that rule is safe. Aggressive normalization would collapse different companies to the same canonical string — e.g. stripping `LLC` and `Solutions` makes `Initech LLC` and `Initech Solutions` both become `initech`, an "exact" match that would merge two possibly-different companies on a lone name. Restricting normalization to formatting noise keeps "exact = merge" honest.

### 4. Domain comparison has four states (revised)

A domain difference is ambiguous because a small difference has two opposite explanations that edit distance alone cannot tell apart:

- `infitech.com` vs `inftech.com` → a **typo** of one real domain → same company.
- `globex.io` vs `globed.com` → similar-but-real names → different companies.

**Both of these are exactly 1 edit apart in the registrable name.** No edit-distance threshold can label one "same" and the other "different" — so we do **not** try. A 1-edit difference is its own *ambiguous* state that stays neutral and defers to name+address, which is where the two cases actually diverge (globex/globed disagree on name+address; a real typo pair agrees). We compare domains **structurally** (registrable name + TLD) and classify into four states:

- **exact** (`a == b`) → strong "same company" signal (near-clincher) → scores 1.0.
- **variant** — same registrable name, different TLD (`initech.com` / `initech.co`) → likely one company owning multiple TLDs → mild positive, scores 0.8, does **not** veto.
- **near** — registrable names differ by a **single edit** (`globex`/`globed`, `infitech`/`inftech`) → **ambiguous**: excluded from the score (neither rewarded nor penalized) and does **not** veto. Name+address decide. This is the honest reading of "we can't tell a typo from a different company."
- **different** — registrable names differ by **more than one edit** (or clearly unrelated) → excluded from the score and is a **veto** candidate (see #10).

This resolves both hard cases correctly in the full pipeline without the classifier having to guess: `globex`/`globed` (`near`) never merge because name+address disagree; a genuine typo pair (`near`) merges because name+address agree; neither is wrongly credited (0.8) nor wrongly vetoed.

**Bonus use of fuzzy domains:** fuzzy domain similarity is valuable for **candidate generation** (finding pairs to compare, so a typo'd domain doesn't hide a true match) even though it is *not* trusted in the final merge decision. Recall tool vs. precision tool. (Deferred to the scaling/architecture stage.)

### 5. Name / address comparison: proportional fuzzy similarity

- Use **proportional** string similarity (percent of string matched), not raw count of matching characters, so one threshold works for both short and long names.
- Handle truncation/abbreviation by matching against the **shorter string** (containment / token-subset style), so extra tokens in the longer string don't unfairly penalize a real match (`Acme` inside `Acme Corporation`).
- **Very short tokens (1–3 characters) are treated as blank** — they are too short to match reliably and would match almost anything, so we refuse to base a match on them.

### 6. Scoring, missing fields, and confidence

- **Weighted sum over present fields only.** Each field has a weight reflecting how strongly it identifies a company (domain highest). Missing fields are **excluded from both the numerator and the denominator**, i.e. weights re-normalize over the fields actually present.
  - *Why:* this is what makes the "exact domain ≈ 99% same" belief hold mechanically — a pair should not be penalized for lacking an address when a strong signal (exact domain) is already present.
- **"Present" means present on *both* records.** If a field exists on only one record, there is nothing to compare; for that pair it is a missing field (it can still be *filled in* during merge, but it cannot *support* the match).
- **Confidence = score / perfect-score**, computed over the present fields. (Open refinement: confidence should probably also reflect *how much* evidence backed the decision — one field matching is less certain than three — see Open Questions.)

### 7. Field-aware, tiered merge rule for sparse records

The fewer fields two records share, the higher the bar to merge (a direct application of "a wrong merge is worse than a missed one"):

- **Three fields present** → each may be fuzzy, provided the combined score is high.
- **Two fields present (one missing)** → those two need a *really high* score.
- **One field present (two missing)** → that field must match **exactly** to merge.

And it is **field-aware**: an exact **domain** match is strong enough to carry a merge; a lone **name** or **address** match must be exact and is still weaker, because those fields collide (`Initech`/`Innotech`, `Globex`/`Globed` are near-misses that must *not* merge). A single fuzzy name/address match is never sufficient on its own.

### 8. Canonical merge: fill blanks from the most complete value

- When merging a group, fill each field from the most **complete** value available (e.g. `Acme Corporation` over `ACME`, `123 Main Street` over blank), producing the fullest record.
- This "longer/more complete wins" rule applies to **filling blanks**. For a genuine **conflicting non-empty** field (e.g. two different addresses under one exact domain), the precedence is: **most complete (longest) value wins → tie broken by first-seen (stable)**; the domain field additionally follows #10. Every raw value is retained in the audit table (#12), so the pick is auditable and reversible.

### 9. Grouping: plain union (connected components) of above-threshold pairs

- Any pair scoring above threshold is **unioned**; groups fall out as the connected components. No separate group-level over-merge guard.
- **Why this is safe here:** we deliberately put the precision control in **edge creation** (the strict, field-aware tiered rule #7), not in grouping. Every edge requires an *exact anchor* on a deciding field, and exact-normalized matches are effectively transitive — so a chain cannot travel along a weak link to drag in a stranger. Anything reachable through a hub must itself exact-match that hub. This lets grouping stay a "dumb" union while transitivity still can't over-merge unrelated companies.
- Trade-off, defended live: the residual break is two *truly different* companies sharing an exact name **and** exact address with no domain to separate them — no rule can split those (logged in "where it breaks").

### 10. Conflicting-domain veto (resolves the #4-meets-#7 seam)

When two records already match on **name and address** but both carry a **different, present** domain:

- Compare domains **structurally** (registrable name + TLD), never by raw string similarity — using the four states in #4.
- **variant** (same registrable name, different TLD) → **does not veto** → the pair merges.
- **near** (registrable names 1 edit apart) → **does not veto** — it is too ambiguous to block an otherwise-strong merge; name+address decide.
- **different** (registrable names >1 edit apart / clearly unrelated) → **veto** → do not merge, even against exact name+address.
- Direction matters: this is a **veto-release**, not a merge trigger. Domain state can only *block* an otherwise-justified merge; it never creates a merge on its own (a lone fuzzy domain never drags two records together — that would reopen #4).
- Honest caveat: only a clearly-`different` domain vetoes, so a genuine 1-edit typo (`near`) with exact name+address still merges (correct), while two unrelated companies (`different`) are blocked. Recorded in "where it breaks."

### 11. Concrete weights, similarity functions, thresholds, and confidence

Starting values, tuned to "a false merge costs more than a false split." All are calibratable against a labeled set (see tuning knobs below).

**Field similarity functions (0–1), on normalized strings; 1–3 char tokens dropped; "exact" = `sim == 1.0`:**

- `name_sim`, `address_sim` → **token-set** ratio (proportional), *not* pure shorter-string containment. Legal suffixes are already stripped in normalization (so `Acme` vs `Acme Corporation` → `acme` = 1.0), but a kept **descriptor** token must reduce the score (`Initech` vs `Initech Solutions` → ~0.6, not 1.0) — this is B2 enforced.
- `compare_domain` → **four states** (#4): `exact` → scores **1.0** (full weight); `variant` (same registrable name, different TLD) → scores **0.8** (mild positive — a company owning `.com`/`.co` is likely one entity); `near` (registrable names 1 edit apart) and `different` (>1 edit / unrelated) → **excluded from the score** (neutral). We *exclude* rather than give a low score on purpose: a low value in domain's high-weight slot would wrongly *penalize* the pair. Only a `different` domain becomes a hard **veto** inside the name+address-exact branch (#10); `near`/`different` are never scored.

**Weights (over scored fields, re-normalized when some are absent/excluded):** domain **0.50**, name **0.30**, address **0.20**.

**Decision procedure for a pair:** (1) veto check (#10); (2) weighted score over scored fields; (3) field-aware gate (fewer fields ⇒ higher bar, from #7):

| Scored fields | Auto-merge threshold |
|---|---|
| 3 | 0.82 |
| 2 | 0.90 |
| 1 | must be **exact**: domain exact → merge; name/address exact → **review** (they collide) |

- **Review band:** score within **0.05** below its threshold. Because the pipeline has **no human review queue** (#12), a borderline pair is **left unmerged** (the conservative default). The intent is to surface its score and reason for offline threshold tuning; today that distinction lives only in the returned `PairDecision` (`decision`/`reason`) and is **not yet persisted or logged** in the running pipeline (future work — see `edge-cases.md` §E). The band does not change merge output, only observability.

**Confidence:** pairwise = `score × 100`, capped by evidence (3 fields → 99, 2 → 95, 1 → 90). **Group confidence = the weakest edge** that formed the group.

**Behavior on the sample (validates the numbers):** groups `{1,2,3}`, `{4,5}`, `{6}`, `{7}`, `{8}`, `{9}` — Initech 6–7 (domain 0.8, name ~0.6, addr 1.0 → ~0.78, just under the 0.82 bar) lands in the **review band** rather than auto-merging or silently dropping; Initech/Innotech and Globex/Globed correctly stay apart.

**Tuning knobs (asymmetry-driven):** to cut over-merging → raise the 3-field threshold (0.82→0.85+), widen the review band, drop any variant credit; finer knobs are the per-field weights and the typo edit-distance. Presumes a small hand-labeled set to measure precision/recall.

---

### 12. Pipeline architecture (batch + incremental), no review queue

The system is a linear pipeline of independently testable stages:

**Ingest → Normalize → Generate candidates → Score & decide → Merge → continue.**

- No **review queue**: `Score & decide` makes a binary call (merge / don't). Borderline pairs are left unmerged (their `review` label is available in the `PairDecision` but not persisted — see #11), not held for a human.
- **Incremental by design:** each new record is processed against the existing set and unioned into an existing group (or forms a new one), without re-running the whole batch. Batch mode is the same mechanism applied record-by-record over a snapshot (or index-then-query).

**Group-as-single-entity model:**

- A group is represented by **one canonical record** (built with the merge algorithm, #8/#11). The canonical is the only entry in the active/searchable set — **one entry per group**.
- A separate **audit/log table** stores every raw row merged into a group with its group id. This is the provenance store — it satisfies the "make merges auditable/reversible" requirement and holds the conflict-resolution provenance parked in #8.
- **GET** returns the group's canonical record + confidence (audit rows available for explanation).
- New records **match against canonicals only**, never individual members.

**Candidate generation (the O(n²) escape), incremental — for each new record, query the existing canonicals via three methods and union the deduped matches:**

1. **Exact normalized domain** → hash lookup (high precision clinch).
2. **Exact normalized column** (name / address) → hash lookup.
3. **Trigram-based BM25**, top-K (configurable) → typo-tolerant fuzzy recall. Trigrams (not word tokens) so *character-level* typos (`Initech`/`Intech`, `inftech`/`infitech`) still surface — word-token BM25 would miss them. Implementation note: the query must **OR the query string's trigrams** (a single quoted FTS5 phrase only matches a contiguous substring, which is *not* typo-tolerant), and both the stored candidate keys and the query use the **same deep normalization** as scoring (`normalize_name`/`normalize_address`) — otherwise the exact-match candidate branches silently never fire.

- Candidates from the three methods are **deduped into a set**; each maps to its current group; the new record is scored **per matched group** (= per matched canonical).
- **Union the new record with every group that has a passing edge.** Matching ≥2 groups **bridges** them into one (new evidence they were always the same); recompute the canonical. Bridging is safe for the same reason as #9 — every edge still clears the strict tiered rule (#7) and the domain veto (#10).
- **Index maintenance:** indexes hold one entry per group's canonical, so on any group change (new member or bridge) we remove the old canonical and add the recomputed one.
- **Bounded recall cost (where it breaks):** matching against the canonical (the most complete record, so usually *more* matchable) loses only a value that conflict resolution **discarded** — e.g. the losing domain of an `initech.com`/`.co` merge; a later record with that discarded value scores as a 0.8 variant instead of an exact clinch. Rare and small. The audit table retains all raw values, so indexing them for candidate-generation (while still scoring at group level) is a future recall lever.

### 13. Backend & tech stack

- **FastAPI** app exposing add-record (incremental), batch-reconcile, and group-read endpoints (batch = the incremental path in a loop, one code path).
- **SQLite, file-backed** (not `:memory:`) so data survives restarts. The same code can point at `:memory:` for tests. Enable **WAL mode** (`PRAGMA journal_mode=WAL`) for better concurrent reads under FastAPI.
- **Division of labor:**
  - *SQLite owns storage + candidate generation* — canonical table, audit table, indexed columns for exact domain/name/address lookups, and an **FTS5 virtual table with `tokenize='trigram'`** + `bm25()` for the typo-tolerant fuzzy top-K (native, so no separate BM25 dependency).
  - *Python owns the algorithm* — normalization, per-pair scoring/decision (#4/#7/#10/#11), **union-find** grouping (persisted as a `group_id` column, since SQLite doesn't do connected components), and the canonical merge (#8).
- **Caveats banked for implementation:**
  - FTS5 must be compiled into the `sqlite3` build, and the **trigram tokenizer needs SQLite ≥ 3.34** — verify at startup, don't assume.
  - Use a **single shared connection** with `check_same_thread=False` (guarded by a lock) or a shared-cache URI, because FastAPI may access the DB from multiple threads.
  - `bm25()` returns a **negated** score (more negative = better) when reading top-K.

---

## Open Questions / Not Yet Decided

- **Can multiple distinct companies legitimately share one domain** (subsidiaries/branches)? We currently treat exact domain as ~99% same; noted as a residual risk (a "where it breaks" item, not a blocker).
