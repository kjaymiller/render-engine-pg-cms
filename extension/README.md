# pg-cms quick capture (Firefox)

Toolbar button that opens your pg-cms quick-capture page with the current tab's URL and title.

## Install (temporary)

1. Open `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on…**.
3. Select `extension/manifest.json`.

The extension lives until Firefox restarts. For a permanent install, package with `web-ext build` and load the signed `.xpi`.

## Configure

Right-click the toolbar button → **Manage Extension** → **Preferences** to change the CMS base URL (defaults to `http://localhost:8000`).

## How it works

Clicking the toolbar icon opens `<CMS>/quick?url=<tab.url>&title=<tab.title>` in a new tab, which redirects to the CMS homepage with the URL and title carried in the query string. The homepage's **Quick add** box lets you pick a content type; after selection you're forwarded to the normal edit form with URL / title / slug already prefilled.
