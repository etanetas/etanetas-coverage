"""Shared helper for assembling `WHERE` clauses + parameter dicts.

Reduces duplication in endpoints that build SQL conditionally
(`hierarchy`, `audit`, `bulk._filter_addresses`, `addresses.list`,
`zones.list`).
"""
from collections.abc import Iterable

Clause = tuple[str, dict] | None


def build_where(clauses: Iterable[Clause]) -> tuple[str, dict]:
    """Combine a list of (sql_fragment, params) into a single WHERE clause.

    `None` entries are skipped — useful for conditional filters.
    """
    fragments: list[str] = []
    params: dict = {}
    for clause in clauses:
        if clause is None:
            continue
        sql, p = clause
        fragments.append(sql)
        params.update(p)
    if not fragments:
        return "", params
    return "WHERE " + " AND ".join(fragments), params
