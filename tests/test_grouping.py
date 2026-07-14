from app.grouping import UnionFind

def test_transitive_grouping():
    uf = UnionFind()
    for x in ["1", "2", "3", "9"]:
        uf.add(x)
    uf.union("1", "2")       # name+address
    uf.union("1", "3")       # domain
    groups = {frozenset(v) for v in uf.groups().values()}
    assert frozenset({"1", "2", "3"}) in groups
    assert frozenset({"9"}) in groups
