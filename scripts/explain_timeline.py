#!/usr/bin/env python
"""Time and EXPLAIN ANALYZE the CMS list/timeline reads.

Purpose: put numbers behind the claim that list pages were slow because each
page shipped every post's full markdown body. This measures the real query
`db.list_records` issues (via `db.build_list_query`, so the statement can't
drift from the app) both ways:

  * "full"    — SELECT * (what list pages used to do)
  * "excerpt" — LEFT(content, N) (what list pages do now)

For each it reports wall-clock latency, rows returned, approximate bytes over
the wire, and the PostgreSQL plan (EXPLAIN ANALYZE, with buffer counts).

Usage (needs CONNECTION_STRING and SITE_PYPROJECT, same as the app):

    uv run python scripts/explain_timeline.py
    uv run python scripts/explain_timeline.py --type blog --per 50 --repeat 5
    uv run python scripts/explain_timeline.py --all-offsets 100,500,2000

The `--all-offsets` run is the interesting one for deep paging: it shows
OFFSET cost growing linearly, which is the signal to move to keyset
pagination.

Read-only: issues SELECT / EXPLAIN SELECT only, never writes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

# Allow running as a plain script from the repo root without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from render_engine_pg_cms import db
from render_engine_pg_cms.config import load_config


def _payload_bytes(rows: list[dict]) -> int:
    """Rough wire size of the result set.

    Not exact wire framing, but close enough to compare full vs excerpted
    bodies: it measures the column values we actually transfer.
    """
    total = 0
    for r in rows:
        for k, v in r.items():
            if v is None:
                continue
            total += len(str(k).encode())
            total += len(v if isinstance(v, bytes) else str(v).encode())
    return total


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _median(values: list[float]) -> float:
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def _time_query(conn, sql: str, params: dict, repeat: int) -> tuple[list[float], int]:
    """Run the real SELECT `repeat` times, returning (latencies_ms, row_count)."""
    latencies: list[float] = []
    row_count = 0
    with conn.cursor(row_factory=dict_row) as cur:
        for _ in range(repeat):
            start = time.perf_counter()
            cur.execute(sql, params)
            rows = cur.fetchall()
            latencies.append((time.perf_counter() - start) * 1000)
            row_count = len(rows)
    return latencies, row_count


def _explain(conn, sql: str, params: dict) -> dict:
    """Return the EXPLAIN (ANALYZE, BUFFERS) JSON plan for `sql`."""
    with conn.cursor() as cur:
        cur.execute(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}", params
        )
        row = cur.fetchone()
    # psycopg returns the single json column; format varies by version.
    plan = row[0] if isinstance(row, (list, tuple)) else row
    if isinstance(plan, str):
        plan = json.loads(plan)
    if isinstance(plan, list):
        plan = plan[0]
    return plan


def _plan_summary(plan: dict) -> str:
    p = plan.get("Plan", {})
    exec_ms = plan.get("Execution Time")
    plan_ms = plan.get("Planning Time")
    shared = p.get("Shared Hit Blocks", 0), p.get("Shared Read Blocks", 0)
    bits = [p.get("Node Type", "?")]
    if p.get("Relation Name"):
        bits.append(p["Relation Name"])
    if p.get("Actual Rows") is not None:
        bits.append(f"rows={p['Actual Rows']}")
    line = f"{' '.join(bits)}"
    if plan_ms is not None:
        line += f" | planning {plan_ms:.2f} ms"
    if exec_ms is not None:
        line += f" | execution {exec_ms:.2f} ms"
    line += f" | buffers hit={shared[0]} read={shared[1]}"
    # Walk the whole tree: the expensive node (Sort/Seq Scan) is usually under
    # the top-level Limit, so inspecting only the root would miss it.
    offenders = _find_offenders(p)
    if offenders:
        line += "  <-- " + ", ".join(offenders)
    return line


def _find_offenders(node: dict) -> list[str]:
    """Return human labels for plan nodes that usually mean a missing index.

    Reports Seq Scan over a relation (full table walk) and Sort (in-memory
    ordering of the whole result). Recurses through the plan tree.
    """
    found: list[str] = []
    node_type = node.get("Node Type", "")
    if node_type == "Seq Scan":
        rel = node.get("Relation Name", "?")
        rows = node.get("Actual Rows")
        found.append(f"Seq Scan on {rel}" + (f" ({rows} rows)" if rows is not None else ""))
    elif node_type in ("Sort", "Incremental Sort"):
        method = node.get("Sort Method")
        space = node.get("Sort Space Used")
        detail = ", ".join(
            str(x) for x in (method, f"{space} kB" if space else None) if x
        )
        found.append(f"Sort{(' (' + detail + ')') if detail else ''}")
    for child in node.get("Plans", []) or []:
        found.extend(_find_offenders(child))
    return found


def _run_case(
    conn, label: str, cols: set[str], table: str, *, status: str,
    limit: int, offset: int, excerpt_chars: int | None, repeat: int,
) -> bool:
    sql, params, truncated = db.build_list_query(
        cols, table, status=status, limit=limit, offset=offset,
        excerpt_chars=excerpt_chars,
    )
    latencies, row_count = _time_query(conn, sql, params, repeat)

    # Measure payload separately (cheap; reuse the same statement once).
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    nbytes = _payload_bytes(rows)

    plan = _explain(conn, sql, params)
    # EXPLAIN (ANALYZE) executes the query; drop the protocol cost line noise.
    plan_exec = plan.get("Execution Time")

    print(f"\n  [{label}] status={status} limit={limit} offset={offset} "
          f"excerpt={'off' if not truncated else params.get('excerpt_chars')}")
    print(f"    rows={row_count}  payload≈{_human(nbytes)}  "
          f"median={_median(latencies):.1f} ms  "
          f"min={min(latencies):.1f}  max={max(latencies):.1f}  "
          f"(n={len(latencies)})")
    if plan_exec is not None:
        print(f"    EXPLAIN ANALYZE execution: {plan_exec:.2f} ms")
    print(f"    plan: {_plan_summary(plan)}")
    return truncated


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--type", action="append", dest="types",
                    help="Content type to measure (repeatable). Default: every type.")
    ap.add_argument("--per", type=int, default=25,
                    help="Page size (matches the app default of 25).")
    ap.add_argument("--status", default="all",
                    choices=("all", "published", "drafts", "scheduled"))
    ap.add_argument("--excerpt-chars", type=int,
                    default=int(os.environ.get("LIST_EXCERPT_CHARS", "600")),
                    help="Excerpt length to compare against full content.")
    ap.add_argument("--repeat", type=int, default=3,
                    help="Timed repetitions per case (median reported).")
    ap.add_argument("--all-offsets", default="",
                    help="Comma-separated offsets to also test (deep-paging cost).")
    ap.add_argument("--no-full", action="store_true",
                    help="Skip the full-content baseline (excerpt only).")
    args = ap.parse_args()

    if not os.environ.get("CONNECTION_STRING"):
        print("CONNECTION_STRING is not set. Run via `fnox exec -- ...` or set it.",
              file=sys.stderr)
        return 2

    cfg = load_config()
    names = args.types or list(cfg.content_types.keys())
    offsets = [0]
    if args.all_offsets:
        offsets = [int(x) for x in args.all_offsets.split(",") if x.strip()]

    print(f"Measuring list reads: per={args.per} status={args.status} "
          f"repeat={args.repeat} excerpt_chars={args.excerpt_chars}")

    only_excerpt = args.no_full
    with psycopg.connect(cfg.connection_string) as conn:
        # Prime the per-process column cache (mirrors app behaviour).
        col_map: dict[str, set[str]] = {}
        with conn.cursor() as cur:
            for n in names:
                ct = cfg.content_types.get(n)
                if ct and ct.table:
                    col_map[n] = db._table_columns(cur, ct.table)

        for n in names:
            ct = cfg.content_types.get(n)
            if not ct or not ct.table:
                print(f"\n== {n}: no table configured, skipping")
                continue
            cols = col_map[n]
            has_content = "content" in cols
            print(f"\n== {n}  (content column: {'yes' if has_content else 'no'})")
            for off in offsets:
                if not only_excerpt:
                    _run_case(conn, "full", cols, ct.table, status=args.status,
                              limit=args.per, offset=off, excerpt_chars=None,
                              repeat=args.repeat)
                _run_case(conn, "excerpt", cols, ct.table, status=args.status,
                          limit=args.per, offset=off,
                          excerpt_chars=args.excerpt_chars, repeat=args.repeat)

    print("\nNote: OFFSET cost grows linearly with the offset — a jump between "
          "--all-offsets values is the signal to add keyset pagination.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
