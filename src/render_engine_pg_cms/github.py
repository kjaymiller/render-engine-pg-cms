"""Trigger the site's GitHub Actions publish workflow."""
from __future__ import annotations

import httpx

from .config import Config


class GitHubError(RuntimeError):
    pass


def _headers(cfg: Config) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {cfg.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def trigger_publish(cfg: Config) -> None:
    if not cfg.github_token or not cfg.github_repo:
        raise GitHubError(
            "GITHUB_TOKEN and GITHUB_REPO must be set to trigger a rebuild."
        )
    url = (
        f"https://api.github.com/repos/{cfg.github_repo}"
        f"/actions/workflows/{cfg.github_workflow}/dispatches"
    )
    resp = httpx.post(url, headers=_headers(cfg), json={"ref": cfg.github_ref}, timeout=15)
    if resp.status_code >= 300:
        raise GitHubError(
            f"GitHub dispatch failed ({resp.status_code}): {resp.text}"
        )


def latest_run(cfg: Config) -> dict | None:
    """Return the most recent workflow run for the configured workflow, or None."""
    if not cfg.github_token or not cfg.github_repo:
        return None
    url = (
        f"https://api.github.com/repos/{cfg.github_repo}"
        f"/actions/workflows/{cfg.github_workflow}/runs?per_page=1"
    )
    resp = httpx.get(url, headers=_headers(cfg), timeout=15)
    if resp.status_code >= 300:
        raise GitHubError(
            f"GitHub run lookup failed ({resp.status_code}): {resp.text}"
        )
    runs = resp.json().get("workflow_runs") or []
    if not runs:
        return None
    r = runs[0]
    return {
        "id": r.get("id"),
        "status": r.get("status"),            # queued | in_progress | completed
        "conclusion": r.get("conclusion"),    # success | failure | ... | None while running
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
        "html_url": r.get("html_url"),
        "display_title": r.get("display_title") or r.get("name"),
        "event": r.get("event"),
    }
