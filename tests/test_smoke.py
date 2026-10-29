"""Smoke tests: the app imports and its pure units behave. No database needed.

The factory's workcell runs these as the `ci-test` gate before anything is merged. The next
tests to add are route tests against a throwaway Postgres (see sql/ for the schema)."""

from importlib import resources
from pathlib import Path

from render_engine_pg_cms.config import Config, ContentType, load_config
from render_engine_pg_cms.main import _slugify, app


def test_the_app_imports_and_has_routes():
    assert app.title == "render-engine-pg-cms"
    paths = {r.path for r in app.routes}
    assert "/" in paths and "/quick" in paths


def test_slugify_keeps_it_short_and_url_safe():
    assert _slugify("Hello, World!") == "hello-world"
    assert (
        _slugify("  déjà vu  ") == "d-j-vu"
    )  # accents are transliterated away, not encoded
    assert len(_slugify("x" * 500)) == 80


def test_load_config_reads_the_pg_section(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CONNECTION_STRING", "postgres://localhost/test")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[tool.render-engine.pg]\n"
        'insert_sql.blog = "insert into blog (title) values ($1)"\n'
        'read_sql.blog = "select * from blog"\n'
    )
    cfg: Config = load_config(pyproject)
    assert isinstance(cfg.content_types["blog"], ContentType)
    assert cfg.content_types["blog"].table == "blog"


def test_the_packages_static_and_template_files_ship():
    assert resources.files("render_engine_pg_cms").joinpath("templates").is_dir()
    assert resources.files("render_engine_pg_cms").joinpath("static").is_dir()
