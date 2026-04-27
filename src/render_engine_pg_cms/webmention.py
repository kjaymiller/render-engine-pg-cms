"""Pull mention counts from webmention.io."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx
import psycopg
from psycopg.rows import dict_row

from .config import Config, ContentType

log = logging.getLogger(__name__)

# TCP keepalives so a slow webmention.io pass doesn't let the DB socket die
# silently. Relevant when pg is behind a NAT/load-balancer with idle timeouts.
_PG_KWARGS = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
    "connect_timeout": 10,
}


def _connect(cfg: Config, *, row_factory=None):
    kwargs = dict(_PG_KWARGS)
    if row_factory is not None:
        kwargs["row_factory"] = row_factory
    return psycopg.connect(cfg.connection_string, **kwargs)


def _connect_with_retry(cfg: Config, *, row_factory=None, attempts: int = 3):
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return _connect(cfg, row_factory=row_factory)
        except psycopg.OperationalError as exc:
            last_exc = exc
            if i == attempts - 1:
                break
            delay = 2 ** i  # 1s, 2s
            log.warning("pg connect failed (%s); retrying in %ds", exc, delay)
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


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


_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=5.0)


def fetch_summary(
    cfg: Config, target_url: str, *, attempts: int = 3
) -> tuple[int, dict[str, int]]:
    """Return (count, types) for target_url.

    `types` is webmention.io's per-type breakdown, e.g.
    {"like": 3, "repost": 1, "in-reply-to": 1}. Empty dict if none.
    Retries transient network errors (handshake timeouts, connection resets).
    """
    params = {"target": target_url}
    headers = {}
    if cfg.webmention_io_token:
        headers["Authorization"] = f"Bearer {cfg.webmention_io_token}"
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            r = httpx.get(COUNT_API, params=params, headers=headers, timeout=_HTTP_TIMEOUT)
        except httpx.HTTPError as exc:
            last_exc = exc
            if i == attempts - 1:
                break
            delay = 2 ** i  # 1s, 2s
            log.warning("webmention.io fetch failed (%s); retrying in %ds", exc, delay)
            time.sleep(delay)
            continue
        if r.status_code >= 400:
            raise WebmentionError(f"webmention.io {r.status_code}: {r.text[:300]}")
        data = r.json()
        count = int(data.get("count") or 0)
        types = data.get("type") or {}
        if not isinstance(types, dict):
            types = {}
        # Coerce values to int; drop anything non-numeric.
        clean_types = {}
        for k, v in types.items():
            try:
                clean_types[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
        return count, clean_types
    raise WebmentionError(f"Network error: {last_exc}")


def fetch_count(cfg: Config, target_url: str, *, attempts: int = 3) -> int:
    """Back-compat wrapper. Returns just the total count."""
    count, _ = fetch_summary(cfg, target_url, attempts=attempts)
    return count


def sync_record(
    cfg: Config, ct: ContentType, record: dict
) -> tuple[int, str, dict[str, int]]:
    """Sync one record. Returns (count, target_url, types)."""
    import json

    target_url = build_target_url(cfg, ct.name, record.get("slug") or "")
    count, types = fetch_summary(cfg, target_url)
    with _connect_with_retry(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {ct.table}
            SET webmentions_count = %(count)s,
                webmentions_types = %(types)s::jsonb,
                webmentions_synced_at = %(now)s
            WHERE id = %(id)s
            """,
            {
                "count": count,
                "types": json.dumps(types),
                "now": datetime.now(timezone.utc),
                "id": record["id"],
            },
        )
        conn.commit()
    return count, target_url, types


def last_sync_time(cfg: Config) -> datetime | None:
    """Return the most recent `webmentions_synced_at` across microblog+blog.

    Returns None when nothing has ever been synced. Used on startup to
    avoid stampeding webmention.io after frequent restarts.
    """
    latest: datetime | None = None
    for name in ("microblog", "blog"):
        ct = cfg.content_types.get(name)
        if ct is None:
            continue
        try:
            with _connect_with_retry(cfg) as conn, conn.cursor() as cur:
                cur.execute(
                    f"SELECT MAX(webmentions_synced_at) FROM {ct.table}"
                )
                row = cur.fetchone()
                val = row[0] if row else None
                if val is not None and (latest is None or val > latest):
                    latest = val
        except psycopg.Error as exc:
            log.warning("could not read last sync time from %s: %s", ct.table, exc)
    return latest


