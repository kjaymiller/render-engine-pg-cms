"""FastAPI CMS for render-engine PostgreSQL content."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt

from . import db
from .config import Config, ContentType, load_config
from .github import GitHubError, trigger_publish
from .bluesky import BlueskyError, post_status as post_to_bluesky_api
from .mastodon import (
    MastodonError,
    build_alt_text,
    build_status_text,
    post_status,
)
from .webmention import WebmentionError, sync_record as sync_webmention_record

load_dotenv()

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

_md = MarkdownIt("commonmark", {"breaks": True, "linkify": True})
templates.env.filters["md"] = lambda s: _md.render(s or "")

app = FastAPI(title="render-engine-pg-cms")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

SKIP_COLUMNS = {"id", "created_at", "updated_at"}
# Columns we treat as required when present on a content type.
LIKELY_REQUIRED = {"slug", "title", "name", "content"}

_config: Config | None = None


def cfg() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _ct(name: str) -> ContentType:
    c = cfg()
    if name not in c.content_types:
        raise HTTPException(404, f"Unknown content type: {name}")
    return c.content_types[name]


def _render_edit(
    request: Request,
    ct: ContentType,
    record: dict,
    tags: list[str],
    is_new: bool,
    errors: dict[str, str] | None = None,
    form_error: str | None = None,
    flash: str | None = None,
    flash_level: str = "ok",
    status_code: int = 200,
):
    can_syndicate = ct.name in ("microblog", "blog")
    has_mastodon = (
        not is_new and can_syndicate and bool(cfg().mastodon_instance)
    )
    has_bluesky = (
        not is_new
        and can_syndicate
        and bool(cfg().bluesky_handle and cfg().bluesky_app_password)
    )
    return templates.TemplateResponse(
        request,
        "edit.html",
        {
            "ct": ct,
            "record": record,
            "tags": tags,
            "is_new": is_new,
            "errors": errors or {},
            "form_error": form_error,
            "flash": flash,
            "flash_level": flash_level,
            "has_mastodon": has_mastodon,
            "has_bluesky": has_bluesky,
        },
        status_code=status_code,
    )


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    url: str = "",
    title: str = "",
    page: int = 1,
    per: int = 25,
):
    page = max(1, page)
    per = max(5, min(per, 100))
    # Only include types with temporal content on the timeline.
    timeline_types = [
        n for n in ("microblog", "blog", "notes")
        if n in cfg().content_types
    ]
    all_rows = db.list_timeline(cfg(), timeline_types)
    total = len(all_rows)
    pages = max(1, (total + per - 1) // per)
    page = min(page, pages)
    start = (page - 1) * per
    rows = all_rows[start:start + per]
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "content_types": cfg().content_types,
            "url": url,
            "title": title,
            "rows": rows,
            "page": page,
            "pages": pages,
            "per": per,
            "total": total,
            "timeline_types": timeline_types,
            "mastodon_enabled": bool(cfg().mastodon_instance),
            "bluesky_enabled": bool(
                cfg().bluesky_handle and cfg().bluesky_app_password
            ),
        },
    )


@app.get("/api/geocode")
def geocode(q: str):
    """Free-text → lat/lon via OpenStreetMap Nominatim.

    Expects a comma-joined city/region/country query. Returns the first
    match as {display_name, lat, lon}. 404 if nothing found.
    """
    import httpx
    q = (q or "").strip()
    if not q:
        return JSONResponse({"error": "empty query"}, status_code=400)
    headers = {"User-Agent": "render-engine-pg-cms/0.1 (personal cms)"}
    try:
        with httpx.Client(timeout=8.0, headers=headers) as client:
            r = client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": q, "format": "json", "limit": 1,
                        "addressdetails": 1},
            )
            r.raise_for_status()
            hits = r.json()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    if not hits:
        return JSONResponse({"error": "no match"}, status_code=404)
    h = hits[0]
    return {
        "display_name": h.get("display_name", q),
        "lat": float(h["lat"]),
        "lon": float(h["lon"]),
    }


@app.get("/c/{name}", response_class=HTMLResponse)
def list_view(request: Request, name: str, msg: str | None = None, level: str = "ok"):
    ct = _ct(name)
    records = db.list_records(cfg(), ct)
    can_syndicate = ct.name in ("microblog", "blog")
    mastodon_enabled = can_syndicate and bool(cfg().mastodon_instance)
    bluesky_enabled = can_syndicate and bool(
        cfg().bluesky_handle and cfg().bluesky_app_password
    )
    return templates.TemplateResponse(
        request,
        "list.html",
        {
            "ct": ct,
            "records": records,
            "flash": msg,
            "flash_level": level,
            "mastodon_enabled": mastodon_enabled,
            "bluesky_enabled": bluesky_enabled,
            "syndication_enabled": mastodon_enabled or bluesky_enabled,
        },
    )


@app.get("/quick")
def quick_picker(url: str = "", title: str = ""):
    params = urlencode({k: v for k, v in {"url": url, "title": title}.items() if v})
    return RedirectResponse(f"/?{params}" if params else "/", status_code=303)


@app.get("/c/{name}/new", response_class=HTMLResponse)
def new_form(request: Request, name: str, url: str = "", title: str = ""):
    ct = _ct(name)
    record: dict = {}
    if url and "external_link" in ct.primary_columns:
        record["external_link"] = url
    if title and "title" in ct.primary_columns:
        record["title"] = title
    if "slug" in ct.primary_columns:
        slug_src = title or (urlparse(url).hostname if url else "")
        if slug_src:
            record["slug"] = _slugify(slug_src)
    if "date" in ct.primary_columns and "date" not in record:
        record["date"] = datetime.now()
    return _render_edit(request, ct, record=record, tags=[], is_new=True)


@app.post("/c/{name}/new")
async def create(request: Request, name: str):
    ct = _ct(name)
    form = await request.form()
    values, tags, errors = _extract(form, ct)
    if errors:
        return _render_edit(
            request, ct, record=values, tags=tags, is_new=True,
            errors=errors, status_code=400,
        )
    try:
        db.create_record(cfg(), ct, values, tags)
    except psycopg.Error as exc:
        return _render_edit(
            request, ct, record=values, tags=tags, is_new=True,
            form_error=_db_error_message(exc), status_code=400,
        )
    return RedirectResponse(
        f"/c/{name}?msg=Created&level=ok", status_code=303
    )


@app.get("/c/{name}/{record_id}", response_class=HTMLResponse)
def edit_form(
    request: Request,
    name: str,
    record_id: int,
    msg: str | None = None,
    level: str = "ok",
):
    ct = _ct(name)
    record = db.get_record(cfg(), ct, record_id)
    if record is None:
        raise HTTPException(404)
    tags = record.pop("tags", []) if ct.has_tags else []
    return _render_edit(
        request, ct, record=record, tags=tags, is_new=False,
        flash=msg, flash_level=level,
    )


@app.post("/c/{name}/{record_id}")
async def update(request: Request, name: str, record_id: int):
    ct = _ct(name)
    form = await request.form()
    values, tags, errors = _extract(form, ct)
    if errors:
        values_with_id = {**values, "id": record_id}
        return _render_edit(
            request, ct, record=values_with_id, tags=tags, is_new=False,
            errors=errors, status_code=400,
        )
    try:
        db.update_record(
            cfg(), ct, record_id, values, tags if ct.has_tags else None
        )
    except psycopg.Error as exc:
        values_with_id = {**values, "id": record_id}
        return _render_edit(
            request, ct, record=values_with_id, tags=tags, is_new=False,
            form_error=_db_error_message(exc), status_code=400,
        )
    return RedirectResponse(
        f"/c/{name}?msg=Saved&level=ok", status_code=303
    )


@app.post("/c/{name}/{record_id}/delete")
def delete(name: str, record_id: int):
    ct = _ct(name)
    try:
        db.delete_record(cfg(), ct, record_id)
    except psycopg.Error as exc:
        return RedirectResponse(
            f"/c/{name}?msg={_db_error_message(exc)}&level=err",
            status_code=303,
        )
    return RedirectResponse(
        f"/c/{name}?msg=Deleted&level=ok", status_code=303
    )


@app.post("/c/{name}/{record_id}/mastodon")
def post_to_mastodon(name: str, record_id: int):
    ct = _ct(name)
    if "mastodon_url" not in _columns(cfg(), ct):
        return _flash_redirect(
            name, "This content type has no mastodon_url column.", "err"
        )
    record = db.get_record(cfg(), ct, record_id)
    if record is None:
        raise HTTPException(404)
    if record.get("mastodon_url"):
        return _flash_redirect(
            name,
            f"Already posted: {record['mastodon_url']}",
            "err",
            record_id=record_id,
        )
    tags = record.get("tags", []) if ct.has_tags else []
    text = build_status_text(ct.name, record, tags)
    image_url, alt = _pick_image(ct.name, record)
    if not text.strip() and not image_url:
        return _flash_redirect(
            name, "Nothing to post — record has no content or image.", "err",
            record_id=record_id,
        )
    try:
        result = post_status(
            cfg(), text, image_url=image_url, image_alt=alt,
        )
    except MastodonError as exc:
        return _flash_redirect(name, str(exc), "err", record_id=record_id)
    db.set_mastodon_url(cfg(), ct, record_id, result["url"])
    return _flash_redirect(
        name, f"Posted to Mastodon: {result['url']}", "ok",
        record_id=record_id,
    )


@app.post("/c/{name}/{record_id}/bluesky")
def post_to_bluesky(name: str, record_id: int):
    ct = _ct(name)
    if "bluesky_url" not in _columns(cfg(), ct):
        return _flash_redirect(
            name, "This content type has no bluesky_url column.", "err"
        )
    record = db.get_record(cfg(), ct, record_id)
    if record is None:
        raise HTTPException(404)
    if record.get("bluesky_url"):
        return _flash_redirect(
            name, f"Already posted to Bluesky: {record['bluesky_url']}", "err",
            record_id=record_id,
        )
    tags = record.get("tags", []) if ct.has_tags else []
    text = build_status_text(ct.name, record, tags)
    image_url, alt = _pick_image(ct.name, record)
    if not text.strip() and not image_url:
        return _flash_redirect(
            name, "Nothing to post — record has no content or image.", "err",
            record_id=record_id,
        )
    try:
        result = post_to_bluesky_api(
            cfg(), text, image_url=image_url, image_alt=alt,
        )
    except BlueskyError as exc:
        return _flash_redirect(name, str(exc), "err", record_id=record_id)
    if result.get("url"):
        db.set_bluesky_url(cfg(), ct, record_id, result["url"])
    return _flash_redirect(
        name, f"Posted to Bluesky: {result.get('url', result.get('uri'))}", "ok",
        record_id=record_id,
    )


@app.post("/c/{name}/{record_id}/syndicate")
def post_to_both(name: str, record_id: int):
    ct = _ct(name)
    cols = _columns(cfg(), ct)
    if "mastodon_url" not in cols or "bluesky_url" not in cols:
        return _flash_redirect(
            name,
            "This content type is missing mastodon_url or bluesky_url.",
            "err",
            record_id=record_id,
        )
    record = db.get_record(cfg(), ct, record_id)
    if record is None:
        raise HTTPException(404)
    tags = record.get("tags", []) if ct.has_tags else []
    text = build_status_text(ct.name, record, tags)
    image_url, alt = _pick_image(ct.name, record)
    if not text.strip() and not image_url:
        return _flash_redirect(
            name, "Nothing to post — record has no content or image.", "err",
            record_id=record_id,
        )

    results: list[str] = []
    errors: list[str] = []

    if record.get("mastodon_url"):
        results.append(f"Mastodon already posted: {record['mastodon_url']}")
    else:
        try:
            m = post_status(cfg(), text, image_url=image_url, image_alt=alt)
            db.set_mastodon_url(cfg(), ct, record_id, m["url"])
            results.append(f"Mastodon: {m['url']}")
        except MastodonError as exc:
            errors.append(f"Mastodon: {exc}")

    if record.get("bluesky_url"):
        results.append(f"Bluesky already posted: {record['bluesky_url']}")
    else:
        try:
            b = post_to_bluesky_api(
                cfg(), text, image_url=image_url, image_alt=alt,
            )
            if b.get("url"):
                db.set_bluesky_url(cfg(), ct, record_id, b["url"])
            results.append(f"Bluesky: {b.get('url', b.get('uri'))}")
        except BlueskyError as exc:
            errors.append(f"Bluesky: {exc}")

    msg = " · ".join(results + errors) or "Nothing happened."
    level = "err" if errors and not results else "ok"
    return _flash_redirect(name, msg, level, record_id=record_id)


@app.post("/c/{name}/{record_id}/webmentions/sync")
def sync_webmentions(name: str, record_id: int):
    ct = _ct(name)
    record = db.get_record(cfg(), ct, record_id)
    if record is None:
        raise HTTPException(404)
    try:
        count, target = sync_webmention_record(cfg(), ct, record)
    except WebmentionError as exc:
        return _flash_redirect(name, str(exc), "err", record_id=record_id)
    return _flash_redirect(
        name, f"Webmentions: {count} ({target})", "ok", record_id=record_id,
    )


def _columns(config, ct) -> set[str]:
    """Inspect the live table to see if optional columns (mastodon_url) exist."""
    with psycopg.connect(config.connection_string) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = %(t)s
            """,
            {"t": ct.table},
        )
        return {row[0] for row in cur.fetchall()}


