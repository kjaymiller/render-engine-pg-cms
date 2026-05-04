---
title: "Trigger a publish"
description: "Fire the GitHub Actions workflow that rebuilds the site, manually or automatically."
---

# Trigger a publish

The CMS never builds pages itself — it only writes to the database and fires `workflow_dispatch` on a GitHub Actions workflow. For the why, see [explanation/publishing-model.md](../explanation/publishing-model.md).

## One-time setup

Create a fine-grained PAT scoped to your site repo with **Repository permissions → Actions: Read and write**. Then:

```
GITHUB_TOKEN=<pat>
GITHUB_REPO=owner/repo
GITHUB_WORKFLOW=publish.yml          # default
GITHUB_REF=main                      # default
```

## Manually

- **UI**: click **Publish** in the masthead. A confirmation page reports success or failure.
- **CLI**: `just publish`.

## Automatically on save

Auto-publish is on by default. Every record save schedules a publish that fires `AUTOPUBLISH_DEBOUNCE_SECONDS` (default 60s) after your *last* save. Five saves 10 seconds apart → one publish, 60s after the last.

Disable it:

```
AUTOPUBLISH=0
```

Tune the debounce window:

```
AUTOPUBLISH_DEBOUNCE_SECONDS=30
```

## When auto-publish doesn't fire

- `AUTOPUBLISH=0` / `false` / `no`.
- `GITHUB_TOKEN` or `GITHUB_REPO` unset.
- Record's `date` is in the future (drafts don't publish).
- CMS process restarted during the debounce window — re-save to re-arm.
