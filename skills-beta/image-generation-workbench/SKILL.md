---
name: image-generation-workbench
description: |
  Use when a task needs AI-generated or AI-edited bitmap assets, source-backed
  screenshot/card/UI annotation, multi-turn visual repair, generated-image QA,
  variant comparison, or green-screen components. Load for work that will call
  the local image workbench CLI or needs its reference cases. Do not load for
  exact text layout, vector-only diagrams, or document composition unless a
  generated raster image is part of the workflow.
metadata:
  version: "1.0"
  short-description: OpenAI image generation, repair, and visual QA workflow
---

# Image Generation Workbench

## Default Stance

Use Image 2 for visual integration and style. Use deterministic tools for exact
text, layout, measurements, captions, and final document placement.

- Use **Responses API + `image_generation`** when you need multi-turn repair,
  multiple reference images, or an agent to interpret source images before
  generating. This workbench supports only the latest image model,
  `gpt-image-2`; callers do not choose a separate image model.
- Use **Images API** for a simple one-shot generate/edit call where conversation
  state is not needed; this workbench uses `gpt-image-2`.
- Keep long prose, legal/rules wording, Chinese text, bilingual labels, and page
  composition outside the raster image when exact edits matter.
- Always inspect outputs visually. A successful API response is not QA.

## CLI Contract

Main tool: `scripts/image_workbench.py`

- Before choosing parameters, run:

  ```bash
  uv run --script scripts/image_workbench.py profiles --json
  uv run --script scripts/image_workbench.py <subcommand> --help
  ```

- Use `--json` when another agent, script, or CI job consumes stdout. Structured
  stdout is JSON metadata or profiles; stderr is for validation, auth, and API
  errors.
- Without `--json`, stdout is only the output path and optional response ID.
- Validation, auth, and API errors exit non-zero with stdout empty.
- Do not invent flags. If a parameter is not in subcommand help or
  `profiles --json`, do not pass it.
- `annotate-image`, `repair-image`, `diagnose-image`, `response-image`,
  `image-generate`, and `image-edit` can call the OpenAI API and are **billable
  remote actions**. `contact-sheet`, `chroma-alpha`, and reference `case.py`
  scripts without `--run-cli` are local-only.
- Pass credentials through environment variables only. Do not write API keys
  into prompts, command files, logs, metadata, or committed examples.

## Quick Start

Run from the target project root so image inputs and outputs stay
project-relative. Resolve `scripts/image_workbench.py` relative to this skill
directory.

```bash
export OPENAI_API_KEY=...
# Optional when using an OpenAI-compatible proxy:
export OPENAI_BASE_URL=...
uv run --script scripts/image_workbench.py annotate-image \
  --image path/to/source-screenshot.png \
  --aspect-policy match-input \
  --quality high \
  --output-format png \
  --detail high \
  --background auto \
  --out outputs/visuals/tutorial-figure.png \
  --json
```

OpenAI-compatible gateways are also supported:

```bash
export PYDANTIC_AI_GATEWAY_API_KEY=...
export PYDANTIC_AI_GATEWAY_BASE_URL=...
uv run --script scripts/image_workbench.py annotate-image \
  --image path/to/source-screenshot.png \
  --aspect-policy match-input \
  --quality high \
  --output-format png \
  --detail high \
  --background auto \
  --out outputs/visuals/tutorial-figure.png
```

Repair the previous result:

```bash
uv run --script scripts/image_workbench.py repair-image \
  --image path/to/source-screenshot.png \
  --previous-response-id resp_... \
  --issue "Move the label away from the card face and keep the arrow target unchanged." \
  --aspect-policy match-input \
  --quality high \
  --output-format png \
  --detail high \
  --background auto \
  --out outputs/visuals/tutorial-figure-v2.png \
  --json
```

Diagnose before the next repair turn:

```bash
uv run --script scripts/image_workbench.py diagnose-image \
  --source path/to/source-screenshot.png \
  --candidate outputs/visuals/tutorial-figure-v2.png \
  --criteria "The figure teaches the attack lane and preserves the card positions." \
  --detail high \
  --out outputs/visuals/tutorial-figure-v2.diagnosis.json \
  --json
```

Compare variants:

```bash
uv run --script scripts/image_workbench.py contact-sheet \
  --image outputs/visuals/tutorial-figure.png \
  --image outputs/visuals/tutorial-figure-v2.png \
  --out outputs/visuals/contact-sheet.png \
  --json
```

