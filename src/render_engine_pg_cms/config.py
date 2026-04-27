"""Load render-engine CMS config from the site's pyproject.toml."""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


# {placeholder} → %(placeholder)s, so psycopg can bind named params.
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _convert(sql: str) -> tuple[str, list[str]]:
    params: list[str] = []

    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in params:
            params.append(name)
        return f"%({name})s"

    return _PLACEHOLDER.sub(sub, sql), params


@dataclass
class ContentType:
    name: str
    # All INSERT statements from config. Order is not assumed to be meaningful.
    insert_statements: list[tuple[str, list[str]]] = field(default_factory=list)
    # The primary insert (INSERT INTO <name>) — drives form fields and UPDATE.
    primary_insert: tuple[str, list[str]] | None = None
    # INSERT INTO tags (...) — upserts tag names.
    tag_insert: tuple[str, list[str]] | None = None
    # INSERT INTO <name>_tags (...) — links record to tags.
    join_insert: tuple[str, list[str]] | None = None
    # Primary table name, == name once classified.
    table: str = ""
    # SELECT statement for listing records.
    read_sql: str = ""

    @property
    def primary_columns(self) -> list[str]:
        return list(self.primary_insert[1]) if self.primary_insert else []

    @property
    def has_tags(self) -> bool:
        return self.join_insert is not None


@dataclass
class Config:
    connection_string: str
    content_types: dict[str, ContentType]
    github_token: str = ""
    github_repo: str = ""
    github_workflow: str = "publish.yml"
    github_ref: str = "main"
    mastodon_instance: str = ""
    mastodon_access_token: str = ""
    mastodon_default_visibility: str = "public"
    site_base_url: str = ""  # used to resolve relative image_url values
    bluesky_handle: str = ""
    bluesky_app_password: str = ""
    bluesky_pds: str = "https://bsky.social"
    webmention_io_token: str = ""
    # URL template for building the public post URL from a record.
    # Placeholders: {base}, {type}, {slug}
    # Default matches render-engine's default .html page suffix; override
    # with WEBMENTION_URL_TEMPLATE if your site uses trailing-slash routes.
    webmention_url_template: str = "{base}/{type}/{slug}.html"
    # Azure Blob Storage (for drag-drop image uploads)
    azure_storage_connection_string: str = ""
    azure_storage_account: str = ""
    azure_storage_key: str = ""
    azure_storage_container: str = ""
    azure_public_base_url: str = ""
    # Local Ollama server for AI slug suggestions
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"


_TABLE_RE = re.compile(r"INSERT\s+INTO\s+(\w+)", re.IGNORECASE)


def load_config(pyproject_path: Path | None = None) -> Config:
    pyproject_path = pyproject_path or Path(
        os.environ.get("SITE_PYPROJECT", "pyproject.toml")
    )
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)

    pg = data.get("tool", {}).get("render-engine", {}).get("pg", {})
    insert_block = pg.get("insert_sql", {})
    read_block = pg.get("read_sql", {})

    content_types: dict[str, ContentType] = {}
    for name, statements in insert_block.items():
        if isinstance(statements, str):
            statements = [statements]
        ct = ContentType(name=name)
        for stmt in statements:
            converted, params = _convert(stmt)
            ct.insert_statements.append((converted, params))
            m = _TABLE_RE.search(converted)
            table = m.group(1).lower() if m else ""
            if table == name.lower():
                ct.primary_insert = (converted, params)
                ct.table = m.group(1)
            elif table == "tags":
                ct.tag_insert = (converted, params)
            elif table == f"{name.lower()}_tags":
                ct.join_insert = (converted, params)
        # Fallback: if no INSERT matched the content type name, treat the
        # first statement as primary so misnamed configs still work.
        if ct.primary_insert is None and ct.insert_statements:
            first_stmt, first_params = ct.insert_statements[0]
            ct.primary_insert = (first_stmt, first_params)
            m = _TABLE_RE.search(first_stmt)
            if m:
                ct.table = m.group(1)
        ct.read_sql = read_block.get(name, "")
        content_types[name] = ct

    return Config(
        connection_string=os.environ["CONNECTION_STRING"],
        content_types=content_types,
        github_token=os.environ.get("GITHUB_TOKEN", ""),
        github_repo=os.environ.get("GITHUB_REPO", ""),
        github_workflow=os.environ.get("GITHUB_WORKFLOW", "publish.yml"),
        github_ref=os.environ.get("GITHUB_REF", "main"),
        mastodon_instance=os.environ.get("MASTODON_INSTANCE", "").rstrip("/"),
        mastodon_access_token=os.environ.get("MASTODON_ACCESS_TOKEN", "").strip(),
        mastodon_default_visibility=os.environ.get(
            "MASTODON_VISIBILITY", "public"
        ),
        site_base_url=os.environ.get("SITE_BASE_URL", "").rstrip("/"),
        bluesky_handle=os.environ.get("BLUESKY_HANDLE", ""),
        bluesky_app_password=os.environ.get("BLUESKY_APP_PASSWORD", "").strip(),
        bluesky_pds=os.environ.get("BLUESKY_PDS", "https://bsky.social").rstrip("/"),
        webmention_io_token=os.environ.get("WEBMENTION_IO_TOKEN", ""),
        webmention_url_template=os.environ.get(
            "WEBMENTION_URL_TEMPLATE", "{base}/{type}/{slug}.html"
        ),
        azure_storage_connection_string=os.environ.get(
            "AZURE_STORAGE_CONNECTION_STRING", ""
        ),
        azure_storage_account=os.environ.get("AZURE_STORAGE_ACCOUNT", ""),
        azure_storage_key=os.environ.get("AZURE_STORAGE_KEY", ""),
        azure_storage_container=os.environ.get("AZURE_STORAGE_CONTAINER", ""),
        azure_public_base_url=os.environ.get("AZURE_PUBLIC_BASE_URL", "").rstrip("/"),
        ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        ollama_model=os.environ.get("OLLAMA_MODEL", "llama3.2:3b"),
    )
