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
    assert d.decision == "no_merge" and "veto" not in d.reason

def test_globex_globed_no_merge():
    d = score_pair(_n("4","Globex Inc","500 Park Ave","globex.io"),
                   _n("9","Globed Systems","77 River Rd","globed.com"))
    assert d.decision == "no_merge" and "veto" not in d.reason

def test_veto_blocks_exact_name_address_with_different_domain():
    d = score_pair(_n("a","Foo Bar","1 Main Street","foo.com"),
                   _n("b","Foo Bar","1 Main Street","zzzbar.com"))
    assert d.decision == "no_merge" and "veto" in d.reason

# --- n==1 (single scored field) tiered gate ---

def test_single_field_domain_only_exact_merges():
    # name & address absent on both -> only domain is scored (exact) -> merge
    d = score_pair(_n("1", None, None, "acme.com"),
                   _n("2", None, None, "acme.com"))
    assert d.decision == "merge" and "veto" not in d.reason

def test_single_field_name_only_exact_reviews():
    # address & domain absent on both -> only name is scored (exact) -> review (collides)
    d = score_pair(_n("1", "Acme Corporation", None, None),
                   _n("2", "ACME Corp", None, None))
    assert d.decision == "review"

def test_single_field_fuzzy_name_only_no_merge():
    # only name present on both, ~0.67 similar (non-exact) -> no_merge
    d = score_pair(_n("1", "Initech Solutions", None, None),
                   _n("2", "Initech Software", None, None))
    assert d.decision == "no_merge"

# --- near-domain does NOT veto ---

def test_near_domain_does_not_veto():
    # exact name + exact address, domains 1 edit apart in registrable name -> "near".
    # "near" is ambiguous and must NOT veto; name+address exact -> score 1.0 -> merge.
    d = score_pair(_n("a", "Foo Bar", "1 Main Street", "foo.com"),
                   _n("b", "Foo Bar", "1 Main Street", "fop.com"))
    assert d.decision == "merge" and "veto" not in d.reason
