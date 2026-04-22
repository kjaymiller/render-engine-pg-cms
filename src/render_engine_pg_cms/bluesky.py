"""Minimal Bluesky (atproto) client — post a status (optionally with image)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import Config


class BlueskyError(RuntimeError):
    pass


MAX_CHARS = 300  # Bluesky post limit
URL_RE = re.compile(r"https?://[^\s]+")


class _Session:
    def __init__(self, pds: str, access_jwt: str, did: str):
        self.pds = pds
        self.access_jwt = access_jwt
        self.did = did

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_jwt}"}


def _login(cfg: Config) -> _Session:
    if not cfg.bluesky_handle or not cfg.bluesky_app_password:
        raise BlueskyError(
            "Bluesky not configured. Set BLUESKY_HANDLE and BLUESKY_APP_PASSWORD."
        )
    url = f"{cfg.bluesky_pds}/xrpc/com.atproto.server.createSession"
    try:
        r = httpx.post(
            url,
            json={
                "identifier": cfg.bluesky_handle,
                "password": cfg.bluesky_app_password,
            },
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        raise BlueskyError(f"Network error: {exc}") from exc
    if r.status_code >= 400:
        raise BlueskyError(f"Bluesky login {r.status_code}: {r.text[:300]}")
    data = r.json()
    return _Session(cfg.bluesky_pds, data["accessJwt"], data["did"])


def _resolve_image_url(cfg: Config, image_url: str) -> str:
    parsed = urlparse(image_url)
    if parsed.scheme in ("http", "https"):
        return image_url
    if not cfg.site_base_url:
        raise BlueskyError(
            f"image_url {image_url!r} is relative but SITE_BASE_URL is not set."
        )
    if image_url.startswith("/"):
        return f"{cfg.site_base_url}{image_url}"
    return f"{cfg.site_base_url}/{image_url}"


def _upload_blob(sess: _Session, image_url: str) -> dict[str, Any]:
    try:
        img = httpx.get(image_url, timeout=20.0, follow_redirects=True)
        img.raise_for_status()
    except httpx.HTTPError as exc:
        raise BlueskyError(f"Failed to fetch image: {exc}") from exc
    content_type = img.headers.get("content-type", "image/jpeg").split(";")[0]
    up_url = f"{sess.pds}/xrpc/com.atproto.repo.uploadBlob"
    try:
        r = httpx.post(
            up_url,
            content=img.content,
            headers={**sess.headers(), "Content-Type": content_type},
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        raise BlueskyError(f"Network error uploading blob: {exc}") from exc
    if r.status_code >= 400:
        raise BlueskyError(f"Bluesky blob upload {r.status_code}: {r.text[:300]}")
    data = r.json()
    blob = data.get("blob")
    if not blob:
        raise BlueskyError(f"Bluesky blob response missing blob: {data}")
    return blob


def _build_facets(text: str) -> list[dict[str, Any]]:
    """Detect URLs and emit atproto link facets so they're clickable."""
    facets: list[dict[str, Any]] = []
    # Use bytes offsets, per atproto spec.
    text_bytes = text.encode("utf-8")
    for m in URL_RE.finditer(text):
        start = len(text[: m.start()].encode("utf-8"))
        end = len(text[: m.end()].encode("utf-8"))
        facets.append({
            "index": {"byteStart": start, "byteEnd": end},
            "features": [
                {"$type": "app.bsky.richtext.facet#link", "uri": m.group(0)}
            ],
        })
    return facets


def post_status(
    cfg: Config,
    text: str,
    image_url: str | None = None,
    image_alt: str = "",
) -> dict[str, Any]:
    if len(text) > MAX_CHARS:
        text = text[: MAX_CHARS - 1] + "…"

    sess = _login(cfg)

    record: dict[str, Any] = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    facets = _build_facets(text)
    if facets:
        record["facets"] = facets

    if image_url:
        blob = _upload_blob(sess, _resolve_image_url(cfg, image_url))
        record["embed"] = {
            "$type": "app.bsky.embed.images",
            "images": [{"alt": image_alt[:1000], "image": blob}],
        }

    url = f"{sess.pds}/xrpc/com.atproto.repo.createRecord"
    try:
        r = httpx.post(
            url,
            json={
                "repo": sess.did,
                "collection": "app.bsky.feed.post",
                "record": record,
            },
            headers=sess.headers(),
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise BlueskyError(f"Network error posting: {exc}") from exc
    if r.status_code >= 400:
        raise BlueskyError(f"Bluesky post {r.status_code}: {r.text[:300]}")

    data = r.json()
    uri = data.get("uri", "")  # at://did:plc:.../app.bsky.feed.post/<rkey>
    rkey = uri.rsplit("/", 1)[-1] if uri else ""
    web_url = (
        f"https://bsky.app/profile/{cfg.bluesky_handle}/post/{rkey}"
        if rkey else ""
    )
    return {"uri": uri, "cid": data.get("cid", ""), "url": web_url}
