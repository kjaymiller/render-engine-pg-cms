"""REST API for programmatic CMS access.

Bearer-token auth via `CMS_API_TOKEN`. All routes return JSON.
Mounted under /api/v1 from main.py.
"""
from __future__ import annotations

import hmac
import os
from datetime import datetime
from typing import Any

import psycopg
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query

from . import db
from .bluesky import BlueskyError, post_status as post_to_bluesky_api
from .config import ContentType
from .github import GitHubError, trigger_publish
from .mastodon import MastodonError, build_status_text, post_status

router = APIRouter(prefix="/api/v1")


def _expected_token() -> str:
    tok = os.environ.get("CMS_API_TOKEN", "")
    if not tok:
        raise HTTPException(503, "CMS_API_TOKEN not configured on server.")
    return tok


def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = _expected_token()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token.")
    given = authorization[len("Bearer "):]
    if not hmac.compare_digest(given, expected):
        raise HTTPException(401, "Invalid token.")


# Lazy import of cfg() to avoid a circular import with main.py.
def _cfg():
    from .main import cfg
    return cfg()


def _ct(name: str) -> ContentType:
    c = _cfg()
    if name not in c.content_types:
        raise HTTPException(404, f"Unknown content type: {name}")
    return c.content_types[name]


VALID_STATUSES = ("all", "published", "drafts", "scheduled")


def _coerce_values(payload: dict, ct: ContentType) -> tuple[dict, list[str] | None]:
    """Pull recognized columns out of a JSON payload, parse date if ISO,
    and split off `tags`. Unknown keys are ignored — same shape as the form
    handler's _extract but without form-encoding ceremony.
    """
    values: dict[str, Any] = {}
    for col in ct.primary_columns:
        if col in ("id", "created_at", "updated_at"):
            continue
        if col not in payload:
            continue
        raw = payload[col]
        if col == "date" and isinstance(raw, str) and raw:
            try:
                values[col] = datetime.fromisoformat(raw)
            except ValueError:
                raise HTTPException(400, f"Invalid ISO datetime for `date`: {raw!r}")
            continue
        values[col] = raw
    if "draft" in payload:
        values["draft"] = bool(payload["draft"])
    tags = payload.get("tags")
    if tags is not None and not isinstance(tags, list):
        raise HTTPException(400, "`tags` must be a list of strings.")
    return values, tags


@router.get("/content-types", dependencies=[Depends(require_token)])
def list_content_types() -> dict:
    c = _cfg()
    return {
        "content_types": [
            {
                "name": ct.name,
                "table": ct.table,
                "columns": ct.primary_columns,
                "has_tags": ct.has_tags,
            }
            for ct in c.content_types.values()
        ]
    }


@router.get("/c/{name}", dependencies=[Depends(require_token)])
def list_records(
    name: str,
    status: str = Query("all"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    if status not in VALID_STATUSES:
        raise HTTPException(400, f"status must be one of {VALID_STATUSES}")
    ct = _ct(name)
    rows = db.list_records(_cfg(), ct, status=status)
    return {"total": len(rows), "records": rows[offset:offset + limit]}


@router.get("/c/{name}/{record_id}", dependencies=[Depends(require_token)])
def get_record(name: str, record_id: int) -> dict:
    ct = _ct(name)
    row = db.get_record(_cfg(), ct, record_id)
    if row is None:
        raise HTTPException(404)
    return row


@router.post(
    "/c/{name}",
    status_code=201,
    dependencies=[Depends(require_token)],
)
def create_record(name: str, payload: dict = Body(...)) -> dict:
    ct = _ct(name)
    values, tags = _coerce_values(payload, ct)
    try:
        db.create_record(_cfg(), ct, values, tags or [])
    except psycopg.Error as exc:
        raise HTTPException(400, _db_error(exc))
    # The configured INSERT doesn't return ids, so look up by slug if present.
    created = None
    slug = values.get("slug")
    if slug:
        rows = [r for r in db.list_records(_cfg(), ct) if r.get("slug") == slug]
        if rows:
            created = db.get_record(_cfg(), ct, rows[0]["id"])
    # Fire the same auto-publish debounce the form handler uses.
    from .main import schedule_autopublish
    schedule_autopublish(values)
    return {"created": created or values}


@router.patch("/c/{name}/{record_id}", dependencies=[Depends(require_token)])
def update_record(
    name: str, record_id: int, payload: dict = Body(...)
) -> dict:
    ct = _ct(name)
    values, tags = _coerce_values(payload, ct)
    try:
        db.update_record(_cfg(), ct, record_id, values, tags)
    except psycopg.Error as exc:
        raise HTTPException(400, _db_error(exc))
    from .main import schedule_autopublish
    schedule_autopublish(values)
    row = db.get_record(_cfg(), ct, record_id)
    if row is None:
        raise HTTPException(404)
    return row


@router.delete(
    "/c/{name}/{record_id}",
    status_code=204,
    dependencies=[Depends(require_token)],
)
def delete_record(name: str, record_id: int) -> None:
    ct = _ct(name)
    try:
        db.delete_record(_cfg(), ct, record_id)
    except psycopg.Error as exc:
        raise HTTPException(400, _db_error(exc))


@router.post(
    "/c/{name}/{record_id}/syndicate",
    dependencies=[Depends(require_token)],
)
def syndicate(
    name: str, record_id: int, payload: dict = Body(default={}),
) -> dict:
    ct = _ct(name)
    record = db.get_record(_cfg(), ct, record_id)
    if record is None:
        raise HTTPException(404)
    text = (payload.get("text") or "").strip()
    if not text:
        tags = record.get("tags", []) if ct.has_tags else []
        text = build_status_text(ct.name, record, tags)
    want_masto = bool(payload.get("mastodon"))
    want_bsky = bool(payload.get("bluesky"))
    if not (want_masto or want_bsky):
        raise HTTPException(400, "Set `mastodon: true` and/or `bluesky: true`.")

    from .main import _pick_image
    image_url, alt = _pick_image(ct.name, record)
    out: dict = {"mastodon": None, "bluesky": None, "errors": {}}

    if want_masto:
        if record.get("mastodon_url"):
            out["mastodon"] = {"url": record["mastodon_url"], "skipped": True}
        else:
            try:
                m = post_status(_cfg(), text, image_url=image_url, image_alt=alt)
                db.set_mastodon_url(_cfg(), ct, record_id, m["url"])
                out["mastodon"] = m
            except MastodonError as exc:
                out["errors"]["mastodon"] = str(exc)

    if want_bsky:
        if record.get("bluesky_url"):
            out["bluesky"] = {"url": record["bluesky_url"], "skipped": True}
        else:
            try:
                b = post_to_bluesky_api(
                    _cfg(), text, image_url=image_url, image_alt=alt,
                )
                if b.get("url"):
                    db.set_bluesky_url(_cfg(), ct, record_id, b["url"])
                out["bluesky"] = b
            except BlueskyError as exc:
                out["errors"]["bluesky"] = str(exc)

    return out


@router.post("/publish", dependencies=[Depends(require_token)])
def publish() -> dict:
    try:
        trigger_publish(_cfg())
    except GitHubError as exc:
        raise HTTPException(502, str(exc))
    from .main import _mark_publish_dispatched
    _mark_publish_dispatched()
    return {"dispatched": True}


def _db_error(exc: psycopg.Error) -> str:
    diag = getattr(exc, "diag", None)
    if diag is not None and getattr(diag, "message_primary", None):
        return diag.message_primary
    return str(exc).splitlines()[0] if str(exc) else "Database error."
