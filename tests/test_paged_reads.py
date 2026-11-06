"""List/timeline reads are bounded in SQL and status counts use one query (issue #11).

No database is available in tests, so `db._conn` is replaced with a fake
that records each statement and serves an in-memory table, honouring the
bound LIMIT/OFFSET parameters.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from render_engine_pg_cms import db
from render_engine_pg_cms.config import Config, ContentType

BASE = datetime(2024, 1, 1)


def _rows(n: int, step: int, id_base: int) -> list[dict]:
    # Some rows share a date and some have no date, to exercise tiebreakers.
    out = []
    for i in range(n):
        date = None if i % 7 == 0 else BASE + timedelta(hours=(i // 2) * step)
        out.append({"id": id_base + i, "date": date, "draft": False})
    return out


TABLES = {
    "blog": _rows(23, 5, 1),
    "microblog": _rows(41, 3, 1),
    "notes": _rows(9, 11, 1),
}


def _sorted(rows):
    return sorted(
        rows,
        key=lambda r: (r["date"] is not None, r["date"] or BASE, r["id"]),
        reverse=True,
    )


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
            self._result = [{"column_name": c} for c in ("id", "date", "draft")]
            return
        table = sql.split(" FROM ", 1)[1].split()[0]
        rows = TABLES[table]
        if "COUNT(" in sql:
            n = len(rows)
            self._result = [{"all": n, "published": n, "drafts": 0, "scheduled": 0}]
            return
        out = _sorted(rows)
        off = params.get("offset", 0)
        out = out[off:]
        if "limit" in params:
            out = out[: params["limit"]]
        self._result = [dict(r) for r in out]

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
        content_types={
            n: ContentType(name=n, table=n) for n in ("microblog", "blog", "notes")
        },
    )


def _selects(log):
    return [(s, p) for s, p in log if s.startswith("SELECT * FROM")]


def test_list_records_binds_limit_and_offset(log):
    ct = _cfg().content_types["blog"]
    rows = db.list_records(_cfg(), ct, status="published", limit=5, offset=10)
    sql, params = _selects(log)[-1]
    assert "LIMIT %(limit)s" in sql and "OFFSET %(offset)s" in sql
    assert params == {"limit": 5, "offset": 10}
    assert "ORDER BY date DESC NULLS LAST, id DESC" in sql
    # Values are bound, never interpolated into the statement.
    assert " 5" not in sql.split("LIMIT")[1] and "10" not in sql
    assert len(rows) == 5


def test_count_by_status_is_one_aggregate_query(log):
    ct = _cfg().content_types["blog"]
    counts = db.count_by_status(_cfg(), ct)
    counts_sql = [s for s, _ in log if "COUNT(" in s]
    assert len(counts_sql) == 1
    assert "FILTER (WHERE" in counts_sql[0]
    assert counts == {"all": 23, "published": 23, "drafts": 0, "scheduled": 0}


def test_timeline_pages_match_full_merge_without_gaps_or_dupes(log):
    cfg = _cfg()
    names = ["microblog", "blog", "notes"]
    full = db.list_timeline(cfg, names)
    total = len(full)
    assert total == sum(len(v) for v in TABLES.values())

    per = 7
    seen = []
    for start in range(0, total, per):
        page = db.list_timeline(cfg, names, limit=per, offset=start)
        assert page == full[start : start + per]
        seen.extend((r["_type"], r["id"]) for r in page)
    assert len(seen) == total
    assert len(set(seen)) == total


def test_timeline_reads_only_a_bounded_window_per_type(log):
    db.list_timeline(_cfg(), ["microblog", "blog", "notes"], limit=5, offset=10)
    selects = _selects(log)
    assert len(selects) == 3
    for sql, params in selects:
        assert "LIMIT %(limit)s" in sql
        assert params["limit"] == 15
