---
title: "Publishing model"
description: "Why the CMS only fires workflow_dispatch and uses a trailing-edge debounce on save."
---

# Publishing model

The CMS never builds pages. It writes to Postgres and asks GitHub Actions to rebuild the site. There are two reasons.

**Render-engine builds belong in CI.** The site has its own dependencies, its own templates, its own theme assets. Coupling the CMS process to those would mean carrying a duplicate environment on every deploy box. GitHub Actions already runs the canonical build; `workflow_dispatch` is the right hook.

**Builds are slow; saves are fast.** A typical render-engine build takes 10–60 seconds. If every save blocked on a build, you'd write one paragraph, wait a minute, fix a typo, wait again. Decoupling save from publish means you can edit freely.

## Why a trailing-edge debounce

Naïve auto-publish ("publish on every save") fights you when you're editing. You save → build starts → you save again → second build starts → first build is now stale. Within a minute you've burned three runners.

Trailing-edge debounce flips this: every save *cancels* any pending publish task and schedules a fresh one for `AUTOPUBLISH_DEBOUNCE_SECONDS` later. Five rapid saves collapse into one publish, which fires after the editing burst ends.

The window default of 60s is tuned to the expected editing cadence: short enough that "I'm done now" feels prompt, long enough that a flurry of fixes won't trigger a build mid-flow.

## Draft gating via `date`

A post with `date` in the future is a draft. The auto-publisher checks the column and skips publishing for future-dated records. That means you can save freely while a post is embargoed; the deploy fires only when the `date` passes (or you save again past that point).

Types without a `date` column (e.g. `conferences`) always publish — the assumption being that those tables are reference data, not posts.

## Failure mode

`trigger_publish` raises `GitHubError` on any non-204 response. The auto-publish path catches and logs it; the user's save never fails because of a publish problem. The manual **Publish** button shows the error explicitly.

This means a misconfigured PAT silently fails to deploy. You'll notice via the GitHub Actions tab being quiet, not via a CMS error. Trade-off taken on purpose: the CMS is allowed to be useful even when the deploy pipeline is down.
