---
title: "AI suggestions"
description: "Why slug + tag generation runs against a local Ollama and how the prompts are tuned."
---

# AI suggestions

Two assistive features in the editor — **slug generation** and **tag suggestion** — call a local [Ollama](https://ollama.com/) server. Everything runs on the same machine. No cloud API key, no data leaves the network, no per-request cost.

## Why local

This is a personal CMS used dozens of times a week. Round-tripping every save to a hosted LLM would be expensive in dollars and worse in latency — local llama3.2:3b returns a slug in under a second on a laptop CPU. The quality bar isn't "perfect prose," it's "saved me typing"; a small local model clears that bar comfortably.

The default model (`llama3.2:3b`) is chosen for that ratio: ~2 GB on disk, no GPU required, good enough for short-form output. Bumping to `llama3.1:8b` or `qwen2.5:7b` improves tag quality on long posts; the prompts don't need changing.

## Graceful degradation

The two features handle Ollama-unavailable differently:

- **Slug generation** falls back to a rule-based slugify of the same input. The endpoint never returns 5xx — you always get a usable slug, with the `source` field reporting `ai` vs `fallback`.
- **Tag suggestion** returns 503 with no fallback. There's no useful rule-based tag — without an LLM there's nothing to suggest.

The asymmetry mirrors what's actually useful: a slug is a deterministic transform on text and you want one regardless. Tags need topical understanding, which a substring transform can't fake.

## Tag prompt: prefer reuse over invention

The tag prompt explicitly biases toward reuse:

> Only invent a NEW tag if none of the existing tags capture the post's topic.

Without that bias, the model invents synonyms (`webmention`, `webmentions`, `web-mentions`) that fragment the tag space. The existing-tag list is capped at 200 entries to keep prompt size bounded; on a site with thousands of tags this would need a retrieval step, but at this scale the full list fits comfortably.

The chip UI marks each suggestion as known (existing tag, clay/navy chip) or new (sage green, `+` prefix), so you can see at a glance whether you're growing the taxonomy or reusing it.

## Output sanitization

The model's raw output can't be trusted to be a clean slug or comma-list. Both endpoints post-process:

- **Slug**: piped through the same `_slugify` used for blob names. Strips quotes, collapses whitespace, caps length at 80.
- **Tags**: split on commas, lowercased, whitespace→hyphens, deduped, length-gated 2–40 chars, each marked `known: true/false` against the actual tags table.

This means a creative model that returns `"my-post-title!"` or `Tags: python, webmentions, indieweb` still ends up producing a clean, predictable shape.

## Prompt tuning

`temperature: 0.2`, `num_predict: 32` for both. Low temperature because we want deterministic-ish output; small token budget because slugs and tag lists are short. Input capped at 400 chars (slug) / 1200 chars (tags) so a long post doesn't tank inference speed on CPU.
