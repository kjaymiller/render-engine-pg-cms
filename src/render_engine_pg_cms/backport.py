"""Match existing Mastodon / Bluesky posts to CMS records and store URLs.

Strategy per record:
  1. If the toot/skeet contains the record's external_link verbatim, match.
  2. Otherwise compare normalized first ~80 chars of content; match when one is
     a prefix of the other.

This is intentionally conservative — a record with neither an external_link
nor a content prefix that appears in the post will be left alone.

Usage:
  just backport-syndication          # dry-run, prints proposed matches
  just backport-syndication apply    # writes matches to the database
"""
from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

from . import db
from .config import Config, ContentType, load_config

MICROBLOG_PREFIX_LEN = 280
TITLE_PREFIX_LEN = 80


# ---------- Normalization ----------

class _TagStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def _strip_html(s: str) -> str:
    p = _TagStripper()
    p.feed(s or "")
    return p.text()


_WS_RE = re.compile(r"\s+")
# Strip anything that isn't a letter or digit — collapses markdown syntax,
# punctuation, emoji, HTML residue, etc. so comparison is content-only.
_NONWORD_RE = re.compile(r"[^a-z0-9]+")
# Strip markdown link wrappers: [text](url) -> text
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def _normalize(s: str) -> str:
    s = _MD_LINK_RE.sub(r"\1", s or "")
    s = _WS_RE.sub(" ", s.strip()).lower()
    return _NONWORD_RE.sub("", s)


def _prefix(s: str, n: int) -> str:
    return _normalize(s)[:n]


def _record_signature(ct_name: str, record: dict) -> tuple[str, int]:
    """(normalized signature, comparison length) for prefix matching.

    Blog/notes → title. Microblog → content (up to ~280 chars).
    """
    if ct_name == "microblog":
        return _prefix(record.get("content") or "", MICROBLOG_PREFIX_LEN), MICROBLOG_PREFIX_LEN
    title = record.get("title") or record.get("name") or ""
    return _prefix(title, TITLE_PREFIX_LEN), TITLE_PREFIX_LEN


def _build_record_url(cfg: Config, ct_name: str, record: dict) -> str:
    slug = (record.get("slug") or "").strip()
    if not slug or not cfg.site_base_url:
        return ""
    tmpl = cfg.webmention_url_template or "{base}/{type}/{slug}/"
    return tmpl.format(base=cfg.site_base_url, type=ct_name, slug=slug)


# ---------- Fetchers ----------

def _mastodon_statuses(cfg: Config) -> list[dict[str, Any]]:
    if not cfg.mastodon_instance or not cfg.mastodon_access_token:
        print("Mastodon not configured; skipping.", file=sys.stderr)
        return []
    headers = {"Authorization": f"Bearer {cfg.mastodon_access_token}"}
    with httpx.Client(timeout=30.0, headers=headers) as client:
        acct = client.get(
            f"{cfg.mastodon_instance}/api/v1/accounts/verify_credentials"
        ).json()
        acct_id = acct["id"]
        out: list[dict[str, Any]] = []
        max_id: str | None = None
        while True:
            params: dict[str, Any] = {"limit": "40", "exclude_reblogs": "true"}
            if max_id:
                params["max_id"] = max_id
            r = client.get(
                f"{cfg.mastodon_instance}/api/v1/accounts/{acct_id}/statuses",
                params=params,
            )
            r.raise_for_status()
            page = r.json()
            if not page:
                break
            out.extend(page)
            max_id = page[-1]["id"]
            if len(page) < 40:
                break
    return out


def _bluesky_posts(cfg: Config) -> list[dict[str, Any]]:
    if not cfg.bluesky_handle or not cfg.bluesky_app_password:
        print("Bluesky not configured; skipping.", file=sys.stderr)
        return []
    with httpx.Client(timeout=30.0) as client:
        s = client.post(
            f"{cfg.bluesky_pds}/xrpc/com.atproto.server.createSession",
            json={
                "identifier": cfg.bluesky_handle,
                "password": cfg.bluesky_app_password,
            },
        ).json()
        headers = {"Authorization": f"Bearer {s['accessJwt']}"}
        did = s["did"]
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"actor": did, "limit": 100}
            if cursor:
                params["cursor"] = cursor
            r = client.get(
                f"{cfg.bluesky_pds}/xrpc/app.bsky.feed.getAuthorFeed",
                headers=headers,
                params=params,
            )
            r.raise_for_status()
            data = r.json()
            feed = data.get("feed", [])
            for item in feed:
                post = item.get("post", {})
                out.append(post)
            cursor = data.get("cursor")
            if not cursor or not feed:
                break
    return out


