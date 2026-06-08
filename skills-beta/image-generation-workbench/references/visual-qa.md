# Visual QA

## Inspect every output

Open the generated PNG before using it. Reject or repair if any of these appear:

- source facts changed;
- important regions are cropped;
- labels cover the thing they name;
- arrows point to the wrong target;
- fake text, fake logos, or invented UI appears;
- long text is misspelled or unreadable;
- style is inconsistent with the destination document;
- the image looks good alone but fails when placed on the final page.

## Repair loop

First convert visual inspection into one repair issue when the next action is
not obvious:

```bash
uv run --script scripts/image_workbench.py diagnose-image \
  --source path/to/source.png \
  --candidate path/to/output-v1.png \
  --criteria "The figure must preserve source positions and teach the main target." \
  --out path/to/output-v1.diagnosis.json \
  --json
```

Then repair one concrete issue per turn:

```bash
uv run --script scripts/image_workbench.py repair-image \
  --image path/to/source.png \
  --previous-response-id resp_... \
  --issue "Move the label above the highlighted region; do not change the highlighted region." \
  --out path/to/output-v2.png
```

Always attach the original image again on repair turns. Conversation state helps,
but the source image prevents drift.

## Contact sheets

Use contact sheets for selection, not memory:

```bash
uv run --script scripts/image_workbench.py contact-sheet \
  --image out/a.png \
  --image out/b.png \
  --image out/c.png \
  --out out/contact-sheet.png
```

## Document integration

After choosing the raster, render the destination document and inspect the page:

- Are labels still readable at final size?
- Does the crop retain enough context?
- Does the surrounding layout make the teaching point clear?
- Should exact labels move to Typst/HTML instead of staying burned into the PNG?
