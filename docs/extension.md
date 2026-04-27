---
title: "Firefox/Zen quick-capture extension"
description: "A tiny WebExtension under `extension/` that adds a toolbar button. Click it on any page and the CMS opens with the current tab's URL and title prefilled into the **Quick add** box."
---

# Firefox/Zen quick-capture extension

A tiny WebExtension under `extension/` that adds a toolbar button. Click it on any page and the CMS opens with the current tab's URL and title prefilled into the **Quick add** box.

## Install

### Temporary (for a single Firefox/Zen session)

1. `about:debugging#/runtime/this-firefox`
2. **Load Temporary Add-on…**
3. Select `extension/manifest.json`.

### Packaged (`.xpi`)

```bash
just extension
```

Produces `pg-cms-quick-capture.xpi` at the repo root. In Zen, go to `about:debugging` → **Load Temporary Add-on** and select the `.xpi`. For a signed, permanent install, run it through `web-ext sign` or publish to AMO.

## Configuration

Right-click the toolbar button → **Manage Extension** → **Preferences**. One field: the CMS base URL. Defaults to `http://localhost:8000`.

If you expose the CMS over Tailscale, point the extension at that URL (e.g. `http://100.x.y.z:8000`) so the button works from any browser on your tailnet.

## How it works

Clicking the icon opens:

```
<CMS_BASE>/quick?url=<tab.url>&title=<tab.title>
```

`/quick` redirects to the homepage (`/`) with those query params carried across. The homepage's **Quick add** card renders them as "Capturing: <url>" with a type picker. Pick a type → redirected to `/c/<type>/new?url=...&title=...` → the new-record form is prefilled with:

- `external_link` (or `url`) = tab URL
- `title` = tab title
- `slug` = auto-slugified from title

You fill the rest and save as usual. Auto-publish / syndication / webmention tracking all apply — the extension is just a way to seed the capture form.

## Files

| File             | Purpose                                              |
| ---------------- | ---------------------------------------------------- |
| `manifest.json`  | WebExtension manifest (browser_action + permissions) |
| `popup.html/.js` | Toolbar popup (click → open tab)                     |
| `options.html/.js` | Prefs page (CMS base URL)                          |
| `icon.svg`       | Toolbar icon                                         |