# ---------- Matchers ----------

def _candidate_links(cfg: Config, ct_name: str, record: dict) -> list[str]:
    out: list[str] = []
    ext = (record.get("external_link") or "").strip()
    if ext:
        out.append(ext)
    public = _build_record_url(cfg, ct_name, record)
    if public:
        out.append(public)
        out.append(public.rstrip("/"))
    return out


def _prefix_match(rec_sig: str, post_norm: str, cmp_len: int) -> bool:
    if not rec_sig or len(rec_sig) < 20:
        return False
    if not post_norm:
        return False
    # Either side may be truncated (Mastodon/Bluesky char limits, or the
    # record's full content exceeds the post). Match if one is a prefix of the
    # other up to cmp_len.
    a = rec_sig[:cmp_len]
    b = post_norm[:cmp_len]
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return bool(short) and long.startswith(short)


def _match_mastodon(
    cfg: Config, ct_name: str, record: dict, statuses: list[dict]
) -> str | None:
    links = _candidate_links(cfg, ct_name, record)
    rec_sig, cmp_len = _record_signature(ct_name, record)
    for st in statuses:
        raw = st.get("content") or ""
        if any(link and link in raw for link in links):
            return st["url"]
        norm = _normalize(_strip_html(raw))
        if _prefix_match(rec_sig, norm, cmp_len):
            return st["url"]
    return None


def _match_bluesky(
    cfg: Config, ct_name: str, record: dict, posts: list[dict]
) -> str | None:
    links = _candidate_links(cfg, ct_name, record)
    rec_sig, cmp_len = _record_signature(ct_name, record)
    for post in posts:
        record_val = post.get("record", {}) or {}
        text = record_val.get("text") or ""
        embed = record_val.get("embed") or {}
        ext_uri = ((embed.get("external") or {}).get("uri") or "")
        haystack = f"{text} {ext_uri}"
        if any(link and link in haystack for link in links):
            return _bsky_url_for(cfg, post)
        norm = _normalize(text)
        if _prefix_match(rec_sig, norm, cmp_len):
            return _bsky_url_for(cfg, post)
    return None


def _bsky_url_for(cfg: Config, post: dict) -> str:
    uri = post.get("uri", "")
    rkey = uri.rsplit("/", 1)[-1] if uri else ""
    handle = (post.get("author") or {}).get("handle") or cfg.bluesky_handle
    return f"https://bsky.app/profile/{handle}/post/{rkey}" if rkey else ""


# ---------- Driver ----------

def _records_missing(cfg: Config, ct: ContentType, column: str) -> list[dict]:
    with psycopg.connect(cfg.connection_string, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM {ct.table}
                WHERE {column} IS NULL OR {column} = ''
                """
            )
            return list(cur.fetchall())


def backport(apply: bool = False) -> None:
    cfg = load_config()
    print("Fetching remote timelines…")
    mastodon_statuses = _mastodon_statuses(cfg)
    bluesky_posts = _bluesky_posts(cfg)
    print(
        f"  {len(mastodon_statuses)} mastodon statuses, "
        f"{len(bluesky_posts)} bluesky posts"
    )

    for name in ("microblog", "blog"):
        ct = cfg.content_types.get(name)
        if ct is None:
            continue

        for column, matcher, label in (
            ("mastodon_url",
             lambda r, _n=name: _match_mastodon(cfg, _n, r, mastodon_statuses),
             "Mastodon"),
            ("bluesky_url",
             lambda r, _n=name: _match_bluesky(cfg, _n, r, bluesky_posts),
             "Bluesky"),
        ):
            records = _records_missing(cfg, ct, column)
            if not records:
                continue
            print(f"\n{label} backport — {ct.name} ({len(records)} candidates)")
            matched = 0
            for r in records:
                url = matcher(r)
                if not url:
                    continue
                matched += 1
                tag = "APPLY" if apply else " DRY "
                snippet = _prefix(r.get("content") or r.get("title") or "", 60)
                print(f"  [{tag}] #{r['id']} → {url}  ({snippet!r})")
                if apply:
                    db.set_syndication_url(cfg, ct, r["id"], column, url)
            print(f"  matched {matched}/{len(records)}")

    if not apply:
        print("\nDry run complete. Re-run with `apply` to write matches.")


if __name__ == "__main__":
    backport(apply=(len(sys.argv) > 1 and sys.argv[1] == "apply"))
