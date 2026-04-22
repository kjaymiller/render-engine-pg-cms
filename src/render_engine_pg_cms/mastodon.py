"""Minimal Mastodon client — post a status (optionally with media) and return the URL."""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import Config


class MastodonError(RuntimeError):
    pass


MAX_CHARS = 500  # default Mastodon toot limit
MEDIA_POLL_TIMEOUT = 30.0  # seconds to wait for async media processing
MEDIA_POLL_INTERVAL = 1.0


def _headers(cfg: Config) -> dict[str, str]:
    return {"Authorization": f"Bearer {cfg.mastodon_access_token}"}


def _resolve_image_url(cfg: Config, image_url: str) -> str:
    """Make a relative image_url absolute using SITE_BASE_URL."""
    if not image_url:
        return ""
    parsed = urlparse(image_url)
    if parsed.scheme in ("http", "https"):
        return image_url
    if not cfg.site_base_url:
        raise MastodonError(
            f"image_url {image_url!r} is relative but SITE_BASE_URL is not set."
        )
    if image_url.startswith("/"):
        return f"{cfg.site_base_url}{image_url}"
    return f"{cfg.site_base_url}/{image_url}"


def _upload_media(cfg: Config, image_url: str, alt: str = "") -> str:
    """Download an image and upload it to Mastodon. Returns the media id."""
    absolute = _resolve_image_url(cfg, image_url)
    try:
        r = httpx.get(absolute, timeout=20.0, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise MastodonError(f"Failed to fetch image {absolute}: {exc}") from exc

    filename = absolute.rsplit("/", 1)[-1] or "image"
    content_type = r.headers.get("content-type", "application/octet-stream")

    upload_url = f"{cfg.mastodon_instance}/api/v2/media"
    files = {"file": (filename, r.content, content_type)}
    data = {"description": alt[:1500]} if alt else {}
    try:
        up = httpx.post(
            upload_url, files=files, data=data,
            headers=_headers(cfg), timeout=60.0,
        )
    except httpx.HTTPError as exc:
        raise MastodonError(f"Network error uploading media: {exc}") from exc
    if up.status_code >= 400:
        raise MastodonError(f"Mastodon media upload {up.status_code}: {up.text[:300]}")

    media = up.json()
    media_id = media.get("id")
    if not media_id:
        raise MastodonError(f"Mastodon media response missing id: {media}")

    # 202 = still processing; poll GET /api/v1/media/:id until it returns 200.
    if up.status_code == 202:
        deadline = time.monotonic() + MEDIA_POLL_TIMEOUT
        status_url = f"{cfg.mastodon_instance}/api/v1/media/{media_id}"
        while time.monotonic() < deadline:
            time.sleep(MEDIA_POLL_INTERVAL)
            poll = httpx.get(status_url, headers=_headers(cfg), timeout=20.0)
            if poll.status_code == 200:
                break
            if poll.status_code >= 400:
                raise MastodonError(
                    f"Mastodon media processing failed {poll.status_code}: "
                    f"{poll.text[:300]}"
                )
        else:
            raise MastodonError(
                "Mastodon media still processing after "
                f"{MEDIA_POLL_TIMEOUT:.0f}s; aborting."
            )
    return media_id


def post_status(
    cfg: Config,
    text: str,
    visibility: str | None = None,
    image_url: str | None = None,
    image_alt: str = "",
) -> dict[str, Any]:
    if not cfg.mastodon_instance or not cfg.mastodon_access_token:
        raise MastodonError(
            "Mastodon not configured. Set MASTODON_INSTANCE and MASTODON_ACCESS_TOKEN."
        )

    media_ids: list[str] = []
    if image_url:
        media_ids.append(_upload_media(cfg, image_url, alt=image_alt))

    url = f"{cfg.mastodon_instance}/api/v1/statuses"
    data: dict[str, Any] = {
        "status": text,
        "visibility": visibility or cfg.mastodon_default_visibility,
    }
    if media_ids:
        data["media_ids[]"] = [str(m) for m in media_ids]

    try:
        r = httpx.post(url, data=data, headers=_headers(cfg), timeout=30.0)
    except httpx.HTTPError as exc:
        raise MastodonError(f"Network error posting to Mastodon: {exc}") from exc
    if r.status_code >= 400:
        raise MastodonError(f"Mastodon API {r.status_code}: {r.text[:300]}")
    data = r.json()
    if "url" not in data:
        raise MastodonError(f"Mastodon response missing url: {data}")
    return data


def build_status_text(ct_name: str, record: dict, tags: list[str]) -> str:
    """Format a record into toot text for a given content type."""
    parts: list[str] = []
    if ct_name == "microblog":
        content = (record.get("content") or "").strip()
        if content:
            parts.append(content)
        link = record.get("external_link")
        if link:
            parts.append(str(link))
    elif ct_name == "blog":
        title = (record.get("title") or "").strip()
        description = (record.get("description") or "").strip()
        link = record.get("external_link")
        if title:
            parts.append(title)
        if description:
            parts.append(description)
        if link:
            parts.append(str(link))
    else:
        for key in ("title", "name", "content", "description", "external_link"):
            v = record.get(key)
            if v:
                parts.append(str(v))
                break

    if tags:
        hashtags = " ".join(
            "#" + t.replace(" ", "").replace("-", "") for t in tags if t
        )
        parts.append(hashtags)

    text = "\n\n".join(p for p in parts if p)
    if len(text) > MAX_CHARS:
        text = text[: MAX_CHARS - 1] + "…"
    return text


def build_alt_text(ct_name: str, record: dict) -> str:
    """Reasonable alt-text guess for the attached image."""
    if ct_name == "blog":
        return (record.get("description") or record.get("title") or "").strip()
    return (record.get("content") or "").strip()
