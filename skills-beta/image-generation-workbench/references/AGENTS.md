# Image Workbench References

This directory contains runnable cases, not parameter documentation.

Each case directory contains:

- `AGENTS.md` explaining the scenario, the expected observation, and when to use
  the case.
- `case.py` when the fixture can be generated deterministically; otherwise, a
  small checked-in PNG fixture.

Keep API parameter truth in `../scripts/image_workbench.py` help and
`profiles --json`. Do not recreate flat reference docs here.
