"""List reads ship excerpts, not full post bodies, and tag lookups batch.

Complements tests/test_paged_reads.py: that file locks in the SQL LIMIT/OFFSET
bound, this one locks in the payload bound (content truncation) and the
batched tag loader that replaces per-row tag queries.

No database is available, so `db._conn` is replaced with a fake that models
the parts of the queries we care about: returning `content` and honouring
`LEFT(content, N)` plus `= ANY(ids)`.
"""

from __future__ import annotations

import pytest

from render_engine_pg_cms import db
from render_engine_pg_cms.config import Config, ContentType

BIG = "x" * 5000

TABLES = {
    "blog": [
        {"id": 1, "date": None, "draft": False, "content": BIG},
        {"id": 2, "date": None, "draft": False, "content": "short"},
    ],
    "microblog": [
        {"id": 1, "date": None, "draft": False, "content": BIG},
    ],
}

# blog_id -> tag names
TAGS = {1: ["python", "web"], 2: ["python"], 3: ["orphan"]}


class FakeCursor:
    def __init__(self, log):
        self.log = log
        self._result = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        params = params or {}
        self.log.append((sql, dict(params)))
        if "information_schema.columns" in sql:
            self._result = [
                {"column_name": c} for c in ("id", "date", "draft", "content")
            ]
            return
        if "tags.name" in sql:
            ids = list(params.get("ids") or [])
            self._result = [
                {"record_id": i, "name": name} for i in ids for name in TAGS.get(i, [])
            ]
            return
        table = sql.split(" FROM ", 1)[1].split()[0]
        rows = [dict(r) for r in TABLES[table]]
        if "LEFT(content" in sql:
            n = params["excerpt_chars"]
            for r in rows:
                if r.get("content"):
                    r["content"] = r["content"][:n]
        if "'' AS content" in sql:
            for r in rows:
                r["content"] = ""
        if "limit" in params:
            rows = rows[: params["limit"]]
        self._result = rows

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result[0] if self._result else None


class FakeConn:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return FakeCursor(self.log)


@pytest.fixture
def log(monkeypatch):
    calls: list = []
    monkeypatch.setattr(db, "_conn", lambda cfg: FakeConn(calls))
    db._table_columns_cache.clear()
    yield calls
    db._table_columns_cache.clear()


def _cfg() -> Config:
    return Config(
        connection_string="",
        content_types={n: ContentType(name=n, table=n) for n in ("blog", "microblog")},
    )


def _selects(log):
    return [(s, p) for s, p in log if s.startswith("SELECT") and " FROM " in s]


# --- content truncation -----------------------------------------------------


def test_bounded_read_truncates_content_in_sql(log):
    ct = _cfg().content_types["blog"]
    rows = db.list_records(_cfg(), ct, limit=10, excerpt_chars=100)
    sql, params = _selects(log)[-1]
    assert "LEFT(content, %(excerpt_chars)s)" in sql
    assert params["excerpt_chars"] == 100
    # Long body cut down, short body untouched, and the cut is flagged.
    by_id = {r["id"]: r for r in rows}
    assert by_id[1]["content"] == "x" * 100
    assert by_id[1]["_truncated"] is True
    assert by_id[2]["content"] == "short"
    assert by_id[2]["_truncated"] is False


def test_truncation_value_is_bound_not_interpolated(log):
    ct = _cfg().content_types["blog"]
    db.list_records(_cfg(), ct, limit=10, excerpt_chars=250)
    sql, _ = _selects(log)[-1]
    assert "250" not in sql


def test_unbounded_read_keeps_full_content(log):
    """limit=None is the internal/extraction path; it must not be excerpted."""
    ct = _cfg().content_types["blog"]
    rows = db.list_records(_cfg(), ct, limit=None, excerpt_chars=100)
    sql, _ = _selects(log)[-1]
    assert "LEFT(content" not in sql
    assert {r["id"]: r["content"] for r in rows}[1] == BIG
    assert all("_truncated" not in r for r in rows)


def test_no_excerpt_when_chars_none(log):
    ct = _cfg().content_types["blog"]
    db.list_records(_cfg(), ct, limit=10, excerpt_chars=None)
    sql, _ = _selects(log)[-1]
    assert "LEFT(content" not in sql


def test_omit_content_drops_body_without_binding_length(log):
    """The timeline renders no body for blog/notes, so the column is
    emptied server-side and no excerpt length is bound."""
    ct = _cfg().content_types["blog"]
    rows = db.list_records(_cfg(), ct, limit=10, omit_content=True)
    sql, params = _selects(log)[-1]
    assert sql.count("'' AS content") == 1
    assert "LEFT(content" not in sql
    assert "excerpt_chars" not in params
    assert all(r["content"] == "" for r in rows)


def test_omit_content_ignored_when_unbounded(log):
    """limit=None is the internal/extraction path; it must keep full rows
    even when a caller passes omit_content."""
    ct = _cfg().content_types["blog"]
    rows = db.list_records(_cfg(), ct, limit=None, omit_content=True)
    sql, _ = _selects(log)[-1]
    assert "'' AS content" not in sql
    assert {r["id"]: r["content"] for r in rows}[1] == BIG


