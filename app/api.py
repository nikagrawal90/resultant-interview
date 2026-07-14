import csv
import io
import os
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from app.store import Store
from app.reconcile import Reconciler
from app.models import RawRecord

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

_ID_HEADERS = {"id", "#"}
_FIELD_HEADERS = {"name", "address", "website"}

def _clean_cell(v):
    if v is None:
        return None
    v = v.strip()
    return v if v else None

def _parse_csv_records(text: str) -> list[RawRecord]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []

    # Map headers case-insensitively to canonical field names.
    header_map = {}          # canonical field -> actual header string
    id_header = None
    for h in reader.fieldnames:
        key = h.strip().lower()
        if key in _ID_HEADERS:
            id_header = h
        elif key in _FIELD_HEADERS:
            header_map[key] = h

    records = []
    for i, row in enumerate(reader, start=1):
        rid = None
        if id_header is not None:
            rid = _clean_cell(row.get(id_header))
        if rid is None:
            rid = str(i)
        records.append(RawRecord(
            id=rid,
            name=_clean_cell(row.get(header_map.get("name"))),
            address=_clean_cell(row.get(header_map.get("address"))),
            website=_clean_cell(row.get(header_map.get("website"))),
        ))
    return records

def create_app(db_uri: str) -> FastAPI:
    app = FastAPI(title="Record Reconciliation")
    store = Store(db_uri)
    store.init_schema()
    recon = Reconciler(store)
    app.state.store = store
    app.state.recon = recon

    @app.post("/records")
    def add_record(r: RecordIn):
        gid = recon.add_record(_raw(r))
        return store.get_canonical(gid)

    @app.post("/reconcile")
    def reconcile(batch: BatchIn):
        recon.reconcile_batch([_raw(r) for r in batch.records])
        return store.all_canonicals()

    @app.get("/groups")
    def all_groups():
        return store.all_canonicals()

    @app.get("/groups/{group_id}")
    def get_group(group_id: int):
        c = store.get_canonical(group_id)
        if not c:
            raise HTTPException(404, "group not found")
        return c

    @app.post("/reconcile/csv")
    async def reconcile_csv(file: UploadFile):
        raw_bytes = await file.read()
        try:
            text = raw_bytes.decode("utf-8")
            records = _parse_csv_records(text)
        except (UnicodeDecodeError, csv.Error):
            raise HTTPException(400, "invalid or unparseable CSV")
        recon.reconcile_batch(records)
        return store.all_canonicals()

    @app.get("/export.csv")
    def export_csv():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["name", "address", "website"])
        for c in store.all_canonicals():
            writer.writerow([c.name, c.address, c.domain])
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="reconciled.csv"'},
        )

    return app

# File-backed and durable by default; override with RECONCILIATION_DB (tests use an in-memory DB).
app = create_app(os.environ.get("RECONCILIATION_DB", "file:reconciliation.db"))
