from app.db.filter_builder import build_where


def test_empty_returns_empty_clause():
    where, params = build_where([])
    assert where == ""
    assert params == {}


def test_single_filter():
    where, params = build_where([("a.id = :id", {"id": 7})])
    assert where == "WHERE a.id = :id"
    assert params == {"id": 7}


def test_multiple_filters_joined_with_and():
    where, params = build_where([
        ("a.id = :id", {"id": 7}),
        ("a.name ILIKE :q", {"q": "%foo%"}),
    ])
    assert where == "WHERE a.id = :id AND a.name ILIKE :q"
    assert params == {"id": 7, "q": "%foo%"}


def test_none_clauses_are_skipped():
    where, params = build_where([
        ("a.id = :id", {"id": 7}),
        None,
        ("a.x = :x", {"x": 1}),
    ])
    assert where == "WHERE a.id = :id AND a.x = :x"
    assert params == {"id": 7, "x": 1}
