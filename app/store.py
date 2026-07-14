# app/store.py
import sqlite3
from app.models import CanonicalRecord, RawRecord
from app.normalize import normalize_name, normalize_address

class Store:
    def __init__(self, db_path):
        uri = db_path.startswith("file:")
        self.con = sqlite3.connect(db_path, uri=uri, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")

    def init_schema(self):
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS canonical (
                group_id INTEGER PRIMARY KEY,
                name TEXT, address TEXT, domain TEXT,
                norm_name TEXT, norm_address TEXT,
                confidence INTEGER, member_ids TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_domain ON canonical(domain);
            CREATE INDEX IF NOT EXISTS ix_name ON canonical(norm_name);
            CREATE INDEX IF NOT EXISTS ix_address ON canonical(norm_address);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER, raw_id TEXT,
                name TEXT, address TEXT, website TEXT
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS canonical_fts
                USING fts5(text, group_id UNINDEXED, tokenize='trigram');
        """)
        self.con.commit()

    def upsert_canonical(self, c):
        self.delete_canonical(c.group_id)
        self.con.execute(
            "INSERT INTO canonical VALUES (?,?,?,?,?,?,?,?)",
            (c.group_id, c.name, c.address, c.domain,
             normalize_name(c.name), normalize_address(c.address),
             c.confidence, ",".join(c.member_ids)),
        )
        fts_text = f"{normalize_name(c.name)} {normalize_address(c.address)}".strip()
        self.con.execute(
            "INSERT INTO canonical_fts(text, group_id) VALUES (?,?)",
            (fts_text, c.group_id),
        )
        self.con.commit()

    def delete_canonical(self, group_id):
        self.con.execute("DELETE FROM canonical WHERE group_id=?", (group_id,))
        self.con.execute("DELETE FROM canonical_fts WHERE group_id=?", (group_id,))
        self.con.commit()

    def get_canonical(self, group_id):
        row = self.con.execute("SELECT * FROM canonical WHERE group_id=?", (group_id,)).fetchone()
        return _row_to_canonical(row) if row else None

    def all_canonicals(self):
        return [_row_to_canonical(r) for r in self.con.execute("SELECT * FROM canonical")]

    def add_audit(self, group_id, raw):
        self.con.execute(
            "INSERT INTO audit(group_id, raw_id, name, address, website) VALUES (?,?,?,?,?)",
            (group_id, raw.id, raw.name, raw.address, raw.website),
        )
        self.con.commit()

    def candidate_group_ids(self, name, address, domain, top_k):
        # name/address/domain must already be normalized (as produced by app.normalize).
        ids = set()
        if domain:
            ids |= {r["group_id"] for r in self.con.execute(
                "SELECT group_id FROM canonical WHERE domain=?", (domain,))}
        if name:
            ids |= {r["group_id"] for r in self.con.execute(
                "SELECT group_id FROM canonical WHERE norm_name=?", (name,))}
        if address:
            ids |= {r["group_id"] for r in self.con.execute(
                "SELECT group_id FROM canonical WHERE norm_address=?", (address,))}
        text = f"{name} {address}".strip()
        tris = _trigrams(text)
        if tris:
            match = " OR ".join('"' + t.replace('"', '""') + '"' for t in tris)
            ids |= {r["group_id"] for r in self.con.execute(
                "SELECT group_id FROM canonical_fts WHERE canonical_fts MATCH ? "
                "ORDER BY bm25(canonical_fts) LIMIT ?", (match, top_k))}
        return ids

def _trigrams(s):
    s = s.strip()
    return {s[i:i+3] for i in range(len(s) - 2)}

def _row_to_canonical(r):
    return CanonicalRecord(
        group_id=r["group_id"], name=r["name"], address=r["address"], domain=r["domain"],
        confidence=r["confidence"], member_ids=r["member_ids"].split(",") if r["member_ids"] else [],
    )