def _flash_redirect(
    name: str, msg: str, level: str, record_id: int | None = None
) -> RedirectResponse:
    params = urlencode({"msg": msg, "level": level})
    target = f"/c/{name}/{record_id}" if record_id else f"/c/{name}"
    return RedirectResponse(f"{target}?{params}", status_code=303)


@app.post("/publish", response_class=HTMLResponse)
def publish(request: Request):
    try:
        trigger_publish(cfg())
        message = f"Dispatched {cfg().github_workflow} on {cfg().github_repo}@{cfg().github_ref}."
        ok = True
    except GitHubError as exc:
        message = str(exc)
        ok = False
    return templates.TemplateResponse(
        request,
        "publish_result.html",
        {"message": message, "ok": ok},
    )


def _extract(form, ct: ContentType) -> tuple[dict, list[str], dict[str, str]]:
    values: dict = {}
    errors: dict[str, str] = {}
    for col in ct.primary_columns:
        if col in SKIP_COLUMNS:
            continue
        raw = form.get(col)
        raw = raw.strip() if isinstance(raw, str) else raw
        if col == "date" and raw:
            try:
                values[col] = datetime.fromisoformat(raw)
            except ValueError:
                errors[col] = "Invalid date/time."
                values[col] = raw
            continue
        if not raw:
            values[col] = None
            if col in LIKELY_REQUIRED:
                errors[col] = "Required."
            continue
        values[col] = raw
    tags_raw = form.get("tags", "") or ""
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    return values, tags, errors


