# Record Reconciliation

Given dirty company records (`name`, `address`, `website` — typos, abbreviations,
missing fields, reordered tokens), group the records that refer to the same
real-world company and produce one merged (canonical) record per group with a
confidence score. The approach: normalize formatting noise only, generate
candidate pairs cheaply, score each pair on present fields with domain
weighted highest, apply a field-aware tiered gate (fewer shared fields ⇒
higher bar) plus a conflicting-domain veto, union passing pairs into groups,
and merge each group by taking the most complete value per field. Guiding
principle throughout: **a wrong merge is costlier than a missed one**, so
every judgment call biases toward not merging.

## Run it

```bash
python -m venv .venv
./.venv/bin/pip install -r requirements.txt

# tests
./.venv/bin/python -m pytest -q

# API
./.venv/bin/uvicorn app.api:app --reload
```

Storage is SQLite, file-backed by default (`reconciliation.db` in the working
directory), so the canonical and audit tables persist on disk. Set
`RECONCILIATION_DB` to point elsewhere, e.g. an in-memory shared-cache DB for
tests (`file:test?mode=memory&cache=shared`) — that's how the test suite
isolates itself from the on-disk file.

**Single-session caveat:** the `Reconciler` holds its grouping state
(union-find, per-group members, next-id) **in memory** and does not rehydrate
it from the DB on startup. So the service is safe for one running process, but
**restarting against a populated DB is not safe** — the first write after a
restart can overwrite existing groups. Rehydrating on startup from the audit
table is future work (see `edge-cases.md` §E).

Example requests once the server is running (`/reconcile` expects
`{"records": [...]}` — `data/sample.json` is a bare array, so wrap it):

```bash
curl -X POST localhost:8000/reconcile \
  -H 'Content-Type: application/json' \
  -d "{\"records\": $(cat data/sample.json)}"

curl localhost:8000/groups
```

