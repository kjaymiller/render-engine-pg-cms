---
title: "Image uploads"
description: "Drag an image onto the `image_url` field or the `content` textarea on any edit page. The CMS uploads it to Azure Blob Storage, optimizes it, and either fills the URL field or inserts a markdown image at your caret."
---

# Image uploads

Drag an image onto the `image_url` field or the `content` textarea on any edit page. The CMS uploads it to Azure Blob Storage, optimizes it, and either fills the URL field or inserts a markdown image at your caret.

Clipboard paste works too — hit `Cmd/Ctrl-V` on the same fields.

## The flow

1. Browser dispatches `drop` / `paste` event on the decorated element.
2. JS posts the file to `POST /api/upload` as multipart.
3. Server optimizes with Pillow (off the event loop).
4. Server uploads the result to Azure (off the event loop).
5. JSON response includes `{url, size, original_size, saved_bytes, ...}`.
6. JS either sets the input's `.value` (for `image_url`) or inserts `![alt](url)` at the caret (for `content`).

A status line under each drop zone shows `Uploaded photo.jpg (2100→180 KB, 91% smaller)`.

## Server-side optimization (`image_optimize.py`)

- **EXIF rotation** honored; **all metadata stripped** on save (no leaky GPS/camera info).
- **Downscale**: largest edge clamped to `MAX_EDGE_PX = 2200` via Lanczos resampling.
- **Re-encode**: WebP (quality 82) for images with alpha, JPEG (quality 82, progressive) otherwise. Preserves WebP if the upload was already WebP.
- **Pass-through**: SVG and GIF are untouched — re-encoding SVG loses nothing and animated GIFs would silently drop frames.
- **Safety net**: `MAX_DECODE_PIXELS = 100_000_000`. Anything bigger is passed through without decoding, so a weaponized PNG can't blow up Pillow's memory.
- **No-op guard**: if optimization ever produces *larger* output (rare), the original bytes are kept.
- **Short-circuit**: files under 50 KB skip optimization entirely.

## Server-side limits

- **Request cap**: `MAX_UPLOAD_BYTES = 50 * 1024 * 1024` (50 MiB). Covers ProRAW, 5K screenshots, etc.
- **Content types**: `image/png`, `image/jpeg`, `image/gif`, `image/webp`, `image/svg+xml`, `image/avif`. Anything else → 400.

## Blob naming (`azure_blob.py`)

Blobs land at the container root (the container itself is the "uploads" bucket):

```
<slug>-<uuid8>.<ext>
```

- `<slug>`: NFKD-normalized, ASCII-transliterated, lowercased, non-alphanumerics collapsed to `-`, capped at 50 chars. `"Crème brûlée.JPG"` → `"creme-brulee"`.
- `<uuid8>`: 8 hex chars from a v4 uuid, so repeated uploads of the same filename don't collide.
- `<ext>`: picked from the optimized content-type (`.webp`, `.jpg`, etc.).
- Non-Latin filenames (Japanese, Arabic, etc.) that slug to empty fall back to `<uuid8>.<ext>`.
- Paste-from-clipboard (no filename) also uses the uuid-only form.

Example: dropping `Crème brûlée.JPG` stores `creme-brulee-a3b9c7d1.webp` (after re-encoding to WebP).

## Cache headers

Every blob is saved with `Cache-Control: public, max-age=31536000, immutable`. Because every upload has a unique URL (uuid suffix + extension), re-uploading never invalidates anything — clients cache forever safely.

## Public URL resolution

- If `AZURE_PUBLIC_BASE_URL` is set (e.g. `https://cdn.kjaymiller.com/uploads`), the returned URL is `{base}/{blob_name}`.
- Otherwise, falls back to the blob's default URL: `https://{account}.blob.core.windows.net/{container}/{blob_name}`.

## Drop zones

| Field             | Mode       | Effect                                                |
| ----------------- | ---------- | ----------------------------------------------------- |
| `content`         | `markdown` | Inserts `\n![<basename>](<url>)\n` at the caret.      |
| `image_url`       | `url`      | Sets the input's `.value` to the returned URL.        |

Drag-over highlights the target zone with an inset border + "Drop to upload" overlay. Drag-leave only resets when the cursor actually exits the zone (not when it crosses into a child element).

## Azure container setup

1. Create a storage account in Azure.
2. Create a container (name is whatever you want, e.g. `uploads`).
3. Set **Public access level** to **Blob** so the returned URLs work without SAS tokens.
4. Fetch the connection string from **Security + networking → Access keys**.
5. Set `AZURE_STORAGE_CONNECTION_STRING` and `AZURE_STORAGE_CONTAINER` in your env.

Optional: front the container with Azure CDN or Front Door, point your custom domain at it, and set `AZURE_PUBLIC_BASE_URL`.

## Security considerations

- `/api/upload` is **unauthenticated** — same as every other route. The whole CMS is assumed to be behind a private network (Tailscale, localhost only, etc.).
- Allowlist of content types prevents arbitrary files (HTML, executables) from being uploaded.
- UUID-suffixed names make direct enumeration of other uploads impractical.
- Metadata stripping removes EXIF GPS that could leak home/venue locations from photos.

## Env vars

See [configuration.md](configuration.md#azure-blob-storage-image-uploads).
