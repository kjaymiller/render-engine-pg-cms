---
title: "AI suggestions"
description: "The CMS uses a local [Ollama](https://ollama.com/) server for two assistive features: **slug generation** and **tag suggestion**. Everything runs locally — no data leaves your machine, no cloud API costs."
---

# AI suggestions

The CMS uses a local [Ollama](https://ollama.com/) server for two assistive features: **slug generation** and **tag suggestion**. Everything runs locally — no data leaves your machine, no cloud API costs.

Both features degrade gracefully when Ollama isn't running: slug generation falls back to rule-based slugify, tag suggestion returns an error you can see in the UI.

## Ollama setup

```bash
# Install (macOS/Linux)
brew install ollama       # or: curl -fsSL https://ollama.com/install.sh | sh

# Pull a model (2 GB, fast on CPU, good enough for slugs/tags)
ollama pull llama3.2:3b

# Run the server (auto-starts on macOS)
ollama serve
```

The CMS assumes `http://localhost:11434` by default. Override with `OLLAMA_URL` if Ollama runs elsewhere.

## Slug suggestion

**Button**: sparkle icon next to the `slug` input on any edit form.

**Behavior**:
1. Reads the most meaningful field available — title → name → description → content.
2. POSTs to `/api/ai/slug` with that text.
3. Server sends a tightly-worded prompt asking for lowercase-hyphen output only.
4. Server sanitizes the raw response through the same `_slugify` used for blob names (strips quotes, collapses whitespace, caps length at 80).
5. Field is populated; a hint line reports `Generated via Ollama` or `Used rule-based fallback`.

**Fallback**: if Ollama is unreachable or times out, the endpoint returns a rule-based slug from the same input plus `source: "fallback"`. The user still gets a usable slug.

**Prompt tuning**: `temperature: 0.2`, `num_predict: 32`. Input capped at 400 chars so long posts don't tank inference speed.

## Tag suggestion

**Button**: sparkle icon next to the comma-separated `tags` input on any type with tag support.

**Behavior**:
1. Reads `title + content/description` from the form.
2. Loads every existing tag name from the `tags` table.
3. POSTs to `/api/ai/tags` with the text.
4. Server builds a prompt that **strongly prefers reuse** over invention:
   > Only invent a NEW tag if none of the existing tags capture the post's topic.
5. Existing-tag list capped at 200 entries in the prompt to keep inference cheap.
6. Response is split on commas, each entry normalized (lowercased, whitespace→hyphens), deduped, length-gated (2-40 chars).
7. Each suggestion is marked `known: true/false` against the actual tags table.
8. UI renders them as chips:
   - **Known** chips: clay/navy, no prefix — `python`
   - **New** chips: sage green, `+` prefix — `+ webmentions`
   - **Active** (currently in the input): dark — click to remove
9. Hint line summarizes: `Got 4 suggestions (3 existing, 1 new). Click to add/remove.`

Clicking a chip toggles it in/out of the comma-separated `tags` input. Order is preserved; duplicates are filtered.

**Prompt tuning**: `temperature: 0.2`, `num_predict: 32`, 45s timeout. Post context capped at 1200 chars.

## Endpoints

### `POST /api/ai/slug`

| Param  | Type        | Notes |
| ------ | ----------- | ----- |
| `text` | form field  | Required. The title/content to slug. |

Response:
```json
{ "slug": "my-post-title", "source": "ai" }
```
Or on fallback:
```json
{ "slug": "my-post-title", "source": "fallback", "error": "Network error: ..." }
```
Never returns 5xx — always produces a usable slug.

### `POST /api/ai/tags`

| Param  | Type        | Notes |
| ------ | ----------- | ----- |
| `text` | form field  | Required. Post body for topic detection. |

Response:
```json
{
  "suggestions": [
    {"tag": "python", "known": true},
    {"tag": "indieweb", "known": true},
    {"tag": "webmentions", "known": false}
  ],
  "source": "ai"
}
```
Returns 503 on Ollama failure (no fallback — without AI there's nothing useful to suggest).

## Choosing a model

`llama3.2:3b` is the default because it's small enough to run on any laptop's CPU and still produces clean slugs. For better tag suggestions on a long post, bump to something larger:

```bash
ollama pull llama3.1:8b        # better topic understanding
ollama pull qwen2.5:7b         # strong general performance
```

Then set `OLLAMA_MODEL=llama3.1:8b` in your env. The prompts don't change.

## Env vars

See [configuration.md](configuration.md#ollama-ai-slug--tag-suggestions).
