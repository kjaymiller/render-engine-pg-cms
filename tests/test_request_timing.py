"""The request-timing middleware stamps every response and warns on slow ones.

Kept dependency-light: the middleware is exercised on a tiny throwaway FastAPI
app rather than importing `main`, which requires a live SITE_PYPROJECT and
CONNECTION_STRING at request time."""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from render_engine_pg_cms import main


@pytest.fixture
def app() -> FastAPI:
    """A minimal app wired with only main's middleware under test."""
    a = FastAPI()
    a.middleware("http")(main.add_process_time)

    @a.get("/ok")
    def ok():
        return {"ok": True}

    return a


def test_adds_x_process_time_header(app):
    r = TestClient(app).get("/ok")
    assert r.status_code == 200
    assert "X-Process-Time" in r.headers
    # A float in milliseconds; parse it to prove the format.
    assert float(r.headers["X-Process-Time"]) >= 0.0


def test_no_slow_warning_by_default(app, caplog):
    """SLOW_REQUEST_MS=0 disables warnings; only the header remains."""
    caplog.set_level(logging.WARNING, logger="render_engine_pg_cms")
    with TestClient(app) as _:
        pass
    assert not any("SLOW" in r.message for r in caplog.records)


def test_slow_request_warns_when_threshold_met(app, monkeypatch, caplog):
    # A threshold of 0 means "every request is slow" (0 is falsy, so use a
    # tiny positive number to force the branch on any real timing).
    monkeypatch.setattr(main, "SLOW_REQUEST_MS", 0.000001)
    caplog.set_level(logging.WARNING, logger="render_engine_pg_cms")
    r = TestClient(app).get("/ok")
    assert r.status_code == 200
    slow = [rec for rec in caplog.records if "SLOW" in rec.getMessage()]
    assert slow, "expected a SLOW warning above the threshold"
    assert "/ok" in slow[0].getMessage()
