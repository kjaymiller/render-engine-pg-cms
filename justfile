set dotenv-load := true

# 1Password secret references
db_secret := "op://Private/personal-blog/credential"
mastodon_secret := "op://Private/mastodon.social/access-token"
webmention_secret := "op://Private/Webmention.io/credential"
bluesky_secret := "op://Private/bluesky/app password"
github_secret := "op://Private/GH-PAT - Kjaymiller.com PG CMS/credential"

default:
    @just --list

# Install dependencies into a uv-managed venv
install:
    uv sync

# Run the dev server with auto-reload
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    export CONNECTION_STRING="$(op read '{{db_secret}}')"
    export MASTODON_ACCESS_TOKEN="$(op read '{{mastodon_secret}}')"
    export WEBMENTION_IO_TOKEN="$(op read '{{webmention_secret}}')"
    export BLUESKY_APP_PASSWORD="$(op read '{{bluesky_secret}}')"
    export GITHUB_TOKEN="$(op read '{{github_secret}}')"
    uv run uvicorn render_engine_pg_cms.main:app --reload

# Run the server bound to 0.0.0.0 for LAN/tailscale access
serve host="0.0.0.0" port="8000":
    #!/usr/bin/env bash
    set -euo pipefail
    export CONNECTION_STRING="$(op read '{{db_secret}}')"
    export MASTODON_ACCESS_TOKEN="$(op read '{{mastodon_secret}}')"
    export WEBMENTION_IO_TOKEN="$(op read '{{webmention_secret}}')"
    export BLUESKY_APP_PASSWORD="$(op read '{{bluesky_secret}}')"
    export GITHUB_TOKEN="$(op read '{{github_secret}}')"
    uv run uvicorn render_engine_pg_cms.main:app --host {{host}} --port {{port}}

# Backfill webmention counts for all existing microblog + blog rows.
sync-webmentions:
    #!/usr/bin/env bash
    set -euo pipefail
    export CONNECTION_STRING="$(op read '{{db_secret}}')"
    export WEBMENTION_IO_TOKEN="$(op read '{{webmention_secret}}')"
    uv run python -c "from render_engine_pg_cms.config import load_config; from render_engine_pg_cms.webmention import sync_all; results = sync_all(load_config()); print(f'synced {len(results)} records'); [print(r) for r in results]"

# Trigger the site's publish workflow from the CLI (no browser needed)
publish:
    #!/usr/bin/env bash
    set -euo pipefail
    export CONNECTION_STRING="$(op read '{{db_secret}}')"
    export GITHUB_TOKEN="$(op read '{{github_secret}}')"
    uv run python -c "from render_engine_pg_cms.config import load_config; from render_engine_pg_cms.github import trigger_publish; trigger_publish(load_config()); print('dispatched')"

# Update locked dependencies
lock:
    uv lock --upgrade

# Drop and recreate the venv
clean:
    rm -rf .venv

# Run a SQL file against the content database (e.g. `just load-sql sql/mastodon_migration.sql`)
load-sql file:
    #!/usr/bin/env bash
    set -euo pipefail
    CONNECTION_STRING="$(op read '{{db_secret}}')"
    psql "$CONNECTION_STRING" -f {{file}}

# Backport mastodon_url / bluesky_url for existing records by matching timeline posts.
# `just backport-syndication` is a dry run; `just backport-syndication apply` writes matches.
backport-syndication mode="dry":
    #!/usr/bin/env bash
    set -euo pipefail
    export CONNECTION_STRING="$(op read '{{db_secret}}')"
    export MASTODON_ACCESS_TOKEN="$(op read '{{mastodon_secret}}')"
    export BLUESKY_APP_PASSWORD="$(op read '{{bluesky_secret}}')"
    if [ "{{mode}}" = "apply" ]; then
        uv run python -m render_engine_pg_cms.backport apply
    else
        uv run python -m render_engine_pg_cms.backport
    fi

# Package the Firefox/Zen extension into a loadable .xpi
extension:
    rm -f pg-cms-quick-capture.xpi
    cd extension && zip -r ../pg-cms-quick-capture.xpi . -x "*.DS_Store"
    @echo "→ pg-cms-quick-capture.xpi ready. Load it in Zen via about:debugging → Load Temporary Add-on."
