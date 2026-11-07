"""The timing diagnostic attributes render time to connect vs query.

No database is available, so the diagnostic's `db` helpers are replaced with
fakes that record each phase call and can be made slow or to raise. The
diagnostic is loaded as a module from `scripts/` (it is a plain script, not
an importable package).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import psycopg
import pytest

from render_engine_pg_cms import db
from render_engine_pg_cms.config import Config, ContentType

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load_script(name: str):
    """Import scripts/<name>.py without requiring a scripts package."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


timing = _load_script("timing_diagnostic")


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def FakeConn(closed: list | None = None):
    class _Conn:
        def cursor(self):
            return FakeCursor()

        def close(self):
            if closed is not None:
                closed.append(True)

    return _Conn()


def _cfg() -> Config:
    return Config(
        connection_string="postgresql://user:s3cret@db.example:5432/site",
        content_types={
            n: ContentType(name=n, table=n) for n in ("microblog", "blog", "notes")
        },
    )


@pytest.fixture
def wired(monkeypatch):
    """Wire the diagnostic onto fake db helpers; return the call log."""
    calls: list[str] = []
    closed: list = []

    monkeypatch.setattr(timing, "load_config", _cfg)
    monkeypatch.setenv("CONNECTION_STRING", "postgresql://fake/db")
    monkeypatch.delenv("LIST_EXCERPT_CHARS", raising=False)

    monkeypatch.setattr(db, "page_conn", lambda cfg: (calls.append("connect"), FakeConn(closed))[1])
    monkeypatch.setattr(db, "_table_columns", lambda cur, table: (calls.append(f"cols:{table}"), set())[1])
    monkeypatch.setattr(
        db, "counts_by_status_for", lambda cfg, cts, conn=None: (calls.append("counts"), {})[1]
    )
    monkeypatch.setattr(
        db, "list_timeline", lambda cfg, types, **kw: (calls.append("list"), [])[1]
    )
    monkeypatch.setattr(
        db, "count_by_status", lambda cfg, ct, conn=None: (calls.append("counts"), {})[1]
    )
    monkeypatch.setattr(
        db, "list_records", lambda cfg, ct, **kw: (calls.append("list"), [])[1]
    )
    return calls, closed


def test_main_reports_every_phase_and_uses_one_connection(monkeypatch, wired, capsys):
    calls, closed = wired
    monkeypatch.setattr(sys, "argv", ["timing_diagnostic.py", "--repeat", "2"])

    rc = timing.main()

    out = capsys.readouterr().out
    assert rc == 0
    # Both page shapes were measured (index + the collection types).
    assert "index (timeline" in out
    assert "collection /c/" in out
    # Each pass: connect, then counts+list on the shared connection.
    assert calls.count("connect") >= 2
    assert "counts" in calls and "list" in calls
    # Every opened connection is closed even on the happy path.
    assert closed
    assert "connect=" in out and "queries=" in out


def test_report_attributes_dominant_phase(capsys):
    connect = timing.Phase("connect")
    counts = timing.Phase("counts")
    listing = timing.Phase("list")
    total = timing.Phase("total")
    connect.samples = [400.0, 420.0]
    counts.samples = [5.0, 6.0]
    listing.samples = [7.0, 8.0]
    total.samples = [412.0, 434.0]

    dominant = timing._report(
        {"label": "shape", "phases": [connect, counts, listing, total]}
    )

    out = capsys.readouterr().out
    assert dominant == "connect/handshake"
    assert "dominant phase: connect/handshake" in out


def test_report_attributes_query_when_queries_dominate():
    connect = timing.Phase("connect")
    counts = timing.Phase("counts")
    listing = timing.Phase("list")
    total = timing.Phase("total")
    connect.samples = [20.0]
    counts.samples = [150.0]
    listing.samples = [200.0]
    total.samples = [370.0]

    dominant = timing._report(
        {"label": "shape", "phases": [connect, counts, listing, total]}
    )

    assert dominant == "query"


def test_repeat_is_clamped_to_cap(monkeypatch, wired, capsys):
    monkeypatch.setattr(
        sys, "argv", ["timing_diagnostic.py", "--repeat", "9999"]
    )
    seen: list[int] = []

    real_run_index = timing._run_index

    def spy(cfg, types, status, per, repeat):
        seen.append(repeat)
        return real_run_index(cfg, types, status, per, repeat)

    monkeypatch.setattr(timing, "_run_index", spy)
    rc = timing.main()

    assert rc == 0
    assert seen and all(r == timing.MAX_REPEAT for r in seen)
    assert "clamped" in capsys.readouterr().err


def test_unknown_type_is_rejected_before_connecting(monkeypatch, wired, capsys):
    calls, _ = wired
    monkeypatch.setattr(
        sys, "argv", ["timing_diagnostic.py", "--type", "nope"]
    )

    rc = timing.main()

    captured = capsys.readouterr()
    assert rc == 2
    assert "Unknown content type" in captured.err
    assert "connect" not in calls


def test_missing_connection_string_is_a_clear_error(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["timing_diagnostic.py"])
    monkeypatch.delenv("CONNECTION_STRING", raising=False)

    rc = timing.main()

    assert rc == 2
    assert "CONNECTION_STRING is not set" in capsys.readouterr().err


def test_db_error_is_redacted_and_exits_nonzero(monkeypatch, wired, capsys):
    _calls, _ = wired
    secret = "postgresql://user:s3cret@db.example:5432/site"

    def boom(cfg):
        raise psycopg.OperationalError(
            f"connection failed: could not connect to server {secret} "
            "password=hunter2"
        )

    monkeypatch.setattr(db, "page_conn", boom)
    monkeypatch.setattr(sys, "argv", ["timing_diagnostic.py"])

    rc = timing.main()

    err = capsys.readouterr().err
    assert rc == 1
    assert secret not in err
    assert "hunter2" not in err
    assert "OperationalError" in err
    # The failing phase is named so a spike/error can be attributed.
    assert "connect" in err


def test_redact_strips_dsn_and_password():
    cfg = _cfg()
    message = f"could not connect to {cfg.connection_string} password=hunter2"

    redacted = timing._redact(message, cfg)

    assert "s3cret" not in redacted
    assert "hunter2" not in redacted
    assert "<redacted>" in redacted
