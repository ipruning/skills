#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pillow>=12.2.0",
# ]
# ///
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CASE_DIR = Path(__file__).resolve().parent
SKILL_DIR = CASE_DIR.parents[1]
CLI = SKILL_DIR / "scripts/image_workbench.py"
OUT_DIR = Path("/tmp/image-workbench-cases/source-backed-mobile-ui")
SOURCE = OUT_DIR / "source-mobile-ui.png"
RESULT = OUT_DIR / "tutorial-figure.png"


def draw_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (768, 1280), "#f4f6fb")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    draw.rounded_rectangle((36, 32, 732, 1248), radius=36, fill="#ffffff", outline="#cbd5e1", width=3)
    draw.rectangle((36, 32, 732, 126), fill="#111827")
    draw.text((72, 68), "Deck Review", fill="#ffffff", font=font)
    draw.text((604, 68), "9:41", fill="#ffffff", font=font)

    draw.rounded_rectangle((76, 172, 692, 338), radius=24, fill="#fff7db", outline="#eab308", width=2)
    draw.text((108, 204), "Primary candidate", fill="#111827", font=font)
    draw.text((108, 246), "Keep this source layout and annotate lightly.", fill="#374151", font=font)

    y = 394
    for index, color in enumerate(("#dc2626", "#2563eb", "#16a34a", "#9333ea"), start=1):
        draw.rounded_rectangle((76, y, 692, y + 150), radius=18, fill="#f8fafc", outline="#dbe3ef", width=2)
        draw.rounded_rectangle((106, y + 22, 206, y + 128), radius=12, fill=color)
        draw.text((236, y + 34), f"Item {index}", fill="#111827", font=font)
        draw.text((236, y + 78), "Stable source-backed row", fill="#475569", font=font)
        y += 178

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
        "--json",
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-cli", action="store_true", help="Call the real API command after creating the fixture.")
    args = parser.parse_args()

    draw_fixture(SOURCE)
    print(f"source={SOURCE}")
    print("expected_aspect_policy=match-input")
    print("expected_resolved_size=1024x1536")
    print("command=" + " ".join(command()))

    if not args.run_cli:
        return
    if "OPENAI_API_KEY" not in os.environ and "PYDANTIC_AI_GATEWAY_API_KEY" not in os.environ:
        raise SystemExit("Set OPENAI_API_KEY or PYDANTIC_AI_GATEWAY_API_KEY before using --run-cli.")
    subprocess.run(command(), check=True)


if __name__ == "__main__":
    main()
