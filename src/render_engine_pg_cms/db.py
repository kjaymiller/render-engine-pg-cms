"""Thin psycopg layer — CRUD driven by ContentType definitions from config.py."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .config import ContentType, Config


def _conn(cfg: Config) -> psycopg.Connection:
    return psycopg.connect(cfg.connection_string, row_factory=dict_row)


# Per-process cache of {table: {column,...}}. The CMS reads tables directly
# (rather than via the site-publishing read_sql) so it can surface drafts and
# scheduled rows that the site's published feed filters out.
_table_columns_cache: dict[str, set[str]] = {}


def _table_columns(cur: psycopg.Cursor, table: str) -> set[str]:
    cached = _table_columns_cache.get(table)
    if cached is not None:
        return cached
    cur.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = %(t)s
        """,
        {"t": table},
    )
    cols = {r["column_name"] if isinstance(r, dict) else r[0] for r in cur.fetchall()}
    _table_columns_cache[table] = cols
    return cols


def _status_clause(cols: set[str], status: str) -> str:
    """Return a `WHERE` fragment (without the `WHERE`) for the requested
    status filter, or "" if no filter applies. Tolerates tables without
    `draft` or `date` (e.g. conferences) by silently skipping the missing
    predicate.
    """
    has_draft = "draft" in cols
    has_date = "date" in cols
    if status == "drafts":
        return "draft = TRUE" if has_draft else "FALSE"
    if status == "scheduled":
        if not has_date:
            return "FALSE"
        base = "date > NOW()"
        if has_draft:
            base = f"draft = FALSE AND {base}"
        return base
    if status == "published":
        parts = []
        if has_draft:
            parts.append("draft = FALSE")
        if has_date:
            parts.append("(date IS NULL OR date <= NOW())")
        return " AND ".join(parts)
    return ""  # "all" / unknown


def _order_clause(cols: set[str]) -> str:
    # Stable total order (id tiebreaker) so LIMIT/OFFSET paging never skips
    # or duplicates rows.
    order = "ORDER BY "
    if "date" in cols:
        order += "date DESC NULLS LAST, "
    return order + "id DESC"


def _select_clause(
    cols: set[str], excerpt_chars: int | None,
) -> tuple[str, bool]:
    """Build the select list for a bounded list read.

    When `excerpt_chars` is set and the table has a `content` column, the
    body is truncated server-side so a page of list rows doesn't ship the
    full markdown of every post. Returns (select_list, truncated) where
    `truncated` says whether the content column was actually shortened.

    `excerpt_chars=None` (internal, unbounded callers) selects everything
    so extraction/migration paths still see complete rows.
    """
    if excerpt_chars is None or "content" not in cols:
        return "*", False
    select = "*, LEFT(content, %(excerpt_chars)s) AS content"
    return select, True


def build_list_query(
    cols: set[str],
    table: str,
    status: str = "all",
    limit: int | None = None,
    offset: int = 0,
    excerpt_chars: int | None = None,
) -> tuple[str, dict[str, Any], bool]:
    """Assemble the SELECT that `list_records` runs.

    Split out so diagnostics (scripts/explain_timeline.py) can EXPLAIN the
    *exact* statement the app issues instead of a hand-copied approximation
    that silently drifts. Returns (sql, params, truncated).
    """
    where = _status_clause(cols, status)
    select, truncated = _select_clause(cols, excerpt_chars)
    sql = f"SELECT {select} FROM {table}"
    if where:
        sql += f" WHERE {where}"
    sql += f" {_order_clause(cols)}"
    params: dict[str, Any] = {}
    if truncated:
        params["excerpt_chars"] = max(1, int(excerpt_chars))
    if limit is not None:
        sql += " LIMIT %(limit)s"
        params["limit"] = max(0, int(limit))
    if offset:
        sql += " OFFSET %(offset)s"
        params["offset"] = max(0, int(offset))
    return sql, params, truncated


