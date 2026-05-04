"""FastAPI CMS for render-engine PostgreSQL content."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt

from . import db
from .config import Config, ContentType, load_config
from .github import GitHubError, latest_run as github_latest_run, trigger_publish
from .bluesky import BlueskyError, post_status as post_to_bluesky_api
from .mastodon import (
    MastodonError,
    build_alt_text,
    build_status_text,
    post_status,
)
from .webmention import (
    WebmentionError,
    build_target_url as build_webmention_target_url,
    last_sync_time as webmention_last_sync_time,
    list_targets as list_webmention_targets,
    sync_all as sync_all_webmentions,
    sync_record as sync_webmention_record,
)
from .azure_blob import AzureUploadError, upload_bytes as upload_to_azure
from .azure_blob import _slugify as _slugify_loose
from .image_optimize import optimize as optimize_image
from .ollama import (
    OllamaError,
    suggest_slug as ollama_suggest_slug,
    suggest_description as ollama_suggest_description,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("render_engine_pg_cms")

load_dotenv()

BASE_DIR = Path(__file__).parent


def _inject_content_types(request: Request) -> dict:
    return {"content_types": cfg().content_types}


templates = Jinja2Templates(
    directory=BASE_DIR / "templates",
    context_processors=[_inject_content_types],
)

_md = MarkdownIt("commonmark", {"breaks": True, "linkify": True})
templates.env.filters["md"] = lambda s: _md.render(s or "")

WEBMENTION_SYNC_INTERVAL = int(os.environ.get("WEBMENTION_SYNC_INTERVAL", "21600"))
# Auto-loop only touches posts within this many days. Old posts rarely pick
# up new mentions; the manual "Sync now" button still hits every record.
# Set to 0 to disable the filter and let the loop sync everything.
WEBMENTION_AUTO_MAX_AGE_DAYS = int(
    os.environ.get("WEBMENTION_AUTO_MAX_AGE_DAYS", "60")
)

# Trailing-edge debounce on auto-publish after a record create/update.
# Rapid-fire saves within this window collapse into a single workflow run.
AUTOPUBLISH_DEBOUNCE_SECONDS = float(
    os.environ.get("AUTOPUBLISH_DEBOUNCE_SECONDS", "60")
)
AUTOPUBLISH_ENABLED = os.environ.get("AUTOPUBLISH", "1") not in ("0", "false", "no")
_pending_publish_task: "asyncio.Task | None" = None

# Timestamp (UTC, ISO) of the last publish dispatch from this process.
# Lets the status endpoint report "running" during the gap between dispatch
# and GitHub surfacing the new run in its listing.
_last_publish_dispatched_at: str | None = None


def _record_is_live(record: dict) -> bool:
    """A record is "live" (worth publishing) when its `date` is in the past
    AND it's not flagged as a draft.

    Records without a `date` column are treated as live — that covers types
    like 'conferences' or anything else the user manages through the CMS
    where temporal gating doesn't apply.
    """
    if record.get("draft"):
        return False
    d = record.get("date")
    if d is None:
        return True
    try:
        # Compare as naive when the value is naive, tz-aware otherwise.
        if hasattr(d, "tzinfo") and d.tzinfo is not None:
            from datetime import timezone as _tz
            return d <= datetime.now(_tz.utc)
        return d <= datetime.utcnow()
    except TypeError:
        # Unrecognized date shape — don't block autopublish.
        return True


async def _dispatch_autopublish() -> None:
    """Wait out the debounce window, then fire the publish workflow."""
    try:
        await asyncio.sleep(AUTOPUBLISH_DEBOUNCE_SECONDS)
    except asyncio.CancelledError:
        return
    try:
        await asyncio.to_thread(trigger_publish, cfg())
        _mark_publish_dispatched()
        log.info("auto-publish dispatched after save(s)")
    except GitHubError as exc:
        log.warning("auto-publish failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("auto-publish raised: %s", exc)


def schedule_autopublish(record: dict) -> None:
    """Kick (or reset) the trailing-debounce publish timer.

    Multiple saves in quick succession collapse into one workflow run at the
    end of the last save's 60-second cooldown. No-op for drafts (future
    `date`), for content types without a date column it runs freely, and
    when GitHub isn't configured.
    """
    global _pending_publish_task
    if not AUTOPUBLISH_ENABLED:
        return
    if not (cfg().github_token and cfg().github_repo):
        return
    if not _record_is_live(record):
        return
    # Cancel any outstanding timer — later saves push the publish further.
    if _pending_publish_task and not _pending_publish_task.done():
        _pending_publish_task.cancel()
    _pending_publish_task = asyncio.create_task(_dispatch_autopublish())

# In-memory status for the UI. Not persisted across restarts — acceptable for
# an admin tool; on restart the next auto-run repopulates it.
_sync_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "trigger": None,      # "auto" | "manual"
    "total_expected": 0,  # set upfront once we know how many rows to hit
    "processed": 0,       # increments per record as the sync progresses
    "results": [],        # appended as each record finishes
    "last_update": None,  # ISO ts; bumped on every per-record callback
    "error": None,
}
_sync_lock = asyncio.Lock()


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _run_sync_blocking(trigger: str) -> None:
    """Blocking sync used by both the auto-loop and manual triggers.

    Updates _sync_state in place as each record finishes so the UI can show
    live per-mention progress. Safe to call from a worker thread —
    the dict mutation here is fine for single-writer admin use.
    """
    _sync_state.update(
        running=True,
        started_at=_now_iso(),
        finished_at=None,
        trigger=trigger,
        error=None,
        processed=0,
        total_expected=0,
        results=[],
        last_update=_now_iso(),
    )
    try:
        def on_start(total: int) -> None:
            _sync_state["total_expected"] = total
            _sync_state["last_update"] = _now_iso()

        def on_record(entry: dict) -> None:
            _sync_state["results"].append(entry)
            _sync_state["processed"] = len(_sync_state["results"])
            _sync_state["last_update"] = _now_iso()

        # Auto-runs restrict to recent posts to avoid rate-limiting on every
        # cycle; manual runs (triggered from the UI) hit every record.
        max_age = (
            WEBMENTION_AUTO_MAX_AGE_DAYS or None
            if trigger == "auto" else None
        )
        sync_all_webmentions(
            cfg(), max_age_days=max_age,
            on_start=on_start, on_record=on_record,
        )
        ok = sum(1 for r in _sync_state["results"] if r["error"] is None)
        log.info(
            "webmention sync (%s): %d/%d refreshed",
            trigger, ok, len(_sync_state["results"]),
        )
    except Exception as exc:
        _sync_state["error"] = str(exc)
        log.warning("webmention sync (%s) failed: %s", trigger, exc)
    finally:
        _sync_state["running"] = False
        _sync_state["finished_at"] = _now_iso()


async def _sync_now(trigger: str) -> bool:
    """Run one sync cycle if none is in flight. Returns True if it ran."""
    if _sync_lock.locked():
        return False
    async with _sync_lock:
        await asyncio.to_thread(_run_sync_blocking, trigger)
    return True


async def _webmention_sync_loop() -> None:
    """Periodically refresh webmention counts for every syndicated record.

    Interval is controlled by WEBMENTION_SYNC_INTERVAL (seconds; 0 disables).

    On startup, looks at the latest `webmentions_synced_at` in the DB so a
    restart after a recent sync doesn't stampede webmention.io. We only wait
    out the remainder of the interval (not a full cycle) — so the first sync
    happens `max(0, interval - elapsed_since_last)` seconds after startup.
    """
    # Compute startup delay from on-disk state.
    initial_delay = 0.0
    try:
        last = await asyncio.to_thread(webmention_last_sync_time, cfg())
    except Exception as exc:  # noqa: BLE001
        log.warning("couldn't determine last sync time: %s", exc)
        last = None
    if last is not None:
        from datetime import timezone as _tz
        now = datetime.now(_tz.utc) if last.tzinfo else datetime.utcnow()
        try:
            elapsed = (now - last).total_seconds()
        except TypeError:
            elapsed = float(WEBMENTION_SYNC_INTERVAL)  # mismatched tz — run now
        initial_delay = max(0.0, WEBMENTION_SYNC_INTERVAL - elapsed)
        if initial_delay > 0:
            log.info(
                "deferring first webmention sync: last run %ds ago, waiting %ds",
                int(elapsed), int(initial_delay),
            )

    if initial_delay > 0:
        try:
            await asyncio.sleep(initial_delay)
        except asyncio.CancelledError:
            raise

    while True:
        try:
            await _sync_now("auto")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("webmention sync failed: %s", exc)
        await asyncio.sleep(WEBMENTION_SYNC_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task: asyncio.Task | None = None
    if WEBMENTION_SYNC_INTERVAL > 0 and cfg().webmention_io_token:
        task = asyncio.create_task(_webmention_sync_loop())
        log.info(
            "webmention background sync started (every %ds)",
            WEBMENTION_SYNC_INTERVAL,
        )
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="render-engine-pg-cms", lifespan=lifespan)
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


def _social_context(
    ct_name: str, record: dict, tags: list[str],
) -> tuple[str, str | None, str, str]:
    """Compute the publish-to-social modal inputs for a record.

    Returns (draft_text, image_url, image_alt, canonical_url). canonical_url
    is empty when site_base_url or slug isn't configured — the UI hides the
    "append URL" checkbox in that case.
    """
    draft = build_status_text(ct_name, record, tags)
    image_url, image_alt = _pick_image(ct_name, record)
    try:
        canonical = build_webmention_target_url(
            cfg(), ct_name, record.get("slug") or "",
        )
    except Exception:  # noqa: BLE001
        canonical = ""
    return draft, image_url, image_alt, canonical


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
    social_draft, social_image_url, social_image_alt, canonical_url = (
        _social_context(ct.name, record, tags)
        if (has_mastodon or has_bluesky) and record
        else ("", None, "", "")
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
            "social_draft": social_draft,
            "social_image_url": social_image_url,
            "social_image_alt": social_image_alt,
            "social_canonical_url": canonical_url,
            "masto_limit": 500,
            "bsky_limit": 300,
        },
        status_code=status_code,
    )


VALID_STATUSES = ("all", "published", "drafts", "scheduled")


def _annotate_scheduled(rows: list[dict]) -> None:
    """Tag rows with `_scheduled=True` when they're not drafts but have a
    publish `date` in the future. Used by the list templates to badge them.
    """
    from datetime import timezone as _tz
    now_aware = datetime.now(_tz.utc)
    now_naive = datetime.utcnow()
    for r in rows:
        d = r.get("date")
        if not d or r.get("draft"):
            r["_scheduled"] = False
            continue
        try:
            ref = now_aware if (getattr(d, "tzinfo", None) is not None) else now_naive
            r["_scheduled"] = d > ref
        except TypeError:
            r["_scheduled"] = False


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    url: str = "",
    title: str = "",
    page: int = 1,
    per: int = 25,
    status: str = "all",
):
    page = max(1, page)
    per = max(5, min(per, 100))
    if status not in VALID_STATUSES:
        status = "all"
    # Only include types with temporal content on the timeline.
    timeline_types = [
        n for n in ("microblog", "blog", "notes")
        if n in cfg().content_types
    ]
    # Aggregate counts across timeline types for the status tabs.
    status_counts = {k: 0 for k in VALID_STATUSES}
    for n in timeline_types:
        per_type = db.count_by_status(cfg(), cfg().content_types[n])
        for k, v in per_type.items():
            status_counts[k] = status_counts.get(k, 0) + v
    all_rows = db.list_timeline(cfg(), timeline_types, status=status)
    _annotate_scheduled(all_rows)
    total = len(all_rows)
    pages = max(1, (total + per - 1) // per)
    page = min(page, pages)
    start = (page - 1) * per
    rows = all_rows[start:start + per]
    mastodon_enabled = bool(cfg().mastodon_instance)
    bluesky_enabled = bool(cfg().bluesky_handle and cfg().bluesky_app_password)
    # Annotate each timeline row with the same social-publish context the
    # single-record edit page uses, so the unified "Publish to social" modal
    # can be opened directly from the timeline. Tags aren't loaded for the
    # timeline (would be N extra queries per page), so the auto-draft skips
    # hashtags — the user can still type them in the modal.
    if mastodon_enabled or bluesky_enabled:
        for r in rows:
            if r["_type"] not in ("microblog", "blog"):
                continue
            draft, img, alt, canon = _social_context(r["_type"], r, [])
            r["_social_draft"] = draft
            r["_social_image_url"] = img
            r["_social_image_alt"] = alt
            r["_social_canonical_url"] = canon
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
            "status": status,
            "status_counts": status_counts,
            "mastodon_enabled": mastodon_enabled,
            "bluesky_enabled": bluesky_enabled,
            "masto_limit": 500,
            "bsky_limit": 300,
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


# Cap upload size to protect against runaway drops. 50 MiB covers ProRAW /
# 5K-screenshot territory with headroom. Note: the server downscales to
# MAX_EDGE_PX (2200) and re-encodes, so the *stored* blob is almost always
# <500 KB regardless of what gets uploaded.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    """Accept a single image file and persist it to Azure Blob Storage.

    Returns {url, filename, content_type, size}. The caller places the
    returned `url` wherever it wants (image_url input, markdown textarea).
    """
    if not cfg().azure_storage_container and not cfg().azure_storage_connection_string:
        return JSONResponse(
            {"error": "Azure storage is not configured on this server."},
            status_code=503,
        )
    content_type = (file.content_type or "").lower()
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        return JSONResponse(
            {"error": f"File too large ({len(raw)} bytes). Max {MAX_UPLOAD_BYTES}."},
            status_code=413,
        )

    # Downscale + re-encode off the event loop so we don't block other requests
    # while Pillow churns on a 20MP photo.
    try:
        data, new_content_type = await asyncio.to_thread(
            optimize_image, raw, content_type
        )
    except Exception as exc:  # noqa: BLE001 — optimization is best-effort
        log.warning("image optimize failed (%s); uploading original", exc)
        data, new_content_type = raw, content_type

    try:
        url = await asyncio.to_thread(
            upload_to_azure, cfg(), data, new_content_type, file.filename,
        )
    except AzureUploadError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        log.exception("azure upload failed")
        return JSONResponse({"error": f"Upload failed: {exc}"}, status_code=502)

    return {
        "url": url,
        "filename": file.filename,
        "content_type": new_content_type,
        "original_content_type": content_type,
        "size": len(data),
        "original_size": len(raw),
        "saved_bytes": max(0, len(raw) - len(data)),
    }


@app.post("/api/ai/slug")
async def ai_suggest_slug(text: str = Form(...)):
    """Ask the local Ollama server for a URL slug for `text`.

    Returns {slug, source}. `source` is "ai" when the model answered
    successfully, "fallback" when we fell back to rule-based slugify —
    that way the UI can tell the user why they got what they got.
    """
    clean_input = (text or "").strip()
    if not clean_input:
        return JSONResponse({"error": "empty input"}, status_code=400)
    try:
        raw = await asyncio.to_thread(ollama_suggest_slug, cfg(), clean_input)
    except OllamaError as exc:
        log.info("ollama slug failed (%s); using fallback", exc)
        return {"slug": _slugify_loose(clean_input)[:80], "source": "fallback", "error": str(exc)}
    slug = _slugify_loose(raw)[:80]
    # Belt-and-braces: if the model returned something that normalized to
    # empty (e.g. just punctuation), fall back rather than return "".
    if not slug:
        return {"slug": _slugify_loose(clean_input)[:80], "source": "fallback",
                "error": "model returned unusable output"}
    return {"slug": slug, "source": "ai"}


@app.post("/api/ai/description")
async def ai_suggest_description(text: str = Form(...)):
    """Generate a one-sentence summary of `text` via Ollama for use as a
    description / excerpt. Returns {description, source}. `source` is "ai"
    on success or "error" if Ollama failed (the field is left empty so
    the user can write their own).
    """
    clean_input = (text or "").strip()
    if not clean_input:
        return JSONResponse({"error": "empty input"}, status_code=400)
    try:
        summary = await asyncio.to_thread(
            ollama_suggest_description, cfg(), clean_input,
        )
    except OllamaError as exc:
        log.warning("ollama description failed: %s", exc)
        return JSONResponse(
            {"error": str(exc), "source": "error", "description": ""},
            status_code=503,
        )
    if not summary:
        return JSONResponse(
            {"error": "model returned empty output", "source": "error",
             "description": ""},
            status_code=503,
        )
    return {"description": summary, "source": "ai"}


def _normalize_tag(raw: str) -> str:
    """Lowercase, trim, collapse whitespace to single hyphens. Keeps existing
    multi-word tags looking consistent with the "hyphen-separated" style."""
    s = (raw or "").strip().lower()
    # Drop quotes, leading/trailing punctuation noise the model might emit.
    s = s.strip('"').strip("'").strip(".")
    # Collapse runs of whitespace/underscores to a single hyphen, keep
    # existing hyphens and alphanumerics.
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


@app.post("/api/ai/tags")
async def ai_suggest_tags(text: str = Form(...)):
    """Suggest tags by fuzzy-matching the post text against the existing
    tag library (pg_trgm word_similarity). All suggestions are existing
    library tags, so `known` is always true. Endpoint name kept for
    backward compat with the frontend.
    """
    clean_input = (text or "").strip()
    if not clean_input:
        return JSONResponse({"error": "empty input"}, status_code=400)

    try:
        names = await asyncio.to_thread(
            db.suggest_tags_from_text, cfg(), clean_input, 8,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("tag suggestion failed: %s", exc, exc_info=True)
        return JSONResponse(
            {"error": str(exc), "source": "error", "suggestions": []},
            status_code=500,
        )

    out = [{"tag": n, "known": True} for n in names]
    return {"suggestions": out, "source": "library"}


@app.get("/api/tags/complete")
async def tag_complete(q: str = ""):
    """Autocomplete endpoint for the tag input. Returns up to 8 existing
    tag names that start with `q` (case-insensitive)."""
    try:
        names = await asyncio.to_thread(db.complete_tag, cfg(), q, 8)
    except Exception as exc:  # noqa: BLE001
        log.warning("tag complete failed: %s", exc, exc_info=True)
        return JSONResponse({"matches": []}, status_code=500)
    return {"matches": names}


@app.get("/c/{name}", response_class=HTMLResponse)
def list_view(
    request: Request,
    name: str,
    msg: str | None = None,
    level: str = "ok",
    status: str = "all",
):
    ct = _ct(name)
    if status not in VALID_STATUSES:
        status = "all"
    status_counts = db.count_by_status(cfg(), ct)
    records = db.list_records(cfg(), ct, status=status)
    _annotate_scheduled(records)
    can_syndicate = ct.name in ("microblog", "blog")
    mastodon_enabled = can_syndicate and bool(cfg().mastodon_instance)
    bluesky_enabled = can_syndicate and bool(
        cfg().bluesky_handle and cfg().bluesky_app_password
    )
    # Annotate records with the social-publish context so the unified
    # `publish_social_modal` macro can render in-place. Tags are skipped
    # to avoid an N+1 query per row; the user can add hashtags in the modal.
    if can_syndicate and (mastodon_enabled or bluesky_enabled):
        for r in records:
            draft, img, alt, canon = _social_context(ct.name, r, [])
            r["_social_draft"] = draft
            r["_social_image_url"] = img
            r["_social_image_alt"] = alt
            r["_social_canonical_url"] = canon
    return templates.TemplateResponse(
        request,
        "list.html",
        {
            "ct": ct,
            "records": records,
            "status": status,
            "status_counts": status_counts,
            "flash": msg,
            "flash_level": level,
            "mastodon_enabled": mastodon_enabled,
            "bluesky_enabled": bluesky_enabled,
            "syndication_enabled": mastodon_enabled or bluesky_enabled,
            "masto_limit": 500,
            "bsky_limit": 300,
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
    schedule_autopublish(values)
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
    schedule_autopublish(values)
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
def publish_social(
    name: str,
    record_id: int,
    text: str = Form(""),
    post_mastodon: str = Form(""),
    post_bluesky: str = Form(""),
):
    ct = _ct(name)
    cols = _columns(cfg(), ct)
    record = db.get_record(cfg(), ct, record_id)
    if record is None:
        raise HTTPException(404)

    want_mastodon = bool(post_mastodon) and "mastodon_url" in cols
    want_bluesky = bool(post_bluesky) and "bluesky_url" in cols
    if not (want_mastodon or want_bluesky):
        return _flash_redirect(
            name, "Pick at least one network to publish to.", "err",
            record_id=record_id,
        )

    text = (text or "").strip()
    image_url, alt = _pick_image(ct.name, record)
    if not text and not image_url:
        return _flash_redirect(
            name, "Nothing to post — draft is empty and no image attached.",
            "err", record_id=record_id,
        )

    results: list[str] = []
    errors: list[str] = []

    if want_mastodon:
        if record.get("mastodon_url"):
            results.append(f"Mastodon already posted: {record['mastodon_url']}")
        else:
            try:
                m = post_status(cfg(), text, image_url=image_url, image_alt=alt)
                db.set_mastodon_url(cfg(), ct, record_id, m["url"])
                results.append(f"Mastodon: {m['url']}")
            except MastodonError as exc:
                errors.append(f"Mastodon: {exc}")

    if want_bluesky:
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
        count, target, types = sync_webmention_record(cfg(), ct, record)
    except WebmentionError as exc:
        return _flash_redirect(name, str(exc), "err", record_id=record_id)
    breakdown = ", ".join(f"{k}:{v}" for k, v in sorted(types.items())) or "none"
    return _flash_redirect(
        name,
        f"Webmentions: {count} ({breakdown}) · {target}",
        "ok",
        record_id=record_id,
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


@app.post("/webmentions/sync")
async def trigger_webmention_sync(request: Request):
    if not cfg().webmention_io_token:
        if request.headers.get("accept", "").startswith("application/json"):
            return JSONResponse({"ok": False, "error": "WEBMENTION_IO_TOKEN not set."}, status_code=400)
        return _flash_redirect("", "WEBMENTION_IO_TOKEN not set.", "err")
    if _sync_state["running"]:
        started = False
    else:
        asyncio.create_task(_sync_now("manual"))
        started = True
    if request.headers.get("accept", "").startswith("application/json"):
        return JSONResponse({"ok": True, "started": started, "running": True})
    referer = request.headers.get("referer") or "/webmentions"
    msg = "Webmention sync started." if started else "Sync already in progress."
    params = urlencode({"msg": msg, "level": "ok"})
    sep = "&" if "?" in referer else "?"
    return RedirectResponse(f"{referer}{sep}{params}", status_code=303)


@app.get("/webmentions/targets")
def webmention_targets():
    """List every syndicated record with the target URL we send to
    webmention.io. Use this to verify the URLs match your real post URLs —
    if they don't, bridgy's relayed mentions are being filed under the
    wrong key and your counts will stay at 0.
    """
    return JSONResponse({"targets": list_webmention_targets(cfg())})


@app.get("/webmentions/status")
def webmention_status(since: int = 0):
    """Live status. Pass ?since=N to only return results after index N —
    lets the UI stream per-record updates without re-sending the whole log.
    """
    s = _sync_state
    results = s["results"]
    summary = {
        "running": s["running"],
        "started_at": s["started_at"],
        "finished_at": s["finished_at"],
        "last_update": s["last_update"],
        "trigger": s["trigger"],
        "error": s["error"],
        "total_expected": s["total_expected"],
        "processed": s["processed"],
        "total": len(results),
        "ok": sum(1 for r in results if r["error"] is None),
        "failed": sum(1 for r in results if r["error"] is not None),
        "changed": sum(
            1 for r in results
            if r["error"] is None and r["count"] != r["prev"]
        ),
        "new": results[since:] if since < len(results) else [],
    }
    return JSONResponse(summary)


@app.get("/webmentions", response_class=HTMLResponse)
def webmention_log(request: Request):
    s = _sync_state
    results = s["results"]
    # Sort: changes first, then errors, then unchanged.
    def rank(r):
        if r["error"]:
            return 1
        if r["count"] != r["prev"]:
            return 0
        return 2
    sorted_results = sorted(results, key=rank)
    return templates.TemplateResponse(
        request,
        "webmentions.html",
        {
            "state": s,
            "results": sorted_results,
            "interval": WEBMENTION_SYNC_INTERVAL,
        },
    )


def _mark_publish_dispatched() -> None:
    from datetime import timezone as _tz
    global _last_publish_dispatched_at
    _last_publish_dispatched_at = datetime.now(_tz.utc).isoformat()


@app.post("/publish", response_class=HTMLResponse)
def publish(request: Request):
    try:
        trigger_publish(cfg())
        _mark_publish_dispatched()
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


@app.get("/publish/status", response_class=JSONResponse)
def publish_status(request: Request):
    """Return the current state of the most recent publish workflow run.

    `running` is true when the latest run is queued/in_progress, OR when we
    just dispatched from this process and GitHub hasn't yet surfaced a run
    newer than that dispatch.
    """
    try:
        run = github_latest_run(cfg())
    except GitHubError as exc:
        return JSONResponse(
            {"configured": False, "running": False, "error": str(exc)},
            status_code=200,
        )
    configured = bool(cfg().github_token and cfg().github_repo)
    dispatched_at = _last_publish_dispatched_at
    run_status = run.get("status") if run else None
    running = run_status in ("queued", "in_progress")
    # Bridge the gap between our dispatch and the new run showing up.
    if dispatched_at and run:
        if (run.get("created_at") or "") < dispatched_at and not running:
            running = True
    elif dispatched_at and not run:
        running = True
    return JSONResponse(
        {
            "configured": configured,
            "running": running,
            "dispatched_at": dispatched_at,
            "run": run,
        }
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
    # `draft` lives outside the host site's configured INSERT — capture it
    # explicitly. Checkbox is absent from the form when unchecked.
    draft_raw = form.get("draft")
    if isinstance(draft_raw, str):
        values["draft"] = draft_raw.lower() in ("1", "true", "on", "yes")
    else:
        values["draft"] = False
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
