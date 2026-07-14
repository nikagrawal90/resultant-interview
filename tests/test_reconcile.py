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
    assert len(groups) == 6                        # exactly six groups, no strays/dupes
    assert ["1", "2", "3"] in groups
    assert ["4", "5"] in groups
    assert ["6"] in groups and ["7"] in groups    # Initech pair left separate (review band)
    assert ["8"] in groups and ["9"] in groups
    assert all(c.confidence > 0 for c in canon)     # weakest-edge confidence, never 0
    by_members = {tuple(sorted(c.member_ids, key=int)): c.confidence for c in canon}
    assert by_members[("1", "2", "3")] == 95        # pinned to actual weakest-edge value


def test_new_record_bridges_two_groups():
    store = Store("file:recon_bridge?mode=memory&cache=shared")
    store.init_schema()
    r = Reconciler(store)

    # A: domain-only -> its own group
    r.add_record(RawRecord(id="A", name=None, address=None, website="zeta.com"))
    # B: name+address-only -> must NOT merge with A (no comparable field in common)
    r.add_record(RawRecord(id="B", name="Zeta Industries", address="10 River Road", website=None))
    assert len(store.all_canonicals()) == 2

    # C: all three fields -> exact domain match to A, exact name+address match to B -> bridges both
    r.add_record(RawRecord(id="C", name="Zeta Industries", address="10 River Road", website="zeta.com"))
    canon = store.all_canonicals()
    assert len(canon) == 1
    assert set(canon[0].member_ids) == {"A", "B", "C"}
    assert canon[0].confidence > 0   # weakest-edge confidence, not min-of-all-pairs (was 0)
