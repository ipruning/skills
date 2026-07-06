---
name: image-generation-workbench
description: "Use when a task needs generated or edited bitmap assets, visual QA, screenshot-backed image work, UI annotations, variants, or the local image workbench CLI."
metadata:
  version: "1.0"
  short-description: gpt-image-2 generation, repair, and visual QA workflow
---

# Image Generation Workbench

## Core Rules

Use `gpt-image-2` for visual integration and style. Use deterministic tools for
exact text, layout, measurements, captions, and final document placement.

- Use **Responses API + `image_generation`** when the task needs multi-turn
  repair, multiple input images, or source-image interpretation before generating.
- Use **Images API** for a simple one-shot generate/edit call where conversation
  state is not needed.
- The CLI fixes the image model (`gpt-image-2`); there is no model flag, so do
  not pass a separate image model. Inspect `profiles --json` for the recommended
  parameter bundles and each subcommand's `--help` for its flags before choosing
  parameters.
- Keep long prose, legal/rules wording, Chinese text, bilingual labels, and page
  composition outside the raster image when exact edits matter.
- Always inspect generated images visually. A successful API response is not QA.

## CLI Contract

The CLI entrypoint is `scripts/image_workbench.py`, resolved relative to this
Skill directory.

- Run parameter discovery before choosing parameters:

  ```bash
  SKILL_DIR=/absolute/path/to/image-generation-workbench
  uv run --script "$SKILL_DIR/scripts/image_workbench.py" profiles --json
  uv run --script "$SKILL_DIR/scripts/image_workbench.py" <subcommand> --help
  ```

- Use `--json` when another process, script, or CI job consumes stdout. Structured
  stdout contains JSON metadata or profiles; stderr carries validation, auth, and
  API errors.
- Plain stdout contains only the output path and optional response ID.
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
project-relative. Set `SKILL_DIR` to the directory that contains this `SKILL.md`;
run the workbench script through that absolute path.

```bash
SKILL_DIR=/absolute/path/to/image-generation-workbench
export OPENAI_API_KEY=...
# Optional when using an OpenAI-compatible proxy:
export OPENAI_BASE_URL=...
uv run --script "$SKILL_DIR/scripts/image_workbench.py" annotate-image \
  --image path/to/source-screenshot.png \
  --aspect-policy match-input \
  --quality high \
  --output-format png \
  --detail high \
  --background auto \
  --out outputs/visuals/tutorial-figure.png \
  --json
```

For OpenAI-compatible gateways, set the gateway credential pair instead:

```bash
export PYDANTIC_AI_GATEWAY_API_KEY=...
export PYDANTIC_AI_GATEWAY_BASE_URL=...
```

Each CLI run is independent: `--previous-response-id` carries the API
conversation, not the CLI parameters, so every generating command still passes
its own geometry and quality flags. Follow-up commands add the issue-specific
arguments on top of the same required set:

```bash
uv run --script "$SKILL_DIR/scripts/image_workbench.py" repair-image \
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

uv run --script "$SKILL_DIR/scripts/image_workbench.py" diagnose-image \
  --source path/to/source-screenshot.png \
  --candidate outputs/visuals/tutorial-figure-v2.png \
  --criteria "The figure teaches the attack lane and preserves the card positions." \
  --detail high \
  --out outputs/visuals/tutorial-figure-v2.diagnosis.json \
  --json

uv run --script "$SKILL_DIR/scripts/image_workbench.py" contact-sheet \
  --image outputs/visuals/tutorial-figure.png \
  --image outputs/visuals/tutorial-figure-v2.png \
  --out outputs/visuals/contact-sheet.png \
  --json
```

## Workflow

1. Write the teaching point in one sentence before generating.
2. Choose the method: `annotate-image` for source-backed first passes,
   `repair-image` for one-issue repair turns, `diagnose-image` for visual QA,
   `image-generate` for new artwork, and `image-edit` for direct one-shot edits.
3. State the output geometry before generating. Use `--aspect-policy
match-input` for source-backed screenshots and cards, `portrait` or
   `landscape` for known placements, `square` for icons, `auto` when the model
   should choose, or exact `--size WIDTHxHEIGHT`.
4. State quality, format, detail, and background explicitly on every generating
   command. The `source-final` profile in `profiles --json` carries the
   recommended source-backed bundle; read it rather than a copy pasted here.
5. Attach the source images on every repair turn. `previous_response_id`
   preserves conversation state, but source images prevent visual drift.
6. Ask for short visible labels only. Put exact text in HTML, Typst, slides, or
   the host document.
7. Generate a first pass, inspect the PNG yourself, then run `diagnose-image`
   when a repair turn needs structured visual evidence.
8. Repair one concrete issue per turn. Use the diagnosis
   `next_repair_issue` as the `repair-image --issue` only after checking that it
   matches what you see.
9. Make a contact sheet for variants and reject outputs with cropping, warped
   source facts, unreadable marks, fake text, or style drift.
10. Integrate the selected raster into the final document and inspect the
    rendered page.

## Choose The Method

- Exact source state, object identity, UI state, card face, or screenshot
  content matters: use `annotate-image`, inspect the PNG, then use
  `repair-image` with `--previous-response-id` and the original image attached
  again.
- Exact text, rule terms, bilingual labels, code, tables, or captions matter:
  keep those words in Typst, HTML, slides, or the host document.
- The concept is abstract and does not need source-image fidelity: use
  deterministic vector drawing, Typst primitives, SVG/HTML, Mermaid-style
  diagrams, or another diagram tool.
- The result is a reusable icon, token, sticker, product widget, marker,
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
- Set the intended aspect ratio or `--aspect-policy` in the command and in the
  prompt. Do not recompose portrait/mobile UI into a landscape board unless the
  user asked for that.
- On repair turns, fix only the stated issue.
- For reusable components, generate on a simple opaque or green-screen
  background, then post-process transparency locally.

## Support Files

Use CLI help and `profiles --json` as the parameter contract. Keep each repair
turn visible when the user can inspect the image and choose the next issue.

Read prompt templates only when changing prompt text or debugging generated
prompt behavior:

- `assets/prompts/tutorial-overlay.txt`
- `assets/prompts/revise-image.txt`
- `assets/prompts/diagnose-image.txt`
- `assets/prompts/greenscreen-component.txt`

Read reference cases only when the user task matches the case:

- Use `references/source-backed-mobile-ui/` for mobile UI tutorial overlays that
  must preserve source UI state.
- Use `references/long-screenshot-guardrail/` for long screenshots where cropping
  or recomposition would lose source facts.
- Do not read reference cases for ordinary generation, editing, repair, QA, or
  variant comparison.

## Closeout Checks

After editing `scripts/image_workbench.py`:

```bash
uv run python -m py_compile "$SKILL_DIR/scripts/image_workbench.py"
uv run ruff check "$SKILL_DIR/scripts/image_workbench.py"
uv run ty check "$SKILL_DIR/scripts/image_workbench.py"
uv run --script "$SKILL_DIR/scripts/image_workbench.py" --help
```

Before finishing work that used real API keys:

```bash
# Run the repo's secret scanner first if one is configured.
rg -n --pcre2 \
  --glob '!**/image-generation-workbench/SKILL.md' \
  "(API_KEY|TOKEN|SECRET|BASE_URL)\\s*=|sk-[A-Za-z0-9_-]{20,}|Bearer\\s+[A-Za-z0-9._-]{20,}" \
  .
```
