"""Azure Blob Storage uploads for image assets.

Config (env vars, wired through Config in config.py):
  AZURE_STORAGE_CONNECTION_STRING  — full connection string OR
  AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_KEY  — account-name + shared key
  AZURE_STORAGE_CONTAINER          — container name (e.g. "media")
  AZURE_PUBLIC_BASE_URL            — optional CDN base; falls back to the
                                     blob's default https URL

Public API:
  upload_bytes(cfg, data, content_type, filename_hint) -> public_url
"""
from __future__ import annotations

import mimetypes
import re
import unicodedata
import uuid
from pathlib import PurePosixPath

from azure.storage.blob import BlobServiceClient, ContentSettings

from .config import Config


class AzureUploadError(RuntimeError):
    pass


# Allowed content types for image uploads. Keep tight — this endpoint
# accepts unauthenticated-ish input from the CMS UI, so we don't want
# arbitrary file types leaking into blob storage.
ALLOWED_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "image/avif",
}
EXT_BY_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/avif": ".avif",
}


def _client(cfg: Config) -> BlobServiceClient:
    if cfg.azure_storage_connection_string:
        return BlobServiceClient.from_connection_string(
            cfg.azure_storage_connection_string
        )
    if cfg.azure_storage_account and cfg.azure_storage_key:
        account_url = f"https://{cfg.azure_storage_account}.blob.core.windows.net"
        return BlobServiceClient(
            account_url=account_url, credential=cfg.azure_storage_key
        )
    raise AzureUploadError(
        "Azure storage is not configured. Set AZURE_STORAGE_CONNECTION_STRING "
        "or AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_KEY."
    )


def _safe_ext(filename_hint: str | None, content_type: str) -> str:
    """Pick a filesystem-safe extension. Prefer the hint, fall back to the
    content-type-derived default, else empty."""
    if filename_hint:
        suffix = PurePosixPath(filename_hint).suffix.lower()
        if suffix and len(suffix) <= 6 and suffix[1:].isalnum():
            return suffix
    if content_type in EXT_BY_TYPE:
        return EXT_BY_TYPE[content_type]
    guess = mimetypes.guess_extension(content_type or "")
    return guess or ""


def _slugify(name: str) -> str:
    """Lowercase, transliterate accents (café→cafe), collapse to [a-z0-9-]."""
    # NFKD decomposes "é" into "e" + combining accent; encoding to ASCII
    # with errors="ignore" then drops the combining marks, leaving "e".
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    name = name.strip("-")
    return name[:50]  # keep URLs sane even for very long filenames


def _blob_name(filename_hint: str | None, content_type: str) -> str:
    ext = _safe_ext(filename_hint, content_type)
    # Write directly to the container root (the container IS the uploads
    # bucket). Slugify the original basename and append a short uuid suffix
    # so re-uploading doesn't collide. E.g. "my-photo-a3b9c7d1.jpg".
    stem = ""
    if filename_hint:
        base = PurePosixPath(filename_hint).stem
        stem = _slugify(base)
    suffix = uuid.uuid4().hex[:8]
    if stem:
        return f"{stem}-{suffix}{ext}"
    return f"{suffix}{ext}"


def public_url(cfg: Config, blob_name: str) -> str:
    if cfg.azure_public_base_url:
        return f"{cfg.azure_public_base_url.rstrip('/')}/{blob_name}"
    # Fall back to the blob's default https URL.
    client = _client(cfg)
    blob = client.get_blob_client(container=cfg.azure_storage_container, blob=blob_name)
    return blob.url


def upload_bytes(
    cfg: Config,
    data: bytes,
    content_type: str,
    filename_hint: str | None = None,
) -> str:
    """Upload raw bytes to blob storage and return a public URL."""
    if not cfg.azure_storage_container:
        raise AzureUploadError("AZURE_STORAGE_CONTAINER is not set.")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise AzureUploadError(f"Unsupported content type: {content_type}")
    if not data:
        raise AzureUploadError("Empty upload.")

    blob_name = _blob_name(filename_hint, content_type)
    client = _client(cfg)
    blob = client.get_blob_client(
        container=cfg.azure_storage_container, blob=blob_name
    )
    blob.upload_blob(
        data,
        overwrite=False,
        content_settings=ContentSettings(
            content_type=content_type,
            # A year of immutable caching is fine: blob names are uuid-based,
            # so a re-upload produces a new URL rather than overwriting.
            cache_control="public, max-age=31536000, immutable",
        ),
    )
    return public_url(cfg, blob_name)
