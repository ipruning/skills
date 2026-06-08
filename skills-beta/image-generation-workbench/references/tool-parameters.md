# Tool Parameters

## High-level commands

Implementation primitives:

- Typer owns command parsing and help output.
- Pydantic owns result metadata models and JSON serialization.
- pydantic-settings owns environment credential resolution.
- OpenAI SDK remains the direct API layer; there is no internal agent loop.

- `annotate-image`: recommended first pass for source-backed tutorial overlays.
- `response-image`: Responses API with `image_generation`; best default.
- `repair-image`: Responses API repair turn using `previous_response_id` plus
  re-attached original images.
- `diagnose-image`: Responses API visual QA pass; reads source and candidate
  images, then writes structured repair guidance.
- `image-generate`: direct Images API generation.
- `image-edit`: direct Images API edit with one or more input images.
- `contact-sheet`: local comparison sheet; no API call.
- `chroma-alpha`: local green-screen to alpha post-processing; no API call.

## Responses API parameters

- `--prompt`: prompt text or prompt file.
- `--image`: reference image path; pass multiple times for multiple images.
- `--out`: output file path.
- `--previous-response-id`: prior Responses API response ID for multi-turn
  repair.
- `--reasoning-model` / `--model`: controller model. Default: `gpt-5.5`.
- `--image-model`: optional image generation tool model override. Omitted by
  default so the Responses API can select the GPT Image model.
- `--size`: output size. Default: `1536x1024`.
- `--quality`: `low`, `medium`, `high`, or `auto`. Default: `medium`.
- `--output-format`: `png`, `jpeg`, or `webp`.
- `--action`: `generate`, `edit`, or `auto`. Default: `auto`.
- `--detail`: reference image detail: `low`, `high`, `auto`, or `original`.
- `--background`: `transparent`, `opaque`, or `auto`.
- `--mask`: input image mask for edit operations.
- `--input-fidelity`: only for models that support it; blocked with
  `gpt-image-2`.
- `--moderation`: `auto` or `low`.
- `--output-compression`: compression level for formats that support it.
- `--partial-images`: `0` to `3`; enables streaming and saves partial frames.
- `--timeout`: request timeout in seconds.

Outputs:

- final image at `--out`;
- compact metadata at `--out.json`;
- full response payload at `--out.response.json`;
- optional partial frames as `*.partial-N.*`.
- `--json` prints one compact JSON object to stdout for agents and scripts.
  Without `--json`, stdout is a minimal human-readable result path plus
  response ID when available. Errors go to stderr with non-zero exit codes.
- JSON stdout and metadata files are produced from Pydantic models.

## `annotate-image`

`annotate-image` is a convenience wrapper around `response-image` with the
default tutorial overlay prompt, `action=edit`, PNG output, and no
conversation-state input. Use it when the input image already contains the facts
the reader needs.

- `--image`: required source image; pass multiple times if needed.
- `--out`: required output PNG path.
- `--prompt`: optional override prompt.
- `--reasoning-model`, `--image-model`, `--size`, `--quality`, `--detail`,
  `--timeout`: same meaning as `response-image`. `--image-model` remains an
  optional override and is omitted by default.

For wide screenshots, keep the output wide too. `1024x1024` is useful for cheap
smoke tests but can crop important edges.

## `diagnose-image`

Use `diagnose-image` between generation and repair when an Agent needs to
convert visual inspection into a concrete next step.

- `--source`: original source/reference image; pass multiple times if needed.
- `--candidate`: generated candidate image to evaluate; pass multiple times if
  comparing alternatives.
- `--criteria`: teaching goal or acceptance criteria text/file.
- `--out`: required diagnosis JSON path.
- `--prompt`: optional override prompt.
- `--reasoning-model` / `--model`: multimodal judge model. Default: `gpt-5.5`.
- `--detail`: image detail for visual inspection. Default: `high`.
- `--json`: print result metadata as JSON.
- `--timeout`: request timeout in seconds.

The output JSON includes `diagnosis`. When the model returns valid JSON,
`diagnosis.next_repair_issue` is the single-sentence repair instruction to feed
to `repair-image --issue` after the Agent checks it against the image.

## Images API parameters

Direct commands expose the common Images API knobs:

- `--model`: image model. Default: `gpt-image-2`.
- `--prompt`: prompt text or file.
- `--image`: input image for edit; pass multiple times when supported.
- `--mask`: optional edit mask.
- `--out`: final image path.
- `--size`, `--quality`, `--background`, `--output-format`,
  `--output-compression`, `--moderation`, `--n`, `--input-fidelity`,
  `--timeout`.
- For `gpt-image-2`, use `--quality low|medium|high|auto`.

The script expects image data in the API response and writes metadata next to
the image.

Use `--json` for machine-readable stdout. The JSON object includes output,
metadata, and response paths but never credential values.

When using an OpenAI-compatible gateway, direct Images API routes can be blocked
by gateway-specific cost-estimation rules even when Responses API image
generation works. In that case, prefer `response-image` or `annotate-image`.

## Safety and key handling

- Standard OpenAI credentials:
  - `OPENAI_API_KEY`
  - optional `OPENAI_BASE_URL` for OpenAI-compatible proxies
- Pydantic AI Gateway credentials:
  - `PYDANTIC_AI_GATEWAY_API_KEY`
  - optional `PYDANTIC_AI_GATEWAY_BASE_URL`
- If both key families are set, the tool uses `OPENAI_API_KEY` first.
- Never write API keys into prompts, skill files, metadata JSON, or shell
  history snippets committed to a repository.
- Output metadata records only which key environment variable was used and
  whether a base URL was configured. It does not store credential values.
- Credentials are resolved through pydantic-settings. `OPENAI_API_KEY` takes
  precedence over `PYDANTIC_AI_GATEWAY_API_KEY`.
- Scan before closeout:

```bash
rg -n "/[U]sers/|[g]ateway-us|[j]ihuanshe-openai|[r]esponse_format|[s]k-proj|[p]ylf_v2|OPENAI_API_KEY=.*[s]k|PYDANTIC_AI_GATEWAY_API_KEY=.*[p]ylf" .
```
