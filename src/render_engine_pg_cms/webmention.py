"""Pull mention counts from webmention.io."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import psycopg
from psycopg.rows import dict_row

from .config import Config, ContentType


class WebmentionError(RuntimeError):
    pass


COUNT_API = "https://webmention.io/api/count"


def build_target_url(cfg: Config, ct_name: str, slug: str) -> str:
    if not cfg.site_base_url:
        raise WebmentionError("SITE_BASE_URL is not set.")
    if not slug:
        raise WebmentionError("Record has no slug; cannot build target URL.")
    return cfg.webmention_url_template.format(
        base=cfg.site_base_url, type=ct_name, slug=slug,
    )


def fetch_count(cfg: Config, target_url: str) -> int:
    """Return the total number of webmentions for target_url."""
    params = {"target": target_url}
    headers = {}
    if cfg.webmention_io_token:
        headers["Authorization"] = f"Bearer {cfg.webmention_io_token}"
    try:
        r = httpx.get(COUNT_API, params=params, headers=headers, timeout=15.0)
    except httpx.HTTPError as exc:
        raise WebmentionError(f"Network error: {exc}") from exc
    if r.status_code >= 400:
        raise WebmentionError(f"webmention.io {r.status_code}: {r.text[:300]}")
    data = r.json()
    # API returns {"count": N, "type": {...}}
    return int(data.get("count") or 0)


def sync_record(
    cfg: Config, ct: ContentType, record: dict
) -> tuple[int, str]:
    """Sync one record. Returns (count, target_url)."""
    target_url = build_target_url(cfg, ct.name, record.get("slug") or "")
    count = fetch_count(cfg, target_url)
    with psycopg.connect(cfg.connection_string) as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {ct.table}
            SET webmentions_count = %(count)s,
                webmentions_synced_at = %(now)s
            WHERE id = %(id)s
            """,
            {
                "count": count,
                "now": datetime.now(timezone.utc),
                "id": record["id"],
            },
        )
        conn.commit()
    return count, target_url


def sync_all(cfg: Config) -> list[tuple[str, int, int]]:
    """Sync every microblog + blog row. Returns [(type, id, count), ...]."""
    results: list[tuple[str, int, int]] = []
    for name in ("microblog", "blog"):
        ct = cfg.content_types.get(name)
        if ct is None:
            continue
        with psycopg.connect(cfg.connection_string, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT id, slug FROM {ct.table} WHERE slug IS NOT NULL")
                rows = cur.fetchall()
        for row in rows:
            try:
                count, _ = sync_record(cfg, ct, row)
                results.append((name, row["id"], count))
            except WebmentionError as exc:
                results.append((name, row["id"], -1))
                print(f"[{name}#{row['id']}] {exc}")
    return results
