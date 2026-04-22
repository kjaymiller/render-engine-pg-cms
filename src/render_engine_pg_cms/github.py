"""Trigger the site's GitHub Actions publish workflow."""
from __future__ import annotations

import httpx

from .config import Config


class GitHubError(RuntimeError):
    pass


def trigger_publish(cfg: Config) -> None:
    if not cfg.github_token or not cfg.github_repo:
        raise GitHubError(
            "GITHUB_TOKEN and GITHUB_REPO must be set to trigger a rebuild."
        )
    url = (
        f"https://api.github.com/repos/{cfg.github_repo}"
        f"/actions/workflows/{cfg.github_workflow}/dispatches"
    )
    headers = {
        "Authorization": f"Bearer {cfg.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp = httpx.post(url, headers=headers, json={"ref": cfg.github_ref}, timeout=15)
    if resp.status_code >= 300:
        raise GitHubError(
            f"GitHub dispatch failed ({resp.status_code}): {resp.text}"
        )
