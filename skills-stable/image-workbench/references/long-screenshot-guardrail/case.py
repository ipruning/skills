#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pillow>=12.2.0",
# ]
# ///
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CASE_DIR = Path(__file__).resolve().parent
SKILL_DIR = CASE_DIR.parents[1]
CLI = SKILL_DIR / "scripts/image_workbench.py"
OUT_DIR = Path("/tmp/image-workbench-cases/long-screenshot-guardrail")
SOURCE = OUT_DIR / "long-screenshot.png"
RESULT = OUT_DIR / "should-not-generate.png"


def draw_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (322, 2595), "#f8fafc")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    draw.rectangle((0, 0, 321, 72), fill="#111827")
    draw.text((18, 26), "Long page fixture", fill="#ffffff", font=font)
    y = 104
    for index in range(12):
        draw.rounded_rectangle((14, y, 308, y + 152), radius=10, fill="#ffffff", outline="#d9e2ef", width=2)
        draw.text((34, y + 26), f"Section {index + 1}", fill="#111827", font=font)
        draw.text((34, y + 70), "Too tall for direct match-input.", fill="#475569", font=font)
        y += 198
    image.save(path)


def command() -> list[str]:
    return [
        "uv",
        "run",
        "--script",
        str(CLI),
        "annotate-image",
        "--image",
        str(SOURCE),
        "--aspect-policy",
        "match-input",
        "--quality",
        "high",
        "--output-format",
        "png",
        "--detail",
        "high",
        "--background",
        "auto",
        "--out",
        str(RESULT),
    ]


def main() -> None:
    draw_fixture(SOURCE)
    completed = subprocess.run(command(), check=False, text=True, capture_output=True)
    print(f"source={SOURCE}")
    print(f"status={completed.returncode}")
    if completed.stdout:
        print("stdout:")
        print(completed.stdout.strip())
    if completed.stderr:
        print("stderr:")
        print(completed.stderr.strip())
    if completed.returncode == 0:
        raise SystemExit("Expected the guardrail command to fail before calling the API.")
    if "cannot preserve that extreme ratio" not in completed.stderr:
        raise SystemExit("Expected the error to explain the extreme ratio guardrail.")


if __name__ == "__main__":
    main()