def test_timeline_omits_only_named_types(log):
    cfg = _cfg()
    db.list_timeline(
        cfg,
        ["blog", "microblog"],
        limit=5,
        omit_content_types={"blog"},
    )
    omitted = [s for s, _ in _selects(log) if "'' AS content" in s]
    truncated = [s for s, _ in _selects(log) if "LEFT(content" in s]
    assert len(omitted) == 1  # blog
    assert truncated == []    # microblog keeps its body (the post *is* the text)


def test_timeline_passes_excerpt_through_to_each_type(log):
    cfg = _cfg()
    rows = db.list_timeline(
        cfg,
        ["blog", "microblog"],
        limit=5,
        excerpt_chars=50,
    )
    selects = [s for s, _ in _selects(log) if "LEFT(content" in s]
    assert len(selects) == 2  # one per configured type
    for r in rows:
        assert len(r["content"]) <= 50


def test_build_list_query_matches_list_records_sql(log):
    """The diagnostic script builds SQL via build_list_query; list_records
    must issue exactly that statement, or the measurements are fiction."""
    ct = _cfg().content_types["blog"]
    with db._conn(_cfg()) as conn, conn.cursor() as cur:
        cols = db._table_columns(cur, ct.table)
    sql, params, truncated = db.build_list_query(
        cols, ct.table, status="all", limit=10, offset=5, excerpt_chars=100,
    )
    assert truncated is True
    db.list_records(_cfg(), ct, status="all", limit=10, offset=5, excerpt_chars=100)
    ran_sql, ran_params = _selects(log)[-1]
    assert ran_sql == sql
    assert ran_params == params


def test_build_list_query_unbounded_has_no_excerpt(log):
    ct = _cfg().content_types["blog"]
    with db._conn(_cfg()) as conn, conn.cursor() as cur:
        cols = db._table_columns(cur, ct.table)
    sql, params, truncated = db.build_list_query(
        cols, ct.table, limit=None, excerpt_chars=None,
    )
    assert truncated is False
    assert "LEFT(content" not in sql
    assert "LIMIT" not in sql
    assert params == {}


def test_build_list_query_omit_matches_list_records_sql(log):
    """scripts/explain_timeline.py builds the `omit` case via
    build_list_query; list_records(omit_content=True) must run the same
    statement so the measurement is of the real app query."""
    ct = _cfg().content_types["blog"]
    with db._conn(_cfg()) as conn, conn.cursor() as cur:
        cols = db._table_columns(cur, ct.table)
    sql, params, _truncated = db.build_list_query(
        cols, ct.table, status="all", limit=10, offset=5,
        excerpt_chars=600, omit_content=True,
    )
    assert "'' AS content" in sql
    assert "excerpt_chars" not in params  # length unused when body is dropped
    db.list_records(
        _cfg(), ct, status="all", limit=10, offset=5,
        excerpt_chars=600, omit_content=True,
    )
    ran_sql, ran_params = _selects(log)[-1]
    assert ran_sql == sql
    assert ran_params == params


# --- batched tags -----------------------------------------------------------


def test_tags_for_records_is_a_single_query(log):
    ct = _cfg().content_types["blog"]
    ct.join_insert = (
        "INSERT INTO blog_tags (blog_id, tag_id) VALUES (%(blog_id)s, %(tag_id)s)",
        [],
    )
    out = db.tags_for_records(_cfg(), ct, [1, 2, 3])
    tag_queries = [s for s, _ in log if "tags.name" in s]
    assert len(tag_queries) == 1
    assert out == {1: ["python", "web"], 2: ["python"], 3: ["orphan"]}


def test_tags_for_records_omits_ids_without_tags(log):
    """An id with no tag rows is simply absent from the mapping."""
    ct = _cfg().content_types["blog"]
    ct.join_insert = ("INSERT INTO blog_tags (blog_id) VALUES (%(blog_id)s)", [])
    out = db.tags_for_records(_cfg(), ct, [1, 99])
    assert out == {1: ["python", "web"]}


def test_tags_for_records_short_circuits_without_tags(log):
    ct = _cfg().content_types["blog"]  # has_tags is False
    assert db.tags_for_records(_cfg(), ct, [1, 2]) == {}
    assert [s for s, _ in log if "tags.name" in s] == []


def test_tags_for_records_empty_ids_makes_no_query(log):
    ct = _cfg().content_types["blog"]
    ct.join_insert = ("INSERT INTO blog_tags (blog_id) VALUES (%(blog_id)s)", [])
    assert db.tags_for_records(_cfg(), ct, []) == {}
    assert [s for s, _ in log if "tags.name" in s] == []


def test_tags_for_records_binds_id_list(log):
    ct = _cfg().content_types["blog"]
    ct.join_insert = ("INSERT INTO blog_tags (blog_id) VALUES (%(blog_id)s)", [])
    db.tags_for_records(_cfg(), ct, [7, 8])
    sql, params = [x for x in log if "tags.name" in x[0]][-1]
    assert "= ANY(%(ids)s)" in sql
    assert params["ids"] == [7, 8]
    assert "7, 8" not in sql
