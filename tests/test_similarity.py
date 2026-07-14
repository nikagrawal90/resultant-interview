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
