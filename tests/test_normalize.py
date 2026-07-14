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
