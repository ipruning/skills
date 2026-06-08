# Prompt Recipes

## Tutorial overlay

Use when the source image matters and the output should teach one point.

Shape:

1. Name the source facts to preserve.
2. State the teaching point.
3. List exactly 1-3 visual marks.
4. Ban fake text and unrelated additions.
5. Say source preservation wins over beauty.

See `assets/prompts/tutorial-overlay.txt`.

## Multi-turn repair

Use when a previous output is close but has a local mistake.

Shape:

1. Preserve the previous style and source facts.
2. Keep only the existing labels unless the issue explicitly changes them.
3. Fix only the issue.
4. Re-attach the original image in the command.

See `assets/prompts/revise-image.txt`.

## Visual diagnosis

Use when an Agent needs to inspect a generated image before deciding whether to
repair it.

Shape:

1. Provide the source image, candidate image, and one sentence of acceptance
   criteria.
2. Ask for JSON with verdict, issues, keep_parts, and one next_repair_issue.
3. Feed only one concrete issue into `repair-image`.
4. Re-check the repaired output visually instead of assuming the diagnosis was
   complete.

See `assets/prompts/diagnose-image.txt`.

## Green-screen component

Use when you want a reusable object, marker, badge, icon, token, or widget.

Shape:

1. Request a single centered object on solid chroma green.
2. Avoid shadows touching the edge unless desired.
3. Keep the silhouette clean.
4. Run `chroma-alpha` locally if transparency is needed.

See `assets/prompts/greenscreen-component.txt`.

## Sketch-to-render

Use when exact geometry matters more than source photo fidelity.

Recommended flow:

1. Create a simple vector or screenshot sketch.
2. Attach it as `--image`.
3. Ask Image 2 to preserve geometry and improve surface style.
4. Keep labels short or external.

This is useful for maps, callout plates, app widgets, tutorial panels, and
before/after figures.
