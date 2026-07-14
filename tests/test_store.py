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
