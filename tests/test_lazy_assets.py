"""Heavy third-party assets must not block first paint (issue #10)."""

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "src/render_engine_pg_cms/templates"
BASE = (TEMPLATES / "base.html").read_text()

MARKED = "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"
ALPINE = "https://cdn.jsdelivr.net/npm/alpinejs@3.14.9/dist/cdn.min.js"


def _head() -> str:
    return BASE.split("</head>", 1)[0]


def test_marked_and_mermaid_not_loaded_eagerly():
    script_srcs = re.findall(r"<script[^>]*\bsrc=\"([^\"]+)\"", BASE)
    assert MARKED not in script_srcs
    assert MERMAID not in script_srcs


def test_lazy_loader_uses_pinned_literal_urls():
    assert f'marked: "{MARKED}"' in BASE
    assert f'mermaid: "{MERMAID}"' in BASE


def test_alpine_still_deferred():
    assert f'<script defer src="{ALPINE}"></script>' in _head()


def test_google_fonts_stylesheet_is_non_blocking():
    links = re.findall(r"<link[^>]*fonts\.googleapis\.com/css2[^>]*>", _head())
    noscript = re.findall(r"<noscript>.*?</noscript>", _head(), re.DOTALL)
    blocking = [link for link in links if not any(link in n for n in noscript)]
    assert blocking, "expected the main fonts link"
    for link in blocking:
        assert 'media="print"' in link
        assert "onload=\"this.media='all'\"" in link
    assert any("fonts.googleapis.com/css2" in n for n in noscript)
