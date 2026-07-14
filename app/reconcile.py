from app.normalize import normalize_record
from app.scoring import score_pair
from app.merge import build_canonical
from app.grouping import UnionFind
from app.models import NormalizedRecord, CanonicalRecord
from app.config import BM25_TOP_K

class Reconciler:
    def __init__(self, store):
        self.store = store
        self.uf = UnionFind()
        self.members: dict[int, list[NormalizedRecord]] = {}   # group_id -> normalized members
        self._next_id = 1

    def _canonical_as_norm(self, c):
        from app.models import RawRecord
        return normalize_record(RawRecord(id=f"g{c.group_id}", name=c.name,
                                          address=c.address, website=c.domain))

    def add_record(self, raw):
        nr = normalize_record(raw)
        cand_ids = self.store.candidate_group_ids(nr.name, nr.address, nr.domain, BM25_TOP_K)

        merge_roots = set()
        for gid in cand_ids:
            canon = self.store.get_canonical(gid)
            if canon and score_pair(nr, self._canonical_as_norm(canon)).decision == "merge":
                merge_roots.add(self.uf.find(gid))

        if not merge_roots:
            gid = self._next_id
            self._next_id += 1
            self.uf.add(gid)
            self.members[gid] = [nr]
            root = gid
        else:
            root = min(merge_roots)
            self.uf.add(root)
            for other in merge_roots:
                self.uf.union(root, other)
            root = self.uf.find(root)
            merged = [nr]
            for r in merge_roots:                 # gather members of every bridged group
                merged += self.members.pop(r, [])
            self.members[root] = merged
            for r in merge_roots:                 # drop stale canonicals from the store/index
                if r != root:
                    self.store.delete_canonical(r)

        members = self.members[self.uf.find(root)]
        conf = self._group_confidence(members)
        canon = build_canonical(self.uf.find(root), members, conf)
        self.store.upsert_canonical(canon)
        self.store.add_audit(canon.group_id, raw)
        return canon.group_id

    def _group_confidence(self, members):
        if len(members) == 1:
            return 100
        worst = 100
        for i in range(len(members)):             # weakest pairwise edge in the group
            for j in range(i + 1, len(members)):
                worst = min(worst, score_pair(members[i], members[j]).confidence)
        return worst

    def reconcile_batch(self, raws):
        for raw in raws:
            self.add_record(raw)
        return self.store.all_canonicals()
