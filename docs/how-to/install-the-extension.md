---
title: "Install the browser extension"
description: "Add the quick-capture toolbar button to Firefox or Zen so you can seed a CMS post from any page."
---

# Install the browser extension

A tiny WebExtension under `extension/` adds a toolbar button. Click it on any page → the CMS opens with the current tab's URL and title prefilled into the **Quick add** box.

## Temporary install (one session)

1. Open `about:debugging#/runtime/this-firefox`.
2. **Load Temporary Add-on…**.
3. Select `extension/manifest.json`.

## Packaged `.xpi`

```bash
just extension
```

Produces `pg-cms-quick-capture.xpi` at the repo root. In Zen: `about:debugging` → **Load Temporary Add-on** → select the `.xpi`.

For a signed, permanent install, run it through `web-ext sign` or publish to AMO.

## Configuration

Right-click the toolbar button → **Manage Extension** → **Preferences**. One field: the CMS base URL (default `http://localhost:8000`).

If you expose the CMS over Tailscale, point the extension at the tailnet URL (e.g. `http://100.x.y.z:8000`) so the button works from any browser on your tailnet.

## What it does

Clicking the icon opens:

```
<CMS_BASE>/quick?url=<tab.url>&title=<tab.title>
```

`/quick` redirects to `/` carrying those params. The homepage's **Quick add** card shows "Capturing: <url>" with a content-type picker. Pick a type → the new-record form opens with `external_link` (or `url`), `title`, and `slug` pre-filled.

You fill the rest and save normally. Auto-publish, syndication, and webmention tracking all apply — the extension only seeds the form.
