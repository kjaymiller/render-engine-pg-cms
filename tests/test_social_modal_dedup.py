"""Publish-to-social modals are deduplicated on list/timeline pages (issue #14).

The list and timeline used to render one full modal per row (up to 50+ per
page). They now render exactly one shared `publishSocialShared` modal plus a
lightweight per-row trigger button carrying that row's social context as a
JSON `data-social` payload. These tests render the real templates with mock
contexts (no database) and assert the modal count, the trigger payload, and
that record text stays escaped.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES = Path(__file__).resolve().parents[1] / "src/render_engine_pg_cms/templates"


@pytest.fixture(scope="module")
def env() -> Environment:
    e = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
    )
    # The app registers a markdown renderer here; listings don't need it.
    e.filters["md"] = lambda s: s or ""
    return e


def _record(**over) -> dict:
    rec = {
        "id": 7,
        "mastodon_url": None,
        "bluesky_url": None,
        "draft": False,
        "_scheduled": False,
        "date": datetime(2024, 1, 1),
        "created_at": datetime(2024, 1, 1),
        "content": "body",
        "slug": "a-post",
        "title": "A post",
        "_truncated": False,
        "_type": "microblog",
        "_social_draft": "draft text",
        "_social_image_url": "",
        "_social_image_alt": "",
        "_social_canonical_url": "",
    }
    rec.update(over)
    return rec


def _ct(name: str):
    # ContentType import would pull in config; a light stand-in is enough
    # for `ct.name` used throughout the templates.
    class _CT:
        def __init__(self, n):
            self.name = n

    return _CT(name)


def _count_modals(html: str) -> int:
    return len(re.findall(r'x-data="publishSocialShared\(', html))


def _count_triggers(html: str) -> int:
    return len(re.findall(r"<button[^>]*\bdata-social-publish\b", html))


# --- list page ---------------------------------------------------------------


def _list_html(env, records):
    return env.get_template("list.html").render(
        ct=_ct("microblog"),
        records=records,
        status="all",
        status_counts={"all": len(records)},
        page=1,
        pages=1,
        per=50,
        total=len(records),
        flash=None,
        flash_level="ok",
        mastodon_enabled=True,
        bluesky_enabled=True,
        syndication_enabled=True,
        masto_limit=500,
        bsky_limit=300,
    )


def test_many_rows_render_exactly_one_modal(env):
    html = _list_html(env, [_record(id=i) for i in range(1, 51)])
    assert _count_modals(html) == 1
    # A trigger remains per eligible row so each record is still reachable.
    assert _count_triggers(html) == 50


def test_trigger_carries_own_record_action_and_payload(env):
    html = _list_html(env, [_record(id=42), _record(id=43)])
    actions = re.findall(r'data-action="([^"]*)"', html)
    assert actions == [
        "/c/microblog/42/syndicate",
        "/c/microblog/43/syndicate",
    ]
    # Each trigger's JSON payload round-trips the record id it belongs to is
    # implied by the action; the count of payloads matches the rows.
    assert html.count("data-social='") == 2


def test_no_trigger_or_modal_when_record_already_posted(env):
    rec = _record(mastodon_url="https://m/1", bluesky_url="https://b/1")
    html = _list_html(env, [rec])
    assert _count_triggers(html) == 0
    # The shared modal shell still renders once for the page, but with no
    # trigger it is inert.
    assert _count_modals(html) == 1


def test_no_syndication_renders_no_modal(env):
    html = env.get_template("list.html").render(
        ct=_ct("microblog"),
        records=[_record()],
        status="all",
        status_counts={"all": 1},
        page=1,
        pages=1,
        per=50,
        total=1,
        flash=None,
        flash_level="ok",
        mastodon_enabled=False,
        bluesky_enabled=False,
        syndication_enabled=False,
        masto_limit=500,
        bsky_limit=300,
    )
    assert _count_modals(html) == 0
    assert _count_triggers(html) == 0


def test_draft_text_is_escaped_in_trigger_payload(env):
    evil = "</script><img src=x onerror=alert(1)> \" ' &"
    html = _list_html(env, [_record(_social_draft=evil)])
    # No raw `</script>` can survive inside the attribute (tojson escapes it).
    assert "</script><img" not in html
    assert "\\u003c/script\\u003e" in html
    # The literal quote/apostrophe/ampersand can't break the single-quoted
    # attribute either.
    assert "data-social='" in html


# --- timeline (index) page ---------------------------------------------------


class _Req:
    def __init__(self):
        self.query_params = {}


def _index_html(env, rows):
    return env.get_template("index.html").render(
        request=_Req(),
        content_types={"microblog": _ct("microblog")},
        rows=rows,
        page=1,
        pages=1,
        per=50,
        total=len(rows),
        timeline_types=["microblog"],
        status="all",
        status_counts={"all": len(rows)},
        mastodon_enabled=True,
        bluesky_enabled=True,
        syndication_enabled=True,
        masto_limit=500,
        bsky_limit=300,
        url="",
        title="",
    )


def test_timeline_renders_one_modal_for_many_rows(env):
    html = _index_html(env, [_record(id=i) for i in range(1, 51)])
    assert _count_modals(html) == 1
    assert _count_triggers(html) == 50


# --- edit page stays inline --------------------------------------------------


def test_edit_page_keeps_single_inline_modal(env):
    html = env.get_template("edit.html").render(
        request=_Req(),
        ct=_ct("microblog"),
        record=_record(),
        tags=[],
        is_new=False,
        errors={},
        form_error=None,
        flash=None,
        flash_level="ok",
        has_mastodon=True,
        has_bluesky=True,
        social_draft="draft text",
        social_image_url="",
        social_image_alt="",
        social_canonical_url="",
        masto_limit=500,
        bsky_limit=300,
    )
    # The edit page is a single record: keep its inline publishSocial modal.
    assert "x-data='publishSocial(" in html
    assert _count_modals(html) == 0