def list_records(
    cfg: Config,
    ct: ContentType,
    status: str = "all",
    limit: int | None = None,
    offset: int = 0,
    excerpt_chars: int | None = None,
) -> list[dict[str, Any]]:
    """Return records for one content type, newest first.

    `limit`/`offset` are applied in SQL as bound parameters so callers only
    pull the window they render. `limit=None` means no LIMIT (internal use).

    `excerpt_chars` truncates the `content` column in SQL for bounded reads
    (list pages), so a page window ships excerpts rather than every post's
    full body. It is ignored when `limit is None`, since unbounded callers
    need complete rows. Rows whose content was cut carry `_truncated=True`
    so templates can distinguish an excerpt from a complete body.
    """
    if not ct.table:
        return []
    # Never excerpt unbounded reads: callers like the API create-lookup and
    # any future export path rely on seeing the whole row.
    if limit is None:
        excerpt_chars = None
    with _conn(cfg) as conn, conn.cursor() as cur:
        cols = _table_columns(cur, ct.table)
        sql, params, truncated = build_list_query(
            cols, ct.table, status=status, limit=limit, offset=offset,
            excerpt_chars=excerpt_chars,
        )
        cur.execute(sql, params)
        rows = list(cur.fetchall())
        if truncated:
            for r in rows:
                # Mark rows that are at (or over) the cut so nothing renders
                # a silently-shortened post as if it were the full body.
                content = r.get("content")
                r["_truncated"] = bool(content) and len(content) >= max(
                    1, int(excerpt_chars)
                )
        return rows


def count_by_status(cfg: Config, ct: ContentType) -> dict[str, int]:
    """Return {published, drafts, scheduled, all} counts for one content type,
    computed with a single aggregate query.

    A status whose filter doesn't apply to this table (no `draft`/`date`
    columns) counts every row, matching what `list_records` returns for it.
    """
    out = {"all": 0, "published": 0, "drafts": 0, "scheduled": 0}
    if not ct.table:
        return out
    with _conn(cfg) as conn, conn.cursor() as cur:
        cols = _table_columns(cur, ct.table)
        selects = ['COUNT(*) AS "all"']
        for status in ("published", "drafts", "scheduled"):
            where = _status_clause(cols, status) or "TRUE"
            selects.append(f'COUNT(*) FILTER (WHERE {where}) AS "{status}"')
        cur.execute(f"SELECT {', '.join(selects)} FROM {ct.table}")
        row = cur.fetchone() or {}
        for key in out:
            out[key] = int(row.get(key) or 0)
    return out


def _timeline_key(row: dict) -> tuple:
    # Mirrors the SQL ordering (date DESC NULLS LAST, id DESC) so the
    # per-type windows fetched by list_timeline merge without gaps.
    value = row.get("date")
    return (value is not None, value or 0, row.get("id") or 0)


def list_timeline(
    cfg: Config,
    type_names: list[str] | None = None,
    status: str = "all",
    limit: int | None = None,
    offset: int = 0,
    excerpt_chars: int | None = None,
) -> list[dict[str, Any]]:
    """Merge records across content types, sorted newest first.

    Each row is annotated with `_type` = content-type name. Content types
    without a configured table are silently skipped.

    With `limit`, only the merged window [offset, offset+limit) is returned.
    Each type is asked for at most `offset + limit` rows in SQL: any row in
    the merged window must be within the first `offset + limit` rows of its
    own type, so the result is exact without reading whole tables.

    `excerpt_chars` truncates each row's `content` in SQL for bounded reads
    so the merged page ships excerpts instead of every post's full body.
    """
    names = type_names or list(cfg.content_types.keys())
    per_type = None if limit is None else max(0, offset) + max(0, limit)
    out: list[dict[str, Any]] = []
    for n in names:
        ct = cfg.content_types.get(n)
        if not ct or not ct.table:
            continue
        for r in list_records(
            cfg, ct, status=status, limit=per_type, excerpt_chars=excerpt_chars,
        ):
            r = dict(r)
            r["_type"] = n
            out.append(r)

    out.sort(key=_timeline_key, reverse=True)
    if limit is None:
        return out[max(0, offset):]
    return out[max(0, offset) : max(0, offset) + max(0, limit)]


def get_record(cfg: Config, ct: ContentType, record_id: int) -> dict[str, Any] | None:
    with _conn(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT * FROM {ct.table} WHERE id = %(id)s", {"id": record_id}
        )
        row = cur.fetchone()
        if row is None:
            return None
        if ct.has_tags:
            row["tags"] = _tags_for(cur, ct, record_id)
        return row


