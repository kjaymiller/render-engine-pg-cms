"""Thin client for an OpenAI-chat-completions-compatible LLM server.

Talks POST {base}/chat/completions — the shape vLLM, MLX (omlx), llama.cpp's
server, Ollama, OpenRouter and OpenAI itself all agree on. Used for a couple
of tight, single-turn prompts (slug + description suggestions) — no
streaming, no tool use. If the server is unreachable or the response is
unusable, callers fall back to rule-based slugify.

Config (env vars, wired through Config):
  CHAT_BASE_URL         — e.g. http://100.119.74.47:8001/v1 (must include /v1
                           if the server expects it — this appends
                           /chat/completions verbatim)
  CHAT_MODEL            — exactly as the server reports it via GET /v1/models
  CHAT_API_KEY          — optional; omitted from the request entirely when
                           unset (a local server may not check it; one that
                           does 401s on a missing/garbage key)
  CHAT_DISABLE_THINKING — "true" to pass chat_template_kwargs.enable_thinking
                           = false, for reasoning models (e.g. Qwen3) that
                           would otherwise burn the response on reasoning
                           content nobody reads. Not part of the OpenAI
                           protocol proper — opt-in per deployment since a
                           server that doesn't understand the field may
                           reject the whole request.
"""
from __future__ import annotations

import logging

import httpx

from .config import Config

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
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


def _post_chat(
    cfg: Config,
    prompt: str,
    *,
    timeout: float = 30.0,
    max_tokens: int = 32,
) -> str:
    if not cfg.chat_base_url:
        raise LLMError("CHAT_BASE_URL is not configured.")
    endpoint = f"{cfg.chat_base_url.rstrip('/')}/chat/completions"
    payload: dict = {
        "model": cfg.chat_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        # Low temperature — we want deterministic, terse output, not creativity.
        "temperature": 0.2,
    }
    if cfg.chat_disable_thinking:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    headers = {"content-type": "application/json"}
    # Omitted entirely when there's no key: a server that doesn't check
    # rejects nothing, but sending "Bearer " is a 401 against one that does.
    if cfg.chat_api_key:
        headers["authorization"] = f"Bearer {cfg.chat_api_key}"
    try:
        r = httpx.post(endpoint, json=payload, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        raise LLMError(f"Network error: {exc}") from exc
    if r.status_code >= 400:
        raise LLMError(f"Chat backend {r.status_code}: {r.text[:300]}")
    data = r.json()
    if data.get("error", {}).get("message"):
        raise LLMError(f"Chat backend error: {data['error']['message']}")
    choices = data.get("choices") or []
    if not choices:
        raise LLMError("Chat backend returned no choices.")
    return (choices[0].get("message", {}).get("content") or "").strip()


def suggest_slug(cfg: Config, text: str) -> str:
    """Return an AI-generated slug for `text`. Raises LLMError on failure.

    Caller should wrap in try/except and fall back to rule-based slugify.
    """
    text = (text or "").strip()
    if not text:
        raise LLMError("Empty input.")
    # Cap input so we don't send a whole blog post — first line + first
    # paragraph is plenty of context for a slug.
    short = text[:400]
    raw = _post_chat(cfg, SLUG_PROMPT.format(text=short))
    # Models sometimes wrap output in quotes or add trailing punctuation even
    # when told not to. Grab the first non-empty line as the candidate.
    line = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
    return line


def suggest_description(cfg: Config, text: str) -> str:
    """Return an AI-generated one-sentence summary of `text`. Raises
    LLMError on failure — caller decides whether to surface the error or
    leave the field empty.
    """
    text = (text or "").strip()
    if not text:
        raise LLMError("Empty input.")
    short = text[:2000]
    raw = _post_chat(
        cfg, DESCRIPTION_PROMPT.format(text=short),
        timeout=45.0, max_tokens=96,
    )
    # Strip wrapping quotes the model sometimes adds despite instructions.
    summary = raw.strip().strip('"').strip("'").strip()
    # Take only the first paragraph if the model produced more.
    summary = summary.split("\n\n", 1)[0].replace("\n", " ").strip()
    return summary