def collect_sync_targets(
    cfg: Config,
    *,
    max_age_days: int | None = None,
) -> list[tuple[str, ContentType, dict]]:
    """Fetch every row that bridgy could have relayed mentions for.

    Returned as (type_name, ContentType, row_dict) tuples so callers can
    iterate without re-opening DB connections.

    `max_age_days`: if set, restrict to rows whose `date` is within the
    last N days. Old posts rarely pick up new mentions, so the auto-loop
    uses this to avoid hammering webmention.io for the long tail. Manual
    syncs pass None to hit every record.
    """
    targets: list[tuple[str, ContentType, dict]] = []
    where_age = ""
    params: dict = {}
    if max_age_days is not None:
        where_age = "AND date >= %(cutoff)s"
        params["cutoff"] = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    for name in ("microblog", "blog"):
        ct = cfg.content_types.get(name)
        if ct is None:
            continue
        with _connect_with_retry(cfg, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT id, slug, webmentions_count FROM {ct.table} "
                    "WHERE slug IS NOT NULL "
                    "AND (mastodon_url IS NOT NULL OR bluesky_url IS NOT NULL) "
                    f"{where_age} "
                    "ORDER BY id DESC",
                    params,
                )
                for row in cur.fetchall():
                    targets.append((name, ct, row))
    return targets


def list_targets(cfg: Config) -> list[dict]:
    """Return every syndicated record with the target URL we'd send to
    webmention.io. Diagnostic helper: lets you spot-check whether the
    built URL actually matches the post's public URL on your site.
    """
    out: list[dict] = []
    for name, ct, row in collect_sync_targets(cfg, max_age_days=None):
        try:
            target = build_target_url(cfg, name, row.get("slug") or "")
        except WebmentionError as exc:
            target = f"<error: {exc}>"
        out.append(
            {
                "type": name,
                "id": row["id"],
                "slug": row.get("slug"),
                "target_url": target,
                "webmentions_count": row.get("webmentions_count") or 0,
            }
        )
    return out


def sync_all(
    cfg: Config,
    *,
    max_age_days: int | None = None,
    on_start: "Callable[[int], None] | None" = None,
    on_record: "Callable[[dict], None] | None" = None,
) -> list[dict]:
    """Sync every microblog + blog row that was syndicated.

    Returns a list of dicts: {type, id, slug, prev, count, error}.
    `count` is None when `error` is set.

    `max_age_days`: when set, only records whose `date` is within the last
    N days are synced. The auto-loop uses this to skip the long tail that
    rarely accrues new mentions; manual sync passes None.

    Callbacks:
      - on_start(total): fires once we know how many rows will be processed.
      - on_record(entry): fires as each record finishes.
    Both enable live UI progress.
    """
    results: list[dict] = []
    targets = collect_sync_targets(cfg, max_age_days=max_age_days)
    if on_start is not None:
        try:
            on_start(len(targets))
        except Exception:  # noqa: BLE001
            log.exception("on_start callback raised")
    for name, ct, row in targets:
        prev = row.get("webmentions_count") or 0
        entry = {
            "type": name,
            "id": row["id"],
            "slug": row["slug"],
            "prev": prev,
            "count": None,
            "types": {},
            "error": None,
        }
        try:
            count, _, types = sync_record(cfg, ct, row)
            entry["count"] = count
            entry["types"] = types
        except WebmentionError as exc:
            entry["error"] = str(exc)
        except psycopg.OperationalError as exc:
            entry["error"] = f"db: {exc}"
        except Exception as exc:  # noqa: BLE001 — don't let one row kill the run
            entry["error"] = f"{type(exc).__name__}: {exc}"
        results.append(entry)
        if on_record is not None:
            try:
                on_record(entry)
            except Exception:  # noqa: BLE001 — callbacks must not kill the sync
                log.exception("on_record callback raised")
    return results
