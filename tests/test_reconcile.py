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
    assert ["1", "2", "3"] in groups
    assert ["4", "5"] in groups
    assert ["6"] in groups and ["7"] in groups    # Initech pair left separate (review band)
    assert ["8"] in groups and ["9"] in groups
