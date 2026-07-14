# tests/test_store.py
import sqlite3, pytest
from app.store import Store
from app.models import CanonicalRecord, RawRecord
from app.normalize import normalize_name, normalize_address

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

def test_exact_norm_name_candidate(store):
    # Store and query normalizations must agree: "Acme Corporation" and "Acme Corp."
    # both deep-normalize to "acme", so the norm_name exact branch matches.
    store.upsert_canonical(CanonicalRecord(2, "Acme Corporation", "123 Main St", "acme.com", 99, ["1"]))
    q = normalize_name("Acme Corp.")
    assert q == "acme"
    assert 2 in store.candidate_group_ids(name=q, address="", domain="", top_k=5)

def test_trigram_typo_candidate_fts_only(store):
    # Both name AND address carry a 1-char typo, so NEITHER exact branch can match.
    # Only the trigram-OR BM25 FTS path can surface the group.
    store.upsert_canonical(CanonicalRecord(1, "Initech Solutions", "1 Tech Plaza", "initech.com", 99, ["6"]))
    # Sanity: the typo'd query differs from the stored deep-normalized keys.
    assert normalize_name("Initech Solutions") == "initech solutions"
    assert normalize_address("1 Tech Plaza") == "1 tech plaza"
    typo_name, typo_addr = "initech solutuons", "1 tech plaze"
    assert typo_name != "initech solutions"
    assert typo_addr != "1 tech plaza"
    result = store.candidate_group_ids(name=typo_name, address=typo_addr, domain="", top_k=5)
    assert 1 in result