## Workflow

1. Write the teaching point in one sentence before generating.
2. Choose the visual pipe: `annotate-image` for source-backed first passes,
   `repair-image` for one-issue repair turns, `diagnose-image` for visual QA,
   `image-generate` for new artwork, and `image-edit` for direct one-shot edits.
3. State the output geometry before generating. Use `--aspect-policy
   match-input` for source-backed screenshots and cards, `portrait` or
   `landscape` for known placements, `square` for icons, `auto` when you
   intentionally delegate, or exact `--size WIDTHxHEIGHT`.
4. State quality, format, detail, and background explicitly. Recommended source
   tutorial parameters are `--aspect-policy match-input --quality high
   --output-format png --detail high --background auto`.
5. Attach original references on every repair turn. `previous_response_id`
   preserves conversation state, but re-attaching the source prevents visual
   drift.
6. Ask for short visible labels only. Put exact text in HTML, Typst, slides, or
   the host document.
7. Generate a first pass, inspect the PNG yourself, then run `diagnose-image`
   when the next Agent needs a structured visual read before repairing.
8. Repair one concrete issue per turn. Use the diagnosis
   `next_repair_issue` as the `repair-image --issue` only after checking that it
   matches what you see.
9. Make a contact sheet for variants and reject outputs with cropping, warped
   source facts, unreadable marks, fake text, or style drift.
10. Integrate the selected raster into the final document and inspect the
   rendered page.

## Choose The Visual Pipe

- Exact source state, object identity, UI state, card face, or screenshot
  content matters: use `annotate-image`, inspect the PNG, then use
  `repair-image` with `--previous-response-id` and the original image attached
  again.
- Exact text, rule terms, bilingual labels, code, tables, or captions matter:
  keep those words in Typst, HTML, slides, or the host document.
- The concept is abstract and does not need source-image fidelity: use
  deterministic vector drawing, Typst primitives, SVG/HTML, Mermaid-style
  diagrams, or another diagram tool.
- The desired result is a reusable icon, token, sticker, product widget, marker,
  or green-screen component: use `image-generate` or `response-image`, then QA
  and post-process locally.
- You already have a vector sketch or rough layout: attach it with `--image` and
  ask the image model to preserve geometry while improving surface style.

## Prompt Rules

- Preserve source-image facts over beauty.
- Use a small number of marks: spotlight, crop, dim, arrow, ring, numbered dot,
  or callout label.
- Do not ask the model to render long paragraphs or exact UI copy.
- Do not invent logos, watermarks, card names, screenshots, human hands, or
  domain facts not present in the source.
- Do not let a default canvas choose the composition. Say the intended aspect
  ratio or `--aspect-policy` in the command and in the prompt. Do not recompose
  portrait/mobile UI into a landscape board unless the user asked for that.
- On repair turns, fix only the stated issue.
- For reusable components, generate on a simple opaque or green-screen
  background, then post-process transparency locally.

## Tooling

The CLI is the parameter source of truth. Typer models command arguments,
Pydantic models result metadata, and pydantic-settings reads credentials from
environment variables. Do not add an internal agent loop unless the caller has no
visual inspection capability.

Prompt templates:

- `assets/prompts/tutorial-overlay.txt`
- `assets/prompts/revise-image.txt`
- `assets/prompts/diagnose-image.txt`
- `assets/prompts/greenscreen-component.txt`

Reference cases:

- `references/source-backed-mobile-ui/`
- `references/long-screenshot-guardrail/`

Riftbound-style playbook figures are just one example of this workflow: source
screenshot plus a short teaching point, Image 2 for the visual layer, Typst for
precise prose and final layout.

## Closeout Checks

After editing the tool:

```bash
uv run python -m py_compile scripts/image_workbench.py
uv run ruff check scripts/image_workbench.py
uv run ty check scripts/image_workbench.py
uv run --script scripts/image_workbench.py --help
```

Before finishing work that used real API keys:

```bash
rg -n "/[U]sers/|[g]ateway-us|[j]ihuanshe-openai|r[e]sponse_format|[s]k-proj|[p]ylf_v2|OPENAI_API_KEY=.*[s]k|PYDANTIC_AI_GATEWAY_API_KEY=.*[p]ylf" .
```