_MD_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
_HTML_IMG_RE = re.compile(
    r"<img\b[^>]*?\bsrc=[\"'](?P<url>[^\"']+)[\"']"
    r"(?:[^>]*?\balt=[\"'](?P<alt>[^\"']*)[\"'])?",
    re.IGNORECASE,
)


def _first_content_image(content: str) -> tuple[str, str] | None:
    """Return (url, alt) of the first markdown or HTML image in content."""
    if not content:
        return None
    m = _MD_IMAGE_RE.search(content)
    h = _HTML_IMG_RE.search(content)
    # pick whichever comes first in the text
    candidates = [c for c in (m, h) if c is not None]
    if not candidates:
        return None
    first = min(candidates, key=lambda x: x.start())
    return first.group("url"), (first.group("alt") or "")


def _pick_image(ct_name: str, record: dict) -> tuple[str | None, str]:
    """Prefer image_url; fall back to the first image embedded in content."""
    url = record.get("image_url") or None
    if url:
        return url, build_alt_text(ct_name, record)
    found = _first_content_image(record.get("content") or "")
    if found:
        url, alt = found
        return url, alt or build_alt_text(ct_name, record)
    return None, ""


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:80]


def _db_error_message(exc: psycopg.Error) -> str:
    diag = getattr(exc, "diag", None)
    if diag is not None and getattr(diag, "message_primary", None):
        return diag.message_primary
    return str(exc).splitlines()[0] if str(exc) else "Database error."
