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
