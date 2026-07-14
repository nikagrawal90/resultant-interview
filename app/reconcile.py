import threading
from app.normalize import normalize_record
from app.scoring import score_pair
from app.merge import build_canonical
from app.grouping import UnionFind
from app.models import NormalizedRecord, RawRecord
from app.config import BM25_TOP_K

class Reconciler:
    def __init__(self, store):
        self.store = store
        self.uf = UnionFind()
        self.members: dict[int, list[NormalizedRecord]] = {}   # group_id -> normalized members
        self.confidences: dict[int, int] = {}                   # group root -> confidence
        self._next_id = 1
        self._lock = threading.Lock()

    def _canonical_as_norm(self, c):
        return normalize_record(RawRecord(id=f"g{c.group_id}", name=c.name,
                                          address=c.address, website=c.domain))

    def add_record(self, raw):
        with self._lock:
            nr = normalize_record(raw)
            cand_ids = self.store.candidate_group_ids(nr.name, nr.address, nr.domain, BM25_TOP_K)

            merge_edges = {}                      # root -> min edge confidence into that group
            for gid in cand_ids:
                canon = self.store.get_canonical(gid)
                if not canon:
                    continue
                d = score_pair(nr, self._canonical_as_norm(canon))
                if d.decision == "merge":
                    root = self.uf.find(gid)
                    merge_edges[root] = min(merge_edges.get(root, 100), d.confidence)
            merge_roots = set(merge_edges)

            if not merge_roots:
                gid = self._next_id
                self._next_id += 1
                self.uf.add(gid)
                self.members[gid] = [nr]
                self.confidences[gid] = 100
                root = gid
            else:
                root = min(merge_roots)
                for other in merge_roots:
                    self.uf.union(root, other)
                root = self.uf.find(root)
                merged = [nr]
                for r in merge_roots:                 # gather members of every bridged group
                    merged += self.members.pop(r, [])
                self.members[root] = merged
                new_conf = min(list(merge_edges.values()) +
                                [self.confidences.pop(r, 100) for r in merge_roots])
                self.confidences[self.uf.find(root)] = new_conf
                for r in merge_roots:                 # drop stale canonicals from the store/index
                    if r != root:
                        self.store.delete_canonical(r)

            root = self.uf.find(root)
            members = self.members[root]
            conf = self.confidences[root]
            canon = build_canonical(root, members, conf)
            self.store.upsert_canonical(canon)
            self.store.add_audit(canon.group_id, raw)
            return canon.group_id

    def reconcile_batch(self, raws):
        for raw in raws:
            self.add_record(raw)
        return self.store.all_canonicals()
