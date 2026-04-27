"""Thin psycopg layer — CRUD driven by ContentType definitions from config.py."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .config import ContentType, Config


def _conn(cfg: Config) -> psycopg.Connection:
    return psycopg.connect(cfg.connection_string, row_factory=dict_row)


def list_records(cfg: Config, ct: ContentType) -> list[dict[str, Any]]:
    if not ct.read_sql:
        return []
    with _conn(cfg) as conn, conn.cursor() as cur:
        cur.execute(ct.read_sql)
        rows = list(cur.fetchall())
    # The site's read_sql uses DISTINCT ON (id) so rows come back id-ordered.
    # Re-sort newest first; rows with no date sink to the bottom.
    def sort_key(row):
        value = row.get("date") or row.get("created_at")
        # Sort tuple: (has_value, value-or-id) so Nones sort last under reverse.
        return (value is not None, value or row.get("id") or 0)
    rows.sort(key=sort_key, reverse=True)
    return rows


def list_timeline(
    cfg: Config,
    type_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Merge records across content types, sorted newest first.

    Each row is annotated with `_type` = content-type name. Content types
    without a configured read_sql are silently skipped.
    """
    names = type_names or list(cfg.content_types.keys())
    out: list[dict[str, Any]] = []
    for n in names:
        ct = cfg.content_types.get(n)
        if not ct or not ct.read_sql:
            continue
        for r in list_records(cfg, ct):
            r = dict(r)
            r["_type"] = n
            out.append(r)

    def key(row: dict) -> tuple:
        value = row.get("date") or row.get("created_at")
        return (value is not None, value or 0)

    out.sort(key=key, reverse=True)
    return out


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


def list_all_tags(cfg: Config) -> list[str]:
    """Return every distinct tag name across all content types, alphabetized."""
    with _conn(cfg) as conn, conn.cursor() as cur:
        cur.execute("SELECT name FROM tags ORDER BY name")
        return [r["name"] for r in cur.fetchall()]


def _now_fields(values: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    values = dict(values)
    for key in ("created_at", "updated_at", "date"):
        if key in columns and not values.get(key):
            values[key] = now
    for col in columns:
        values.setdefault(col, None)
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
    set_clause = ", ".join(f"{c} = %({c})s" for c in editable if c in values)
    params = {c: values[c] for c in editable if c in values}
    params["id"] = record_id

    with _conn(cfg) as conn, conn.cursor() as cur:
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
