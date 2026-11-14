"""Title slugs drop apostrophes instead of splitting on them.

"Don't Stop" should become "dont-stop", not "don-t-stop". Covers the straight
ASCII apostrophe and the typographic one (U+2019) that editors insert.
"""

from __future__ import annotations

import re

import pytest

from render_engine_pg_cms.main import _slugify


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Don't Stop", "dont-stop"),
        ("Don\u2019t Stop", "dont-stop"),
        ("It's a test", "its-a-test"),
        ("Plain title", "plain-title"),
    ],
)
def test_apostrophes_are_dropped(title: str, expected: str) -> None:
    assert _slugify(title) == expected


def test_slug_stays_restricted() -> None:
    assert re.fullmatch(r"[a-z0-9-]*", _slugify("Ros\u00e9's \"wild\" ride!?"))
