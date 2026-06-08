# API Selection

## Use Responses API by default

Prefer `client.responses.create(..., tools=[{"type": "image_generation"}])` for
production image workflows.

Use it when:

- a model should inspect one or more source images before generating;
- you need multi-turn repair with `previous_response_id`;
- the prompt includes both image references and non-trivial instructions;
- you want the controller model to decide how to use the image tool;
- you need streaming partial image frames from the image tool.

Default model roles in this skill:

- `--reasoning-model`: `gpt-5.5`
- `--image-model`: omitted by default

The reasoning model reads the prompt and references. The Responses API
`image_generation` tool selects its own GPT Image model by default. Pass
`--image-model` only as an explicit override when you have verified that the
target API or gateway supports it.

## Use Images API for direct calls

Use `client.images.generate(...)` or `client.images.edit(...)` for one-shot
generation or editing where conversation state is unnecessary.

Use it when:

- the prompt is simple;
- you do not need a repair thread;
- you want a small smoke test of image model parameters;
- an external script already manages iteration.

With the Image API, choose `gpt-image-2` directly unless a known deployment or
gateway requires another GPT Image model.

Some OpenAI-compatible gateways may proxy Responses API successfully while
blocking direct Images API routes because their cost-estimation policy does not
know the image model. If direct `image-generate` or `image-edit` fails at the
gateway layer, use `response-image` or `annotate-image` instead.

## Hybrid document workflow

For tutorial PDFs, strategy guides, slide decks, product docs, and manuals:

- Image model: integrated visual, mood, local highlights, short labels.
- Vector/HTML/Typst: exact text, captions, page layout, arrows that must remain
  editable, code/rules copy, data tables, legends.
- QA loop: generate PNG, inspect it, repair or reject, then render the final
  document page and inspect again.

## Choosing AI, vector, or diagram primitives

| Need | Best pipe |
|---|---|
| Source image facts must survive | `annotate-image` or `response-image` with the source attached |
| A previous output is close but has one visible mistake | `repair-image` with `previous_response_id` and the original source attached |
| Exact text, rule prose, bilingual labels, data, or captions | Host document layer: Typst, HTML, slides, or SVG text |
| Abstract process or relationship | Vector/SVG/Typst primitives or Mermaid-style diagrams |
| Visual polish from a rough layout | Attach the sketch as a reference image and ask the model to preserve geometry |
| Reusable token, icon, badge, marker, or widget | Image generation on opaque/green-screen background plus local QA/post-processing |

## Capability boundaries

- `gpt-image-2` does not support transparent backgrounds. Use opaque or
  green-screen output, then local chroma-key post-processing.
- Do not pass `input_fidelity` with `gpt-image-2`; image inputs are high fidelity
  by default for that model.
- Square outputs are good for cheap smoke tests. Wide source screenshots usually
  need a wide output such as `1536x1024` to avoid cropping important context.
- Exact long text belongs outside the image. Use the model for short marks and
  visual emphasis, not editable prose.

Sources to re-check when model/API support changes:

- OpenAI image generation guide:
  `https://developers.openai.com/api/docs/guides/image-generation`
- OpenAI Python SDK method signatures:
  inspect them from the project environment with `uv run python` or from the
  script's locked dependency environment; do not add `--with` to normal
  `uv run --script scripts/image_workbench.py ...` commands because the script
  header already declares runtime dependencies.
