#!/usr/bin/env python
"""Attribute slow page renders to connect/handshake vs query time.

The 2026.11.0 release made a page render share one psycopg connection across
its reads and collapsed the timeline's per-type counts into one UNION ALL
query. Residual 2-6s TTFB spikes remain on simple two-query pages, and the
open question is whether they come from *connecting* (TLS handshake to a
remote database, ~200 ms per un-reused connection) or from the *queries*
themselves / network transit.

This diagnostic answers that against the real database. For each page shape
it times the phases the app actually pays, using the same `db` helpers the
routes use so the numbers can't drift from production:

  connect     — `db.page_conn(cfg)`: TCP + TLS + auth + startup
  counts      — the header's status-count read
  list        — the page's row read (shared connection)
  total       — connect + counts + list, in order

Two shapes are covered, mirroring the routes:

  index       — timeline: `counts_by_status_for` + `list_timeline`
                (main.py `index`)
  collection  — one type: `count_by_status` + `list_records`
                (main.py `list_view`)

A fresh connection is opened every pass so the handshake cost is measured
rather than cached, and each phase is reported as median/min/max over
`--repeat` passes: a spike is attributed to the phase that moved.

Usage (needs CONNECTION_STRING and SITE_PYPROJECT, same as the app):

    uv run python scripts/timing_diagnostic.py
    uv run python scripts/timing_diagnostic.py --repeat 5 --per 25
    uv run python scripts/timing_diagnostic.py --type blog --status published

Read-only: only SELECTs via the existing db read helpers, never writes.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

import psycopg

# Allow running as a plain script from the repo root without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from render_engine_pg_cms import db
from render_engine_pg_cms.config import load_config
from render_engine_pg_cms.main import VALID_STATUSES

# How many passes a single run may make: the diagnostic hits the real
# database, so an unbounded repeat would be a way to hammer production.
MAX_REPEAT = 20

# Timeline types the site's `index` renders (main.py).
TIMELINE_TYPES = ("microblog", "blog", "notes")
# Types whose body still ships on the timeline/list (main.py keeps the
# excerpt only for microblog/notes; blog/notes timeline cards omit it).
TIMELINE_KEEPS_BODY = {"microblog", "notes"}
LIST_KEEPS_BODY = {"microblog", "notes"}


# A DSN can hide in a psycopg error message (e.g. a connect failure echoes
# the conninfo). Redact anything DSN-shaped before printing, and never print
# cfg.connection_string itself.
_DSN_RE = re.compile(r"\bpostgres(?:ql)?://[^\s'\"]+")
_PASSWORD_RE = re.compile(r"(?i)(password\s*=\s*)\S+")


def _redact(message: str, cfg) -> str:
    """Strip DSNs/passwords (and this cfg's DSN) from an error string."""
    secret = getattr(cfg, "connection_string", "") or ""
    if secret:
        message = message.replace(secret, "<redacted>")
    message = _DSN_RE.sub("postgresql://<redacted>", message)
    message = _PASSWORD_RE.sub(r"\1<redacted>", message)
    return message


def _median(values: list[float]) -> float:
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


class Phase:
    """Wall-clock samples for one named step (perf_counter, like the
    X-Process-Time middleware in main.py)."""

    def __init__(self, label: str):
        self.label = label
        self.samples: list[float] = []

    def time(self, fn):
        start = time.perf_counter()
        try:
            out = fn()
        except psycopg.Error as exc:
            # Tag the failure with the phase so main() can report which step
            # died (connect vs a query) without echoing the raw error verbatim.
            exc.phase = self.label
            raise
        self.samples.append((time.perf_counter() - start) * 1000)
        return out

    @property
    def median(self) -> float:
        return _median(self.samples)

    def line(self) -> str:
        if not self.samples:
            return f"    {self.label:<9} —"
        return (
            f"    {self.label:<9} median={self.median:8.1f} ms  "
            f"min={min(self.samples):8.1f}  max={max(self.samples):8.1f}  "
            f"(n={len(self.samples)})"
        )


def _prime_columns(conn, cfg, types: list[str]) -> None:
    """Warm the per-process column cache the way the app does on first use.

    The app resolves `_table_columns` once per process; measuring the read
    without priming would fold a schema round-trip into the first query.
    """
    with conn.cursor() as cur:
        for name in types:
            ct = cfg.content_types.get(name)
            if ct and ct.table:
                db._table_columns(cur, ct.table)


def _run_index(cfg, types: list[str], status: str, per: int, repeat: int) -> dict:
    """Measure the timeline shape (`main.index`')."""
    excerpt_chars = int(os.environ.get("LIST_EXCERPT_CHARS", "600"))
    omit = {n for n in types if n not in TIMELINE_KEEPS_BODY}
    cts = [cfg.content_types[n] for n in types]

    connect = Phase("connect")
    counts = Phase("counts")
    listing = Phase("list")
    total = Phase("total")

    for _ in range(repeat):
        phases_start = time.perf_counter()
        conn = connect.time(lambda: db.page_conn(cfg))
        try:
            _prime_columns(conn, cfg, types)
            counts.time(
                lambda conn=conn: db.counts_by_status_for(cfg, cts, conn=conn)
            )
            listing.time(
                lambda conn=conn: db.list_timeline(
                    cfg, types, status=status, limit=per, offset=0,
                    excerpt_chars=excerpt_chars, omit_content_types=omit,
                    conn=conn,
                )
            )
        finally:
            conn.close()
        total.samples.append((time.perf_counter() - phases_start) * 1000)

    return {
        "label": "index (timeline: counts_by_status_for + list_timeline)",
        "phases": [connect, counts, listing, total],
    }


def _run_collection(cfg, name: str, status: str, per: int, repeat: int) -> dict:
    """Measure a collection shape (`main.list_view`)."""
    excerpt_chars = int(os.environ.get("LIST_EXCERPT_CHARS", "600"))
    ct = cfg.content_types[name]

    connect = Phase("connect")
    counts = Phase("counts")
    listing = Phase("list")
    total = Phase("total")

    for _ in range(repeat):
        phases_start = time.perf_counter()
        conn = connect.time(lambda: db.page_conn(cfg))
        try:
            _prime_columns(conn, cfg, [name])
            counts.time(lambda conn=conn: db.count_by_status(cfg, ct, conn=conn))
            listing.time(
                lambda conn=conn: db.list_records(
                    cfg, ct, status=status, limit=per, offset=0,
                    excerpt_chars=excerpt_chars,
                    omit_content=ct.name not in LIST_KEEPS_BODY,
                    conn=conn,
                )
            )
        finally:
            conn.close()
        total.samples.append((time.perf_counter() - phases_start) * 1000)

    return {
        "label": f"collection /c/{name} (count_by_status + list_records)",
        "phases": [connect, counts, listing, total],
    }


def _report(result: dict) -> str:
    """Print one shape's phases; return the dominant phase name."""
    print(f"\n== {result['label']}")
    phases = result["phases"]
    for phase in phases:
        print(phase.line())
    connect, counts, listing, _total = phases
    query = counts.median + listing.median
    dominant = "connect/handshake" if connect.median >= query else "query"
    print(
        f"    -> connect={connect.median:.1f} ms  "
        f"queries={query:.1f} ms  "
        f"dominant phase: {dominant}"
    )
    return dominant


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--type", action="append", dest="types",
                    help="Content type to measure (repeatable). "
                         "Default: timeline types + the first configured type.")
    ap.add_argument("--per", type=int, default=25,
                    help="Page size (matches the app default of 25).")
    ap.add_argument("--status", default="all", choices=VALID_STATUSES,
                    help="Status filter to measure.")
    ap.add_argument("--repeat", type=int, default=3,
                    help=f"Timed passes per shape (median reported, max {MAX_REPEAT}).")
    args = ap.parse_args()

    if not os.environ.get("CONNECTION_STRING"):
        print("CONNECTION_STRING is not set. Run via `fnox exec -- ...` or set it.",
              file=sys.stderr)
        return 2

    repeat = max(1, min(args.repeat, MAX_REPEAT))
    if repeat != args.repeat:
        print(f"--repeat clamped to [1, {MAX_REPEAT}] (got {args.repeat}).",
              file=sys.stderr)

    cfg = load_config()

    # Validate --type against configured content types before any query.
    if args.types:
        unknown = [n for n in args.types if n not in cfg.content_types]
        if unknown:
            print(f"Unknown content type(s): {', '.join(unknown)}. "
                  f"Configured: {', '.join(cfg.content_types) or '(none)'}.",
                  file=sys.stderr)
            return 2
        wanted = list(dict.fromkeys(args.types))
    else:
        wanted = list(cfg.content_types)

    timeline = [n for n in TIMELINE_TYPES if n in cfg.content_types]
    collection_types = [
        n for n in wanted
        if cfg.content_types.get(n) and cfg.content_types[n].table
    ]

    print(
        f"Timing page shapes: per={args.per} status={args.status} "
        f"repeat={repeat}"
    )

    results: list[dict] = []
    try:
        if timeline:
            results.append(_run_index(cfg, timeline, args.status, args.per, repeat))
        for name in collection_types:
            results.append(_run_collection(cfg, name, args.status, args.per, repeat))
    except psycopg.Error as exc:
        # psycopg errors can embed the conninfo; print the failing phase and
        # the exception class + a redacted message, never the raw DSN.
        phase = getattr(exc, "phase", "connect/query")
        print(
            f"\nDB error during '{phase}': {type(exc).__name__}: "
            f"{_redact(str(exc), cfg)}",
            file=sys.stderr,
        )
        return 1

    if not results:
        print("No content types with a configured table; nothing to measure.",
              file=sys.stderr)
        return 2

    dominant_counts: dict[str, int] = {}
    for result in results:
        dominant = _report(result)
        dominant_counts[dominant] = dominant_counts.get(dominant, 0) + 1

    print("\n--- attribution ---")
    for kind, n in sorted(dominant_counts.items()):
        print(f"  {n} shape(s) dominated by {kind}")
    if len(dominant_counts) == 1:
        only = next(iter(dominant_counts))
        print(f"  Spikes on these pages are most likely {only}-bound.")
    else:
        print("  Mixed: some shapes are connect-bound, others query-bound — "
              "compare the phase medians per shape above.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
