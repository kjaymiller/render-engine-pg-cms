---
title: "AI suggestions"
description: "Why slug + description generation runs against a local/self-hosted chat backend, and how the prompts are tuned."
---

# AI suggestions

Two assistive features in the editor — **slug generation** and **description generation** — call a chat backend that speaks the OpenAI chat-completions protocol (`CHAT_BASE_URL`/`CHAT_MODEL`/`CHAT_API_KEY`, see [configuration](../reference/configuration.md)). That protocol is implemented by vLLM, MLX (omlx), llama.cpp's server, Ollama, OpenRouter, and OpenAI itself, so which one is actually running is a config change, not a code change. Point it at something self-hosted and no cloud API key, no data leaving the network, no per-request cost.

A third feature, **tag suggestion**, is not LLM-backed at all — it fuzzy-matches the post text against the existing tag library (`pg_trgm` word similarity). See [Tag suggestion](#tag-suggestion-not-an-llm-feature) below.

## Why local/self-hosted

This is a personal CMS used dozens of times a week. Round-tripping every save to a hosted LLM would be expensive in dollars and worse in latency — a small local/self-hosted model returns a slug in under a second. The quality bar isn't "perfect prose," it's "saved me typing"; a small model clears that bar comfortably.

## Graceful degradation

- **Slug generation** falls back to a rule-based slugify of the same input. The endpoint never returns 5xx — you always get a usable slug, with the `source` field reporting `ai` vs `fallback`.
- **Description generation** returns 503 on failure, with the field left empty so you can write your own. There's no meaningful fallback for a summary the way there is for a slug.

## Tag suggestion (not an LLM feature)

Tags are suggested by fuzzy-matching the post text against the existing tag library, not generated. Every suggestion is therefore an existing tag (`known` is always `true`) — there's no invention step, so there's no tag-sprawl problem to bias against.

## Output sanitization

The model's raw output can't be trusted to be a clean slug or sentence. Both endpoints post-process:

- **Slug**: piped through the same `_slugify` used for blob names. Strips quotes, collapses whitespace, caps length at 80.
- **Description**: strips wrapping quotes, collapses to the first paragraph, trims whitespace.

This means a creative model that returns `"my-post-title!"` or a multi-paragraph ramble still ends up producing a clean, predictable shape.

## Prompt tuning

`temperature: 0.2` for both. `max_tokens: 32` for the slug, `96` for the description — small budgets since both outputs are short. Input capped at 400 chars (slug) / 2000 chars (description) so a long post doesn't tank inference speed on constrained hardware.

If your backend serves a reasoning model (e.g. Qwen3), set `CHAT_DISABLE_THINKING=true` so responses aren't spent on reasoning content that never reaches the UI.
