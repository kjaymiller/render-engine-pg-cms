"""Thin client for a local Ollama server (https://ollama.com).

We only use /api/generate and a tight prompt — no streaming, no tool use.
If the server is unreachable or the response is unusable, callers fall back
to rule-based slugify.

Config (env vars, wired through Config):
  OLLAMA_URL    — default http://localhost:11434
  OLLAMA_MODEL  — default llama3.2:3b (small enough for CPU, good enough for slugs)
"""
from __future__ import annotations

import json
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


TAGS_PROMPT_WITH_EXISTING = """Suggest 3-5 tags for this post.
Tags should be short (1-3 words each), lowercase, hyphen-separated if multi-word.

Here is the existing tag library. Strongly prefer reusing these when they fit:
{existing}

For each tag you suggest, set "reused" to true if it is copied verbatim from \
the existing library above, or false if it is a new tag you invented. \
Only invent a new tag when no existing tag captures the topic. New tags should \
match the style of the existing ones.

Post:
{text}"""

TAGS_PROMPT_NO_EXISTING = """Suggest 3-5 tags for this post.
Tags should be short (1-3 words each), lowercase, hyphen-separated if multi-word.
Mark every tag's "reused" field as false (no existing library to reuse from).

Post:
{text}"""

# JSON schema enforced on Ollama's side via the `format` parameter. Models
# that honor structured output (llama3.1+, qwen2.5+, etc.) will emit valid
# JSON matching this shape — saves us the regex gymnastics.
TAGS_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tag": {"type": "string"},
                    "reused": {"type": "boolean"},
                },
                "required": ["tag", "reused"],
            },
        },
    },
    "required": ["tags"],
}


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


def suggest_tags(cfg: Config, text: str, existing: list[str]) -> list[dict]:
    """Return AI tag suggestions as [{"tag": str, "reused": bool}, ...].

    Uses Ollama's structured-output mode (`format` = JSON schema) so the model
    returns parseable JSON and self-reports which tags are copied from the
    existing library vs. newly invented. Caller should still verify `reused`
    against the actual library (source of truth) — the model occasionally
    lies in either direction.
    """
    text = (text or "").strip()
    if not text:
        raise OllamaError("Empty input.")
    short = text[:1200]
    if existing:
        sample = ", ".join(existing[:200])
        prompt = TAGS_PROMPT_WITH_EXISTING.format(existing=sample, text=short)
    else:
        prompt = TAGS_PROMPT_NO_EXISTING.format(text=short)

    raw = _post_generate(
        cfg, prompt, timeout=45.0, num_predict=256, format_schema=TAGS_SCHEMA,
    )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OllamaError(f"Model did not return valid JSON: {exc}") from exc

    items = parsed.get("tags") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        raise OllamaError("Model JSON missing 'tags' array.")

    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        tag = (item.get("tag") or "").strip().strip('"').strip("'")
        if not tag:
            continue
        out.append({"tag": tag, "reused": bool(item.get("reused"))})
    return out
