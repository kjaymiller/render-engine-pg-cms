---
title: "Upload images"
description: "Drag, paste, or POST images. The CMS optimizes them and stores them in Azure Blob Storage."
---

# Upload images

## One-time Azure setup

1. Create a storage account in Azure.
2. Create a container (e.g. `uploads`).
3. **Public access level** → **Blob** so URLs work without SAS tokens.
4. Grab the connection string from **Security + networking → Access keys**.
5. Set in `.env`:

   ```
   AZURE_STORAGE_CONNECTION_STRING=<full-connection-string>
   AZURE_STORAGE_CONTAINER=uploads
   AZURE_PUBLIC_BASE_URL=https://cdn.example.com/uploads   # optional CDN/custom domain
   ```

If you don't have a connection string, set `AZURE_STORAGE_ACCOUNT` + `AZURE_STORAGE_KEY` instead.

## From the edit form

Two drop zones on every edit page:

| Field         | What happens                                         |
| ------------- | ---------------------------------------------------- |
| `content`     | Inserts `\n![filename](url)\n` at the caret.         |
| `image_url`   | Sets the input's value to the returned URL.          |

You can:
- **Drag** an image file onto the zone.
- **Paste** an image (`Cmd/Ctrl-V`) while focused on the zone.

A status line below shows: `Uploaded photo.jpg (2100→180 KB, 91% smaller)`.

## Via the API

```bash
curl -X POST http://localhost:8000/api/upload \
  -F file=@photo.jpg
```

Response:

```json
{
  "url": "https://account.blob.core.windows.net/uploads/photo-a3b9c7d1.webp",
  "filename": "photo.jpg",
  "content_type": "image/webp",
  "original_content_type": "image/jpeg",
  "size": 184210,
  "original_size": 2103840,
  "saved_bytes": 1919630
}
```

See [reference/http-api.md](../reference/http-api.md#image-upload) for error codes.

## What gets done to the image

- EXIF rotation honored, then **all metadata stripped** (no leaky GPS).
- Largest edge clamped to **2200px** via Lanczos resampling.
- Re-encoded to **WebP** (with alpha) or **JPEG** (without), quality 82.
- SVG and GIF pass through unchanged.
- Files under 50 KB skip optimization.
- 50 MiB request cap (`MAX_UPLOAD_BYTES`).

For the rationale see [explanation/architecture.md](../explanation/architecture.md#image-uploads).
