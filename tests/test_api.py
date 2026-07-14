import csv
import io
import itertools
import os
# Point the app at an isolated in-memory DB BEFORE importing it, so the test
# never touches the on-disk reconciliation.db (avoids cross-run state).
os.environ["RECONCILIATION_DB"] = "file:apitest?mode=memory&cache=shared"
from fastapi.testclient import TestClient
from app.api import app, create_app

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


_db_counter = itertools.count()

def _fresh_client():
    db_uri = f"file:apitest_csv_{next(_db_counter)}?mode=memory&cache=shared"
    return TestClient(create_app(db_uri))

def test_reconcile_csv_ingest_produces_six_groups():
    client = _fresh_client()
    with open("data/sample.csv", "rb") as f:
        data = f.read()
    r = client.post("/reconcile/csv", files={"file": ("sample.csv", data, "text/csv")})
    assert r.status_code == 200

    groups = client.get("/groups").json()
    assert len(groups) == 6
    member_sets = [set(g["member_ids"]) for g in groups]
    assert {"1", "2", "3"} in member_sets
    assert {"4", "5"} in member_sets

def test_reconcile_csv_bad_encoding_returns_400():
    client = _fresh_client()
    bad = b"\xff\xfe\x00n\x00a\x00m\x00e"
    r = client.post("/reconcile/csv", files={"file": ("bad.csv", bad, "text/csv")})
    assert r.status_code == 400

def test_export_csv_round_trip():
    client = _fresh_client()
    with open("data/sample.csv", "rb") as f:
        data = f.read()
    r = client.post("/reconcile/csv", files={"file": ("sample.csv", data, "text/csv")})
    assert r.status_code == 200

    r = client.get("/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")

    rows = list(csv.reader(io.StringIO(r.text)))
    header, data_rows = rows[0], rows[1:]
    assert header == ["name", "address", "website"]
    assert len(data_rows) == 6
    websites = {row[2] for row in data_rows}
    assert "acme.com" in websites
    assert "globex.io" in websites
