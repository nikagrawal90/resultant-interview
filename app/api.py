import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.store import Store
from app.reconcile import Reconciler
from app.models import RawRecord

app = FastAPI(title="Record Reconciliation")
# File-backed and durable by default; override with RECONCILIATION_DB (tests use an in-memory DB).
_store = Store(os.environ.get("RECONCILIATION_DB", "file:reconciliation.db"))
_store.init_schema()
_recon = Reconciler(_store)

class RecordIn(BaseModel):
    id: str
    name: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    source: Optional[str] = None

class BatchIn(BaseModel):
    records: list[RecordIn]

def _raw(r: RecordIn) -> RawRecord:
    return RawRecord(id=r.id, name=r.name, address=r.address, website=r.website, source=r.source)

@app.post("/records")
def add_record(r: RecordIn):
    gid = _recon.add_record(_raw(r))
    return _store.get_canonical(gid)

@app.post("/reconcile")
def reconcile(batch: BatchIn):
    _recon.reconcile_batch([_raw(r) for r in batch.records])
    return _store.all_canonicals()

@app.get("/groups")
def all_groups():
    return _store.all_canonicals()

@app.get("/groups/{group_id}")
def get_group(group_id: int):
    c = _store.get_canonical(group_id)
    if not c:
        raise HTTPException(404, "group not found")
    return c
