import os
# Point the app at an isolated in-memory DB BEFORE importing it, so the test
# never touches the on-disk reconciliation.db (avoids cross-run state).
os.environ["RECONCILIATION_DB"] = "file:apitest?mode=memory&cache=shared"
from fastapi.testclient import TestClient
from app.api import app

def test_batch_then_get_groups():
    client = TestClient(app)
    rows = [
        {"id": "1", "name": "Acme Corporation", "address": "123 Main St", "website": "acme.com"},
        {"id": "3", "name": "ACME", "address": None, "website": "acme.com"},
    ]
    r = client.post("/reconcile", json={"records": rows})
    assert r.status_code == 200
    groups = client.get("/groups").json()
    assert any(set(g["member_ids"]) == {"1", "3"} for g in groups)