def _tags_for(cur: psycopg.Cursor, ct: ContentType, record_id: int) -> list[str]:
    join_table = f"{ct.table}_tags"
    fk = f"{ct.table}_id"
    cur.execute(
        f"""
        SELECT tags.name FROM tags
        JOIN {join_table} ON {join_table}.tag_id = tags.id
        WHERE {join_table}.{fk} = %(id)s
        ORDER BY tags.name
        """,
        {"id": record_id},
    )
    return [r["name"] for r in cur.fetchall()]


def tags_for_records(
    cfg: Config, ct: ContentType, record_ids: list[int],
) -> dict[int, list[str]]:
    """Return {record_id: [tag, ...]} for a batch of records in one query.

    Callers that need tags for a whole page should use this instead of
    calling `get_record` (or `_tags_for`) per row — that is an N+1. One
    `= ANY(...)` query covers the entire page, and record ids with no tags
    are simply absent from the result.
    """
    if not ct.has_tags or not record_ids:
        return {}
    join_table = f"{ct.table}_tags"
    fk = f"{ct.table}_id"
    with _conn(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {join_table}.{fk} AS record_id, tags.name AS name
            FROM tags
            JOIN {join_table} ON {join_table}.tag_id = tags.id
            WHERE {join_table}.{fk} = ANY(%(ids)s)
            ORDER BY {join_table}.{fk}, tags.name
            """,
            {"ids": [int(i) for i in record_ids]},
        )
        out: dict[int, list[str]] = {}
        for r in cur.fetchall():
            out.setdefault(r["record_id"], []).append(r["name"])
        return out


def list_all_tags(cfg: Config) -> list[str]:
    """Return every distinct tag name across all content types, alphabetized."""
    with _conn(cfg) as conn, conn.cursor() as cur:
        cur.execute("SELECT name FROM tags ORDER BY name")
        return [r["name"] for r in cur.fetchall()]


def complete_tag(cfg: Config, prefix: str, limit: int = 8) -> list[str]:
    """Return existing tag names that start with `prefix` (case-insensitive),
    for autocomplete on the tags input. Empty/whitespace prefix returns [].
    """
    prefix = (prefix or "").strip().lower()
    if not prefix:
        return []
    with _conn(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name FROM tags WHERE name ILIKE %(p)s ORDER BY name LIMIT %(n)s",
            {"p": prefix + "%", "n": limit},
        )
        return [r["name"] for r in cur.fetchall()]


def suggest_tags_from_text(
    cfg: Config, text: str, limit: int = 8,
) -> list[str]:
    """Suggest existing library tags whose names appear in (or fuzzy-match
    a word in) `text`. Uses pg_trgm's word_similarity — the `<%` operator
    is true when a tag name matches a continuous extent of words in the
    text. Requires sql/tags_trgm_migration.sql.
    """
    text = (text or "").strip()
    if not text:
        return []
    sql = """
        SELECT name
        FROM tags
        WHERE name <%% %(text)s
        ORDER BY word_similarity(name, %(text)s) DESC, name
        LIMIT %(limit)s
    """
    with _conn(cfg) as conn, conn.cursor() as cur:
        cur.execute(sql, {"text": text, "limit": limit})
        return [r["name"] for r in cur.fetchall()]




def _now_fields(values: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    values = dict(values)
    for key in ("created_at", "updated_at", "date"):
        if key in columns and not values.get(key):
            values[key] = now
    for col in columns:
        values.setdefault(col, None)
    # `draft` is NOT NULL in the schema; coerce a missing/None to False so
    # the configured INSERT statement binds cleanly even if the caller
    # didn't think to set it.
    if "draft" in columns and values.get("draft") is None:
        values["draft"] = False
    return values


def create_record(
    cfg: Config,
    ct: ContentType,
    values: dict[str, Any],
    tags: list[str] | None = None,
) -> None:
    if ct.primary_insert is None:
        raise RuntimeError(f"No primary INSERT configured for {ct.name}")
    primary_stmt, primary_params = ct.primary_insert
    values = _now_fields(values, primary_params)

    with _conn(cfg) as conn, conn.cursor() as cur:
        cur.execute(primary_stmt, values)
        if ct.has_tags and tags:
            _upsert_tags(cur, ct, values, tags)
        # The configured INSERT statement is owned by the host site, so it
        # won't include CMS-only columns like `draft`. Apply them by slug
        # right after, while we're still in the same transaction.
        cols = _table_columns(cur, ct.table)
        if "draft" in cols and values.get("slug") is not None:
            cur.execute(
                f"UPDATE {ct.table} SET draft = %(d)s WHERE slug = %(s)s",
                {"d": bool(values.get("draft")), "s": values["slug"]},
            )
        conn.commit()


def _upsert_tags(
    cur: psycopg.Cursor,
    ct: ContentType,
    values: dict[str, Any],
    tags: list[str],
) -> None:
    now = datetime.now(timezone.utc)
    tag_stmt = ct.tag_insert[0] if ct.tag_insert else None
    join_stmt = ct.join_insert[0] if ct.join_insert else None
    for tag in tags:
        tag_values = {**values, "name": tag, "created_at": now}
        if tag_stmt:
            # Savepoint so a UniqueViolation on the tag doesn't abort the
            # outer transaction (which would drop the record we just inserted).
            cur.execute("SAVEPOINT tag_insert")
            try:
                cur.execute(tag_stmt, tag_values)
                cur.execute("RELEASE SAVEPOINT tag_insert")
            except psycopg.errors.UniqueViolation:
                cur.execute("ROLLBACK TO SAVEPOINT tag_insert")
                cur.execute("RELEASE SAVEPOINT tag_insert")
        if join_stmt:
            cur.execute(join_stmt, tag_values)


def update_record(
    cfg: Config,
    ct: ContentType,
    record_id: int,
    values: dict[str, Any],
    tags: list[str] | None = None,
) -> None:
    editable = [
        c for c in ct.primary_columns if c not in ("created_at",)
    ]
    if "updated_at" in editable:
        values["updated_at"] = datetime.now(timezone.utc)

    with _conn(cfg) as conn, conn.cursor() as cur:
        cols = _table_columns(cur, ct.table)
        # `draft` lives outside the host site's configured INSERT, so add it
        # to the editable set when the column actually exists on the table.
        if "draft" in cols and "draft" in values:
            if "draft" not in editable:
                editable = [*editable, "draft"]
            values["draft"] = bool(values.get("draft"))
        set_clause = ", ".join(f"{c} = %({c})s" for c in editable if c in values)
        params = {c: values[c] for c in editable if c in values}
        params["id"] = record_id
        if set_clause:
            cur.execute(
                f"UPDATE {ct.table} SET {set_clause} WHERE id = %(id)s",
                params,
            )
        if ct.has_tags and tags is not None:
            join_table = f"{ct.table}_tags"
            fk = f"{ct.table}_id"
            cur.execute(
                f"DELETE FROM {join_table} WHERE {fk} = %(id)s",
                {"id": record_id},
            )
            # Re-insert tag associations.
            slug_value = values.get("slug")
            _upsert_tags(cur, ct, {"slug": slug_value}, tags)
        conn.commit()


def set_syndication_url(
    cfg: Config,
    ct: ContentType,
    record_id: int,
    column: str,
    url: str,
) -> None:
    if column not in ("mastodon_url", "bluesky_url"):
        raise ValueError(f"Unsupported syndication column: {column}")
    with _conn(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {ct.table} SET {column} = %(url)s WHERE id = %(id)s",
            {"url": url, "id": record_id},
        )
        conn.commit()


def set_mastodon_url(
    cfg: Config, ct: ContentType, record_id: int, url: str
) -> None:
    set_syndication_url(cfg, ct, record_id, "mastodon_url", url)


def set_bluesky_url(
    cfg: Config, ct: ContentType, record_id: int, url: str
) -> None:
    set_syndication_url(cfg, ct, record_id, "bluesky_url", url)


def delete_record(cfg: Config, ct: ContentType, record_id: int) -> None:
    with _conn(cfg) as conn, conn.cursor() as cur:
        if ct.has_tags:
            join_table = f"{ct.table}_tags"
            fk = f"{ct.table}_id"
            cur.execute(
                f"DELETE FROM {join_table} WHERE {fk} = %(id)s",
                {"id": record_id},
            )
        cur.execute(
            f"DELETE FROM {ct.table} WHERE id = %(id)s", {"id": record_id}
        )
        conn.commit()
