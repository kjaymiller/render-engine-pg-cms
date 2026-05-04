"""Thin client for a local Ollama server (https://ollama.com).

We only use /api/generate and a tight prompt — no streaming, no tool use.
If the server is unreachable or the response is unusable, callers fall back
to rule-based slugify.

Config (env vars, wired through Config):
  OLLAMA_URL    — default http://localhost:11434
  OLLAMA_MODEL  — default llama3.2:3b (small enough for CPU, good enough for slugs)
"""
from __future__ import annotations

import logging

import httpx

from .config import Config

log = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    pass


SLUG_PROMPT = """Generate a URL slug for this post title or content. \
Respond with ONLY the slug — no explanation, no quotes, no punctuation. \
Use lowercase letters, numbers, and hyphens only. Maximum 5 words. \
Prefer concrete nouns over filler words.

Input: {text}

Slug:"""


DESCRIPTION_PROMPT = """Write a one-sentence summary of this blog post for \
use as a meta description / excerpt. Aim for 20-30 words. Plain prose, no \
hashtags, no quotes, no markdown. Respond with ONLY the sentence.

Post:
{text}

Summary:"""


def _post_generate(
    cfg: Config,
    prompt: str,
    *,
    timeout: float = 30.0,
    num_predict: int = 32,
    format_schema: dict | None = None,
) -> str:
    url = f"{cfg.ollama_url.rstrip('/')}/api/generate"
    payload: dict = {
        "model": cfg.ollama_model,
        "prompt": prompt,
        "stream": False,
        # Keep the model resident between requests so we don't pay the
        # cold-load tax on every call. "30m" means Ollama unloads it after
        # 30 minutes of idle.
        "keep_alive": "30m",
        # Low temperature — we want deterministic, terse output, not creativity.
        "options": {"temperature": 0.2, "num_predict": num_predict},
    }
    if format_schema is not None:
        payload["format"] = format_schema
    try:
        r = httpx.post(url, json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise OllamaError(f"Network error: {exc}") from exc
    if r.status_code >= 400:
        raise OllamaError(f"Ollama {r.status_code}: {r.text[:300]}")
    data = r.json()
    return (data.get("response") or "").strip()


def suggest_slug(cfg: Config, text: str) -> str:
    """Return an AI-generated slug for `text`. Raises OllamaError on failure.

    Caller should wrap in try/except and fall back to rule-based slugify.
    """
    text = (text or "").strip()
    if not text:
        raise OllamaError("Empty input.")
    # Cap input so we don't send a whole blog post to Ollama — first line +
    # first paragraph is plenty of context for a slug.
    short = text[:400]
    raw = _post_generate(cfg, SLUG_PROMPT.format(text=short))
    # Models sometimes wrap output in quotes or add trailing punctuation even
    # when told not to. Grab the first non-empty line as the candidate.
    line = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
    return line


def suggest_description(cfg: Config, text: str) -> str:
    """Return an AI-generated one-sentence summary of `text`. Raises
    OllamaError on failure — caller decides whether to surface the error
    or leave the field empty.
    """
    text = (text or "").strip()
    if not text:
        raise OllamaError("Empty input.")
    short = text[:2000]
    raw = _post_generate(
        cfg, DESCRIPTION_PROMPT.format(text=short),
        timeout=45.0, num_predict=96,
    )
    # Strip wrapping quotes the model sometimes adds despite instructions.
    summary = raw.strip().strip('"').strip("'").strip()
    # Take only the first paragraph if the model produced more.
    summary = summary.split("\n\n", 1)[0].replace("\n", " ").strip()
    return summary


