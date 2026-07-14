from app.models import NormalizedRecord, CanonicalRecord

def _pick_longest(values):
    # values in member (first-seen) order; longest wins, tie -> first-seen
    best = ""
    for v in values:
        if v and len(v) > len(best):
            best = v
    return best

def build_canonical(group_id, members, confidence):
    names = [m.raw.name or "" for m in members]
    addrs = [m.raw.address or "" for m in members]
    domains = [m.domain for m in members]        # normalized registrable domain
    return CanonicalRecord(
        group_id=group_id,
        name=_pick_longest(names),
        address=_pick_longest(addrs),
        domain=_pick_longest(domains),
        confidence=confidence,
        member_ids=[m.id for m in members],
    )