(`POST /records` adds one record incrementally; `GET /groups/{id}` reads a
single group's canonical.)

**CSV in / CSV out.** Ingest a CSV file and export the reconciled result as a
three-column CSV:

```bash
# Ingest a CSV (headers: name, address, website; optional id/# column).
# Missing values = empty cells. Ids are auto-assigned by row if no id column.
curl -X POST localhost:8000/reconcile/csv -F "file=@data/sample.csv"

# Export the grouped result — one row per group, columns: name,address,website.
curl localhost:8000/export.csv -o reconciled.csv
```

Ingesting `data/sample.csv` (the 9 sample rows) yields the six groups; the
export collapses them to six rows (Acme 1-3 and Globex 4-5 merged).

## Pipeline

`Ingest → Normalize → Generate candidates → Score & decide → Union (merge groups) → Recompute canonical`

- **Normalize** — formatting noise only (case, punctuation, whitespace, legal
  suffixes, token order, domain → registrable domain). Meaningful descriptor
  tokens (`Solutions`, `Systems`, `Group`) are kept as signal, not stripped.
- **Candidate generation** — SQLite exact-hash lookups on normalized
  domain/name/address, plus an FTS5 trigram index (`tokenize='trigram'`)
  over **name and address** for typo-tolerant fuzzy recall. Domain candidate
  generation is **exact-match only** — the trigram index does not cover the
  domain field (fuzzy-domain recall is deferred, decision #4).
- **Score & decide** — weighted sum over the fields present *on both*
  records (domain 0.50, name 0.30, address 0.20; missing fields drop out of
  both numerator and denominator), then a field-aware tiered threshold and a
  conflicting-domain veto.
- **Union** — any pair that clears the gate is unioned; groups are the
  connected components. Precision lives entirely in edge creation, so the
  union step itself stays a "dumb" union-find.
- **Merge** — canonical record per group: each field takes the most complete
  (longest) value, ties broken by first-seen; every raw row is retained in an
  audit table for provenance.

## Key decisions & what was rejected

Full reasoning, with rejected alternatives and *why*, is in
[`decisions.md`](decisions.md). Highlights:

- **Cost asymmetry drives every judgment call**: a false merge is assumed
  worse than a false split, so ambiguous cases default to *not* merging.
- **Domain gets a 4-state structural comparison** (`exact` / `variant`
  same-name-different-TLD / `near` 1-edit-apart / `different`), not raw
  string similarity. Rejected: edit-distance/fuzzy-ratio scoring for domains
  — `globex.io` vs `globed.com` and `infitech.com` vs `inftech.com` are both
  exactly one edit apart, yet one pair is different companies and the other
  is a typo of the same company. No distance threshold can separate them, so
  a 1-edit domain difference is treated as *ambiguous* and deferred to
  name+address rather than guessed.
- **Normalization strips formatting noise only**, never descriptor tokens.
  Rejected: stripping words like `Solutions`/`Systems` — that would make
  `Initech LLC` and `Initech Solutions` both normalize to `initech`, an
  "exact" match, which is unsafe because the tiered rule lets a single exact
  field carry a merge.
- **Weighted score over present fields only**, with weights re-normalized
  over whatever fields both records actually have — so an exact-domain match
  isn't penalized just because one record lacks an address.
- **Field-aware, tiered merge rule**: 3 fields present can each be fuzzy if
  the combined score clears 0.82; 2 fields need ≥0.90; 1 field must match
  *exactly*, and a lone exact domain is trusted more than a lone exact
  name/address (names/addresses collide near-misses like `Initech`/
  `Innotech`).
- **Plain union (connected components)** for grouping, with no separate
  group-level over-merge guard. Rejected: guarding at the grouping level —
  redundant, because every edge already requires an exact anchor on a
  deciding field (near-transitive), so a weak chain can't smuggle in a
  stranger. Precision is pushed entirely into edge creation instead.
- **Conflicting-domain veto**: when name+address already match but domains
  differ and are structurally `different` (not `variant`/`near`), the merge
  is blocked even against exact name+address.
- **SQLite + FTS5 trigram** for typo-tolerant candidate generation (recall
  tool), kept separate from the scoring stage (precision tool) — fuzzy
  domain similarity is useful for finding candidates but never trusted for
  the merge decision itself.

## Where it breaks

Honest limitations, detailed in [`edge-cases.md`](edge-cases.md) §E:

- Two genuinely different companies sharing an **exact name and exact
  address with no domain** to separate them will merge — no field is left to
  tell them apart.
- The conflicting-domain veto leans on a fuzzy notion (1-edit-apart =
  ambiguous) inside the name+address-exact branch; defensible only because
  that scope is narrow.
- **Subsidiaries/branches sharing one real domain** would over-merge, since
  an exact domain match is treated as ~99% "same company."
- **Confidence can read over-optimistically when few fields are present** —
  matching on 1 of 1 available fields is inherently less certain than
  matching on 3 of 3, and the current confidence score doesn't fully account
  for that.
- **A record whose only link to its true match is a mistyped *domain*** (no
  name/address overlap) is never proposed as a candidate — the trigram index
  covers name/address only, so exact-domain lookup misses the typo and
  fuzzy-domain candidate generation is deferred (decision #4).

## Sample run

`data/sample.json` reconciled end-to-end (`app.reconcile.Reconciler.reconcile_batch`),
printed as `member_ids -> name | address | domain | confidence` (member ids
shown sorted for readability — the raw output emits them in merge order):

```
['1', '2', '3'] -> Acme Corporation | 123 Main Street | acme.com | conf 95
['4', '5'] -> Globex Incorporated | 500 Park Avenue, Suite 200 | globex.io | conf 99
['6'] -> Initech LLC | 1 Tech Plaza | initech.com | conf 100
['7'] -> Initech Solutions | 1 Tech Plz | initech.co | conf 100
['8'] -> Innotech | 9 Innovation Way | innotech.com | conf 100
['9'] -> Globed Systems | 77 River Rd | globed.com | conf 100
```

Six groups, as expected: the Acme trio merges transitively (rows 1–3),
Globex's two rows merge, and Initech/Initech Solutions/Innotech/Globed
Systems all correctly stay apart despite their near-miss names — Initech
(row 6, `.com`) and Initech Solutions (row 7, `.co`) land just under the
merge threshold (score ~0.78 vs. an 0.82 bar), so they are left **unmerged**
(the conservative default). The `review` distinction is available on the
returned `PairDecision` (`decision`/`reason`) but is **not yet
persisted/logged** in the running pipeline — future work.

## Tests

```
31 passed
```

Run with `./.venv/bin/python -m pytest -q`.
