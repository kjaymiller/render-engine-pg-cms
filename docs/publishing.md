---
title: "Publishing"
description: "Publishing means asking GitHub Actions to rebuild the site. The CMS never builds pages itself — it only writes to the database and fires `workflow_dispatch`."
---

# Publishing

Publishing means asking GitHub Actions to rebuild the site. The CMS never builds pages itself — it only writes to the database and fires `workflow_dispatch`.

## Two paths: manual and automatic

Both run the same code (`github.trigger_publish(cfg)`), which POSTs to `POST /repos/{GITHUB_REPO}/actions/workflows/{GITHUB_WORKFLOW}/dispatches` with `{"ref": GITHUB_REF}`.

### Manual

- **Masthead → Publish** button on any page. Redirects to a small "dispatched" / "failed" confirmation page.
- **CLI**: `just publish`. Reads secrets from 1Password and calls `trigger_publish` directly.

### Automatic (on save)

When you create or update a record, the CMS schedules a publish with a **trailing-edge debounce**: rapid-fire saves within the debounce window collapse into one dispatch.

The flow:

1. `POST /c/{name}/new` or `POST /c/{name}/{id}` commits to the DB.
2. `schedule_autopublish(record)` fires.
3. Any pending publish task is cancelled.
4. A new task is scheduled to fire after `AUTOPUBLISH_DEBOUNCE_SECONDS` (default **60**).
5. If another save arrives before the timer expires, steps 3-4 repeat — the clock resets.

So five saves 10 seconds apart result in one publish, 60 seconds after the last save.

## Draft gating

A record is considered "live" (and worth publishing) when its `date` column is in the past or present. Records dated in the future don't trigger auto-publish — you can save freely while a post is embargoed and deploy will only happen once the `date` passes.

Content types without a `date` column (like `conferences`) always count as live — they publish freely.

## When auto-publish doesn't fire

- `AUTOPUBLISH=0` / `false` / `no` in the environment.
- `GITHUB_TOKEN` or `GITHUB_REPO` is unset (silently skipped).
- The record's `date` is in the future.
- The CMS process shut down during the debounce window (a re-save after restart will re-arm it).

## Errors

`trigger_publish` raises `GitHubError` on any non-204 response; the auto-publish path catches this, logs a warning, and never fails the user's save. The manual Publish button surfaces the error on the confirmation page.

## Permissions for the PAT

Fine-grained personal access token scoped to the site repo with:

- **Repository permissions → Actions → Read and write**

Nothing else is needed. The token is only used for `workflow_dispatch`.

## Related config

See [configuration.md](configuration.md#github-for-the-publish-button-and-auto-publish) for the full list of GitHub-related environment variables.
