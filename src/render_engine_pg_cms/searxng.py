"""Thin client for a SearXNG instance (https://docs.searxng.org).

Backs the notes editor's inline "search the web" panel — look up a source
and insert it as a markdown link without leaving the editor.

Config (env vars, wired through Config):
  SEARXNG_URL — default https://search.kjaymiller.dev
"""
from __future__ import annotations

import httpx

from .config import Config


class SearxngError(RuntimeError):
    pass


def search(cfg: Config, query: str, *, limit: int = 8) -> list[dict]:
    """Return up to `limit` {title, url, content} results for `query`.

    Raises SearxngError on failure — caller decides whether to surface it.
    """
    query = (query or "").strip()
    if not query:
        raise SearxngError("Empty query.")
    url = f"{cfg.searxng_url.rstrip('/')}/search"
    try:
        r = httpx.get(url, params={"q": query, "format": "json"}, timeout=8.0)
    except httpx.HTTPError as exc:
        raise SearxngError(f"Network error: {exc}") from exc
    if r.status_code >= 400:
        raise SearxngError(f"SearXNG {r.status_code}: {r.text[:300]}")
    try:
        data = r.json()
    except ValueError as exc:
        raise SearxngError(f"Bad response: {exc}") from exc

    out = []
    for item in data.get("results") or []:
        title = (item.get("title") or "").strip()
        link = (item.get("url") or "").strip()
        if not title or not link:
            continue
        out.append({
            "title": title,
            "url": link,
            "content": (item.get("content") or "").strip(),
        })
        if len(out) >= limit:
            break
    return out
