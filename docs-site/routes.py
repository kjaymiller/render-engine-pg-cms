"""Static docs site for render-engine-pg-cms.

Pulls markdown from ../docs and ../README.md, renders each page through
`doc.html`, and produces an index that lists everything. Run with:

    cd docs-site && uv run render-engine build

Output lands in ./output/ (gitignored).
"""
from pathlib import Path

from render_engine import Collection, Page, Site
from render_engine_markdown import MarkdownPageParser

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent

app = Site()
app.output_path = str(HERE / "output")
app.static_path = str(HERE / "static")
app.site_vars.update(
    SITE_TITLE="render-engine-pg-cms",
    SITE_TAGLINE="A lightweight FastAPI CMS for render-engine sites.",
    SITE_URL="",  # set RE_SITE_URL if you publish this somewhere
)

markdown_extras = [
    "admonitions",
    "footnotes",
    "fenced-code-blocks",
    "header-ids",
    "tables",
    "strike",
]


@app.page
class Index(Page):
    """The repo README becomes the site's landing page."""
    Parser = MarkdownPageParser
    parser_extras = {"markdown_extras": markdown_extras}
    content_path = str(REPO_ROOT / "README.md")
    template = "index.html"
    path_name = "index.html"
    title = "render-engine-pg-cms"


@app.collection
class Docs(Collection):
    """One page per markdown file in ../docs."""
    Parser = MarkdownPageParser
    parser_extras = {"markdown_extras": markdown_extras}
    content_path = str(REPO_ROOT / "docs")
    template = "doc.html"
    routes = ["docs"]
    has_archive = True
    archive_template = "docs_archive.html"
    archive_title = "Documentation"
