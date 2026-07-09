#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "openai>=2.41.1",
#   "pillow>=12.2.0",
#   "pydantic-settings>=2.14.1",
#   "pydantic>=2.13.4",
#   "typer>=0.26.7",
# ]
# ///
from __future__ import annotations

import base64
import json
import math
import mimetypes
import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal, NoReturn, cast

import typer
from openai import OpenAI, OpenAIError, omit
from openai.types.responses import (
    ResponseInputFileParam,
    ResponseInputImageParam,
    ResponseInputTextParam,
    ToolChoiceTypesParam,
)
from openai.types.responses.response_input_param import Message
from openai.types.responses.tool_param import (
    ImageGeneration,
    ImageGenerationInputImageMask,
)
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict  # ty: ignore[unresolved-import]

SKILL_DIR = Path(__file__).resolve().parents[1]
PROMPT_DIR = SKILL_DIR / "assets/prompts"
DEFAULT_TUTORIAL_PROMPT = PROMPT_DIR / "tutorial-overlay.txt"
DEFAULT_REPAIR_PROMPT = PROMPT_DIR / "revise-image.txt"
DEFAULT_DIAGNOSE_PROMPT = PROMPT_DIR / "diagnose-image.txt"
DEFAULT_CONTROLLER_MODEL = "gpt-5.5"
DEFAULT_IMAGE_MODEL = "gpt-image-2"
API_KEY_ENV = "OPENAI_API_KEY"
API_BASE_URL_ENV = "OPENAI_BASE_URL"
GATEWAY_API_KEY_ENV = "PYDANTIC_AI_GATEWAY_API_KEY"
GATEWAY_BASE_URL_ENV = "PYDANTIC_AI_GATEWAY_BASE_URL"

SIZE_PATTERN = re.compile(r"^(?P<width>[1-9][0-9]*)x(?P<height>[1-9][0-9]*)$")
ALLOWED_BACKGROUNDS = {"auto", "opaque"}

app = typer.Typer(
    help=(
        "General image generation workbench. Relative --image/--out paths resolve "
        "against the nearest ancestor directory containing .git or pyproject.toml, "
        "falling back to the current directory."
    ),
    no_args_is_help=True,
)


class Quality(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    AUTO = "auto"


class DirectQuality(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    AUTO = "auto"


class OutputFormat(StrEnum):
    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"


class ResponseAction(StrEnum):
    GENERATE = "generate"
    EDIT = "edit"
    AUTO = "auto"


class AspectPolicy(StrEnum):
    AUTO = "auto"
    MATCH_INPUT = "match-input"
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    SQUARE = "square"
    EXPLICIT = "explicit"


class ImageDetail(StrEnum):
    LOW = "low"
    HIGH = "high"
    AUTO = "auto"
    ORIGINAL = "original"


class Moderation(StrEnum):
    AUTO = "auto"
    LOW = "low"


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    openai_api_key: str | None = Field(default=None, validation_alias=API_KEY_ENV)
    openai_base_url: str | None = Field(default=None, validation_alias=API_BASE_URL_ENV)
    gateway_api_key: str | None = Field(default=None, validation_alias=GATEWAY_API_KEY_ENV)
    gateway_base_url: str | None = Field(default=None, validation_alias=GATEWAY_BASE_URL_ENV)


class ClientConfig(BaseModel):
    api_key: str = Field(exclude=True)
    base_url: str | None = None
    api_key_env: str
    base_url_env: str


class ClientMetadata(BaseModel):
    api_key_env: str
    base_url_env: str
    base_url_configured: bool


class WorkbenchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponseImageMetadata(WorkbenchModel):
    kind: Literal["response-image"]
    output_path: str
    metadata_path: str
    response_path: str
    response_id: object
    reasoning_model: str
    image_model: str
    aspect_policy: str | None
    size: str
    quality: str
    action: str
    output_format: str
    background: str | None
    mask: str | None
    moderation: str | None
    output_compression: int | None
    partial_images: int | None
    partial_outputs: list[str]
    previous_response_id: str | None
    prompt: str
    images: list[str]
    client: ClientMetadata


class DirectImageMetadata(WorkbenchModel):
    kind: Literal["image-generate", "image-edit"]
    output_path: str
    metadata_path: str
    response_path: str
    model: str
    aspect_policy: str | None
    size: str
    quality: str
    output_format: str
    background: str | None
    output_compression: int | None
    n: int
    prompt: str
    client: ClientMetadata
    moderation: str | None = None
    images: list[str] | None = None
    mask: str | None = None
    output_paths: list[str] | None = None


class DiagnoseImageMetadata(WorkbenchModel):
    kind: Literal["diagnose-image"]
    output_path: str
    response_path: str
    response_id: object
    reasoning_model: str
    sources: list[str]
    candidates: list[str]
    criteria: str
    diagnosis: object
    client: ClientMetadata


class ContactSheetMetadata(WorkbenchModel):
    kind: Literal["contact-sheet"]
    output_path: str
    images: list[str]
    columns: int
    thumb_width: int


class ChromaAlphaMetadata(WorkbenchModel):
    kind: Literal["chroma-alpha"]
    output_path: str
    input_path: str
    color: str
    tolerance: int
    feather: int


class ProfileCommand(WorkbenchModel):
    command: str
    arguments: dict[str, str | int]


class ParameterProfile(WorkbenchModel):
    name: str
    use_when: str
    commands: list[ProfileCommand]
    notes: list[str]


def find_workspace_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists() or (candidate / "pyproject.toml").exists():
            return candidate
    return Path.cwd()


ROOT = find_workspace_root(Path.cwd())


@lru_cache
def settings() -> EnvSettings:
    return EnvSettings()


def fail(message: object) -> NoReturn:
    typer.echo(str(message), err=True)
    raise typer.Exit(1) from None


def work_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT / path


def api_config() -> ClientConfig:
    env = settings()
    if env.openai_api_key:
        return ClientConfig(
            api_key=env.openai_api_key,
            base_url=env.openai_base_url,
            api_key_env=API_KEY_ENV,
            base_url_env=API_BASE_URL_ENV,
        )
    if env.gateway_api_key:
        return ClientConfig(
            api_key=env.gateway_api_key,
            base_url=env.gateway_base_url,
            api_key_env=GATEWAY_API_KEY_ENV,
            base_url_env=GATEWAY_BASE_URL_ENV,
        )
    fail(
        f"{API_KEY_ENV} or {GATEWAY_API_KEY_ENV} is not set. Pass credentials through the command environment; do not write them into prompts or repos."
    )


def client_metadata() -> ClientMetadata:
    config = api_config()
    return ClientMetadata(
        api_key_env=config.api_key_env,
        base_url_env=config.base_url_env,
        base_url_configured=bool(config.base_url),
    )


def make_client(timeout: float) -> OpenAI:
    config = api_config()
    if config.base_url:
        return OpenAI(api_key=config.api_key, base_url=config.base_url, timeout=timeout)
    return OpenAI(api_key=config.api_key, timeout=timeout)


def require_key() -> None:
    api_config()


def read_prompt(value: str | Path) -> str:
    path = Path(value)
    if not path.is_absolute():
        skill_candidate = SKILL_DIR / path
        work_candidate = ROOT / path
        path = skill_candidate if skill_candidate.exists() else work_candidate
    if path.exists():
        return path.read_text(encoding="utf-8")
    if isinstance(value, Path):
        # Built-in prompt templates are passed as Path; a missing one is a
        # broken install, not literal prompt text.
        fail(f"built-in prompt template is missing: {value}")
    text = str(value)
    if text.endswith((".txt", ".md")):
        # A mistyped template path must not become a billed literal prompt.
        fail(f"--prompt looks like a prompt file path but no such file exists: {text}")
    return text


def image_data_url(path: str) -> str:
    resolved = work_path(path)
    mime = mimetypes.guess_type(resolved.name)[0] or "image/png"
    data = base64.b64encode(resolved.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def model_dict(value: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return value.model_dump(mode="json")


def json_data(data: object) -> object:
    if isinstance(data, BaseModel):
        return data.model_dump(mode="json")
    return data


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_data(data), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def emit_result(json_output: bool, data: BaseModel) -> None:
    payload = data.model_dump(mode="json")
    if json_output:
        typer.echo(data.model_dump_json())
        return

    output_path = payload.get("output_path")
    if output_path:
        typer.echo(str(output_path))
    response_id = payload.get("response_id")
    if response_id:
        typer.echo(str(response_id))


PARAMETER_PROFILES = [
    ParameterProfile(
        name="source-final",
        use_when="Final source-backed screenshot, UI, card, logo, or object-preserving edit.",
        commands=[
            ProfileCommand(
                command="annotate-image",
                arguments={
                    "aspect-policy": "match-input",
                    "quality": "high",
                    "output-format": "png",
                    "detail": "high",
                    "background": "auto",
                },
            ),
            ProfileCommand(
                command="repair-image",
                arguments={
                    "aspect-policy": "match-input",
                    "quality": "high",
                    "output-format": "png",
                    "detail": "high",
                    "background": "auto",
                },
            ),
            ProfileCommand(
                command="response-image",
                arguments={
                    "action": "edit",
                    "aspect-policy": "match-input",
                    "quality": "high",
                    "output-format": "png",
                    "detail": "high",
                    "background": "auto",
                },
            ),
            ProfileCommand(
                command="image-edit",
                arguments={
                    "aspect-policy": "match-input",
                    "quality": "high",
                    "output-format": "png",
                    "background": "auto",
                },
            ),
        ],
        notes=[
            "Use exact --size instead of --aspect-policy only when the destination canvas is fixed.",
            "Long screenshots beyond 3:1 must be cropped, sliced, or composed outside the raster image.",
        ],
    ),
    ParameterProfile(
        name="source-draft",
        use_when="Cheap first pass for source-backed work where preservation still matters.",
        commands=[
            ProfileCommand(
                command="annotate-image",
                arguments={
                    "aspect-policy": "match-input",
                    "quality": "low",
                    "output-format": "png",
                    "detail": "high",
                    "background": "auto",
                },
            ),
            ProfileCommand(
                command="response-image",
                arguments={
                    "action": "edit",
                    "aspect-policy": "match-input",
                    "quality": "low",
                    "output-format": "png",
                    "detail": "high",
                    "background": "auto",
                },
            ),
            ProfileCommand(
                command="image-edit",
                arguments={
                    "aspect-policy": "match-input",
                    "quality": "low",
                    "output-format": "png",
                    "background": "auto",
                },
            ),
        ],
        notes=["Upgrade to source-final before publishing or integrating into a document."],
    ),
    ParameterProfile(
        name="new-art-final",
        use_when="New generated artwork without source-image preservation requirements.",
        commands=[
            ProfileCommand(
                command="image-generate",
                arguments={
                    "aspect-policy": "auto",
                    "quality": "high",
                    "output-format": "png",
                    "background": "auto",
                },
            ),
            ProfileCommand(
                command="response-image",
                arguments={
                    "action": "generate",
                    "aspect-policy": "auto",
                    "quality": "high",
                    "output-format": "png",
                    "background": "auto",
                },
            ),
        ],
        notes=["Use portrait, landscape, square, or exact --size when the destination frame is known."],
    ),
    ParameterProfile(
        name="web-compressed",
        use_when="Web asset where file size matters more than lossless preservation.",
        commands=[
            ProfileCommand(
                command="image-generate",
                arguments={
                    "aspect-policy": "auto",
                    "quality": "medium",
                    "output-format": "webp",
                    "output-compression": 85,
                    "background": "auto",
                },
            ),
            ProfileCommand(
                command="response-image",
                arguments={
                    "action": "generate",
                    "aspect-policy": "auto",
                    "quality": "medium",
                    "output-format": "webp",
                    "output-compression": 85,
                    "background": "auto",
                },
            ),
        ],
        notes=["For source-backed edits, also add --detail high and choose match-input."],
    ),
]


@app.command("profiles", help="Print recommended explicit parameter bundles")
def profiles(
    json_output: Annotated[bool, typer.Option("--json", help="Print profiles as JSON")] = False,
) -> None:
    if json_output:
        typer.echo(json.dumps([profile.model_dump(mode="json") for profile in PARAMETER_PROFILES], indent=2))
        return
    for profile in PARAMETER_PROFILES:
        typer.echo(profile.name)
        typer.echo(f"  use: {profile.use_when}")
        for command in profile.commands:
            args = " ".join(f"--{key} {value}" for key, value in command.arguments.items())
            typer.echo(f"  {command.command}: {args}")
        for note in profile.notes:
            typer.echo(f"  note: {note}")
        typer.echo("")


def write_b64_image(data: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(data))


def partial_output_path(output_path: Path, index: int) -> Path:
    return output_path.with_name(f"{output_path.stem}.partial-{index}{output_path.suffix}")


def extract_response_images(data: dict[str, Any]) -> list[str]:
    images: list[str] = []
    for item in data.get("output", []):
        if item.get("type") != "image_generation_call":
            continue
        result = item.get("result")
        if isinstance(result, str):
            images.append(result)
        for partial in item.get("partial_images") or []:
            partial_result = partial.get("result")
            if isinstance(partial_result, str):
                images.append(partial_result)
    return images


def write_images_api_outputs(data: dict[str, Any], output_path: Path) -> list[str]:
    """Write every returned image; data[0] keeps output_path, the rest get -2, -3... suffixes."""
    items = data.get("data")
    if not isinstance(items, list) or not items:
        fail("Images API response did not include data[0].")
    written: list[str] = []
    for index, item in enumerate(items):
        b64_json = item.get("b64_json") if isinstance(item, dict) else None
        if not isinstance(b64_json, str):
            fail(f"Images API response data[{index}] did not include b64_json.")
        target = (
            output_path if index == 0 else output_path.with_name(f"{output_path.stem}-{index + 1}{output_path.suffix}")
        )
        write_b64_image(b64_json, target)
        written.append(str(target))
    return written


def extract_response_text(data: dict[str, Any]) -> str:
    texts: list[str] = []
    for item in data.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                texts.append(content["text"])
    return "\n".join(texts).strip()


def parse_json_object(value: str) -> object:
    stripped = value.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def enum_value(value: StrEnum | None) -> str | None:
    return value.value if value is not None else None


def require_choice[T](value: T | None, option: str, meaning: str, recommendation: str) -> T:
    if value is not None:
        return value
    fail(f"{option} is required. {meaning} Recommendation: {recommendation}")


def parse_size(value: str) -> tuple[int, int] | None:
    match = SIZE_PATTERN.match(value)
    if not match:
        return None
    return int(match["width"]), int(match["height"])


def validate_size_value(value: str) -> None:
    if value == "auto":
        return
    parsed = parse_size(value)
    if parsed is None:
        fail(f'Invalid --size "{value}". Use WIDTHxHEIGHT, for example 1024x1536, 1536x1024, 1024x1024, or auto.')
    width, height = parsed
    pixels = width * height
    ratio = max(width, height) / min(width, height)
    if width % 16 != 0 or height % 16 != 0:
        fail(f'Invalid --size "{value}". gpt-image-2 custom dimensions must be multiples of 16 pixels on both sides.')
    if max(width, height) > 3840:
        fail(f'Invalid --size "{value}". gpt-image-2 allows a maximum side length of 3840 pixels.')
    if ratio > 3:
        fail(f'Invalid --size "{value}". gpt-image-2 requires the long side to be no more than 3x the short side.')
    if not 655_360 <= pixels <= 8_294_400:
        fail(f'Invalid --size "{value}". gpt-image-2 requires total pixels between 655,360 and 8,294,400.')


def image_dimensions(path: str) -> tuple[int, int]:
    resolved = work_path(path)
    try:
        with Image.open(resolved) as image:
            return image.size
    except OSError as exc:
        fail(f"Could not read image dimensions for {resolved}: {exc}")


class ImageInfo(BaseModel):
    path: str
    width: int
    height: int
    format: str | None
    mode: str
    bytes_size: int
    has_alpha: bool


def image_info(path: str) -> ImageInfo:
    resolved = work_path(path)
    try:
        with Image.open(resolved) as image:
            return ImageInfo(
                path=str(resolved),
                width=image.width,
                height=image.height,
                format=image.format,
                mode=image.mode,
                bytes_size=resolved.stat().st_size,
                has_alpha=image.mode in {"RGBA", "LA"} or "transparency" in image.info,
            )
    except OSError as exc:
        fail(f"Could not read image metadata for {resolved}: {exc}")


MATCH_INPUT_TARGET_PIXELS = 1_572_864  # same canvas budget as the fixed 1536x1024 preset


def snap_match_input(width: int, height: int) -> str:
    # match-input must preserve the input ratio instead of requantizing it into
    # landscape/portrait/square buckets; gpt-image-2 accepts custom sizes in 16px steps.
    ratio = width / height
    raw_height = math.sqrt(MATCH_INPUT_TARGET_PIXELS / ratio)
    out_width = max(16, round(raw_height * ratio / 16) * 16)
    out_height = max(16, round(raw_height / 16) * 16)
    # 16px rounding can nudge the ratio past the 3:1 API limit at the extremes.
    while out_width > out_height * 3:
        out_width -= 16
    while out_height > out_width * 3:
        out_height -= 16
    return f"{out_width}x{out_height}"


def resolve_size(
    *,
    size: str | None,
    aspect_policy: AspectPolicy | None,
    reference_images: list[str] | None,
) -> tuple[str, str]:
    if size is not None:
        validate_size_value(size)
        if aspect_policy is None or aspect_policy == AspectPolicy.EXPLICIT:
            return size, AspectPolicy.EXPLICIT.value
        fail(
            "--size and --aspect-policy conflict. Remove --aspect-policy, or use --aspect-policy explicit with the exact --size."
        )

    policy = require_choice(
        aspect_policy,
        "--aspect-policy",
        "It decides the output canvas ratio before generation, so the model does not silently recompose the image.",
        "source-backed mobile UI: match-input; new illustrations: auto; known target: portrait, landscape, or square.",
    )
    if policy == AspectPolicy.AUTO:
        return "auto", policy.value
    if policy == AspectPolicy.LANDSCAPE:
        return "1536x1024", policy.value
    if policy == AspectPolicy.PORTRAIT:
        return "1024x1536", policy.value
    if policy == AspectPolicy.SQUARE:
        return "1024x1024", policy.value
    if policy == AspectPolicy.EXPLICIT:
        fail("--aspect-policy explicit requires --size WIDTHxHEIGHT.")

    if not reference_images:
        fail("--aspect-policy match-input requires at least one --image reference.")

    width, height = image_dimensions(reference_images[0])
    ratio = width / height
    if ratio > 3 or ratio < 1 / 3:
        fail(
            f"The first input image is {width}x{height} ({ratio:.2f}:1). gpt-image-2 cannot preserve that extreme ratio directly; crop, slice, or compose the long page outside the raster image."
        )
    return snap_match_input(width, height), policy.value


def resolve_detail(detail: ImageDetail | None, reference_images: list[str] | None) -> str:
    if not reference_images:
        return (detail or ImageDetail.AUTO).value
    return require_choice(
        detail,
        "--detail",
        "It controls how much visual information the reasoning model reads from each reference image.",
        "high for source-backed editing or QA; auto for loose style references; low only for cheap smoke tests.",
    ).value


def validate_background(background: str) -> None:
    if background == "transparent":
        fail(
            "--background transparent is not supported with gpt-image-2. Use --background auto or opaque; for transparent assets generate a chroma-green component and run chroma-alpha."
        )
    if background not in ALLOWED_BACKGROUNDS:
        fail(f'Invalid --background "{background}". Use auto or opaque.')


def validate_latest_image_options(*, background: str, output_format: str, output_compression: int | None) -> None:
    validate_background(background)
    if output_compression is not None:
        if not 0 <= output_compression <= 100:
            fail("--output-compression must be between 0 and 100.")
        if output_format == OutputFormat.PNG.value:
            fail("--output-compression only applies to jpeg or webp. Remove it for png outputs.")
    elif output_format in {OutputFormat.JPEG.value, OutputFormat.WEBP.value}:
        fail(
            "--output-compression is required with jpeg or webp. It controls the size/quality tradeoff; use 95 for review drafts, 85 for web assets, or 100 for maximum quality."
        )


def validate_mask(mask: str | None, reference_images: list[str] | None) -> None:
    if mask is None:
        return
    if not reference_images:
        fail("--mask requires at least one --image input because a mask edits an existing image.")
    mask_info = image_info(mask)
    source_info = image_info(reference_images[0])
    if mask_info.bytes_size > 50 * 1024 * 1024 or source_info.bytes_size > 50 * 1024 * 1024:
        fail("--mask and the first --image must each be smaller than 50MB for image edit requests.")
    if (mask_info.width, mask_info.height) != (source_info.width, source_info.height):
        fail(
            f"--mask dimensions must match the first --image. Mask is {mask_info.width}x{mask_info.height}, source is {source_info.width}x{source_info.height}."
        )
    if mask_info.format != source_info.format:
        fail(
            f"--mask format must match the first --image. Mask is {mask_info.format or 'unknown'}, source is {source_info.format or 'unknown'}."
        )
    if not mask_info.has_alpha:
        fail("--mask must contain an alpha channel so the API can tell which pixels to edit.")


def call_response_image(
    *,
    prompt: str,
    reference_images: list[str] | None,
    out: str,
    previous_response_id: str | None,
    aspect_policy: str | None,
    size: str,
    quality: str,
    output_format: str,
    action: str,
    detail: str,
    background: str | None,
    mask: str | None,
    moderation: str | None,
    output_compression: int | None,
    partial_images: int | None,
    timeout: float,
    json_output: bool,
) -> None:
    if mask and action != ResponseAction.EDIT.value:
        fail("--mask requires --action edit because masks define which pixels of an input image to modify.")
    if action == ResponseAction.EDIT.value and not reference_images and not previous_response_id:
        fail("--action edit requires at least one --image reference or a --previous-response-id with image context.")
    validate_latest_image_options(
        background=background or "auto",
        output_format=output_format,
        output_compression=output_compression,
    )
    validate_mask(mask, reference_images)
    if partial_images is not None and not 0 <= partial_images <= 3:
        fail("partial_images must be between 0 and 3.")

    require_key()

    text_item: ResponseInputTextParam = {"type": "input_text", "text": prompt}
    content: list[ResponseInputTextParam | ResponseInputImageParam | ResponseInputFileParam] = [text_item]
    for image in reference_images or []:
        image_item: ResponseInputImageParam = {
            "type": "input_image",
            "image_url": image_data_url(image),
            "detail": cast(Literal["low", "high", "auto", "original"], detail),
        }
        content.append(image_item)

    tool: ImageGeneration = {
        "type": "image_generation",
        "size": cast(Any, size),
        "quality": cast(Literal["low", "medium", "high", "auto"], quality),
        "output_format": cast(Literal["png", "jpeg", "webp"], output_format),
        "action": cast(Literal["generate", "edit", "auto"], action),
    }
    tool["model"] = DEFAULT_IMAGE_MODEL
    if background:
        tool["background"] = cast(Literal["opaque", "auto"], background)
    if mask:
        input_image_mask: ImageGenerationInputImageMask = {"image_url": image_data_url(mask)}
        tool["input_image_mask"] = input_image_mask
    if moderation:
        tool["moderation"] = cast(Literal["auto", "low"], moderation)
    if output_compression is not None:
        tool["output_compression"] = output_compression
    if partial_images is not None:
        tool["partial_images"] = partial_images

    client = make_client(timeout)
    output_path = work_path(out)
    partial_paths: list[str] = []
    message: Message = {"role": "user", "content": content}
    tool_choice: ToolChoiceTypesParam = {"type": "image_generation"}

    if partial_images is None:
        response = client.responses.create(
            model=DEFAULT_CONTROLLER_MODEL,
            input=[message],
            previous_response_id=previous_response_id,
            tools=[tool],
            tool_choice=tool_choice,
            max_tool_calls=1,
            store=True,
        )
        data = model_dict(response)
    else:
        data: dict[str, Any] | None = None
        stream = client.responses.create(
            model=DEFAULT_CONTROLLER_MODEL,
            input=[message],
            previous_response_id=previous_response_id,
            tools=[tool],
            tool_choice=tool_choice,
            max_tool_calls=1,
            store=True,
            stream=True,
        )
        for event in stream:
            event_data = model_dict(event)
            event_type = event_data.get("type", "")
            if event_type == "response.image_generation_call.partial_image":
                index = int(event_data["partial_image_index"])
                partial_path = partial_output_path(output_path, index)
                write_b64_image(str(event_data["partial_image_b64"]), partial_path)
                partial_paths.append(str(partial_path))
            elif event_type == "response.completed":
                response_data = event_data.get("response")
                if not isinstance(response_data, dict):
                    fail("response.completed event did not include response.")
                data = response_data
            elif event_type == "error":
                fail(event_data)

        if data is None:
            fail("Streaming response did not include response.completed.")

    if not isinstance(data, dict):
        fail("Responses API result is not an object.")

    response_path = output_path.with_suffix(output_path.suffix + ".response.json")
    metadata_path = output_path.with_suffix(output_path.suffix + ".json")
    write_json(response_path, data)

    generated_images = extract_response_images(data)
    if generated_images:
        write_b64_image(generated_images[-1], output_path)
    elif partial_paths:
        output_path.write_bytes(Path(partial_paths[-1]).read_bytes())
    else:
        fail(f"No image_generation_call result found. Full response written next to {output_path}.")

    metadata = ResponseImageMetadata(
        kind="response-image",
        output_path=str(output_path),
        metadata_path=str(metadata_path),
        response_path=str(response_path),
        response_id=data.get("id"),
        reasoning_model=DEFAULT_CONTROLLER_MODEL,
        image_model=DEFAULT_IMAGE_MODEL,
        aspect_policy=aspect_policy,
        size=size,
        quality=quality,
        action=action,
        output_format=output_format,
        background=background,
        mask=mask,
        moderation=moderation,
        output_compression=output_compression,
        partial_images=partial_images,
        partial_outputs=partial_paths,
        previous_response_id=previous_response_id,
        prompt=prompt,
        images=reference_images or [],
        client=client_metadata(),
    )
    write_json(metadata_path, metadata)
    emit_result(json_output, metadata)


@app.command("response-image", help="Generate or edit via Responses API image_generation")
def response_image(
    prompt: Annotated[str, typer.Option("--prompt", help="Prompt text or prompt file")],
    out: Annotated[str, typer.Option("--out", help="Output image path")],
    image: Annotated[
        list[str] | None, typer.Option("--image", help="Reference image path; pass once per image")
    ] = None,
    previous_response_id: Annotated[
        str | None,
        typer.Option("--previous-response-id", help="Continue a prior Responses API turn from its response_id"),
    ] = None,
    aspect_policy: Annotated[
        AspectPolicy | None,
        typer.Option(
            "--aspect-policy",
            help="Required unless --size is passed: auto, match-input, landscape, portrait, square, or explicit",
        ),
    ] = None,
    size: Annotated[
        str | None, typer.Option("--size", help="Exact output size, e.g. 1024x1536, 1536x1024, or auto")
    ] = None,
    quality: Annotated[
        Quality | None,
        typer.Option("--quality", help="Required: low for drafts, high for final assets, auto to delegate"),
    ] = None,
    output_format: Annotated[
        OutputFormat | None,
        typer.Option("--output-format", help="Required: png for lossless, jpeg for speed, webp for compression"),
    ] = None,
    action: Annotated[
        ResponseAction | None,
        typer.Option(
            "--action", help="Required: edit source pixels, generate new pixels, or auto when deliberately delegating"
        ),
    ] = None,
    detail: Annotated[
        ImageDetail | None,
        typer.Option("--detail", help="Required for reference images; recommended: high"),
    ] = None,
    background: Annotated[
        str | None,
        typer.Option("--background", help="Required: auto or opaque. Transparent is rejected for gpt-image-2."),
    ] = None,
    mask: Annotated[str | None, typer.Option("--mask", help="Image mask for edit operations")] = None,
    moderation: Annotated[
        Moderation | None, typer.Option("--moderation", help="Moderation strictness passed to the API")
    ] = None,
    output_compression: Annotated[
        int | None,
        typer.Option("--output-compression", min=0, max=100, help="Required with jpeg or webp; rejected with png"),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print result metadata as JSON")] = False,
    partial_images: Annotated[
        int | None,
        typer.Option("--partial-images", min=0, max=3, help="Enable streaming and save partial image frames"),
    ] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="API request timeout in seconds")] = 1200,
) -> None:
    resolved_size, resolved_aspect_policy = resolve_size(size=size, aspect_policy=aspect_policy, reference_images=image)
    resolved_quality = require_choice(
        quality,
        "--quality",
        "It controls cost, latency, and final visual polish.",
        "low for first drafts, high for final source-backed assets, auto only when you truly want the API to choose.",
    )
    resolved_format = require_choice(
        output_format,
        "--output-format",
        "It decides the artifact format and whether compression is meaningful.",
        "png for source-backed UI/card work; jpeg for quick throwaway drafts; webp for compressed web assets.",
    )
    resolved_action = require_choice(
        action,
        "--action",
        "It tells the image tool whether references are edit targets or inspiration.",
        "edit when preserving a screenshot/card/UI; generate for new artwork; auto only when the distinction is intentionally delegated.",
    )
    resolved_background = require_choice(
        background,
        "--background",
        "It controls how the image model fills transparent or unspecified canvas areas.",
        "auto for most work; opaque for predictable post-processing.",
    )
    resolved_detail = resolve_detail(detail, image)
    call_response_image(
        prompt=read_prompt(prompt),
        reference_images=image,
        out=out,
        previous_response_id=previous_response_id,
        aspect_policy=resolved_aspect_policy,
        size=resolved_size,
        quality=resolved_quality.value,
        output_format=resolved_format.value,
        action=resolved_action.value,
        detail=resolved_detail,
        background=cast(Literal["opaque", "auto"], resolved_background),
        mask=mask,
        moderation=enum_value(moderation),
        output_compression=output_compression,
        partial_images=partial_images,
        timeout=timeout,
        json_output=json_output,
    )


@app.command("annotate-image", help="Recommended first pass for source-backed tutorial overlays")
def annotate_image(
    image: Annotated[
        list[str], typer.Option("--image", help="Original source image path; pass multiple times if needed")
    ],
    out: Annotated[str, typer.Option("--out")],
    prompt: Annotated[str | None, typer.Option("--prompt", help="Override the default tutorial prompt")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print result metadata as JSON")] = False,
    aspect_policy: Annotated[
        AspectPolicy | None,
        typer.Option("--aspect-policy", help="Required unless --size is passed; recommended: match-input"),
    ] = None,
    size: Annotated[str | None, typer.Option("--size", help="Exact output size, e.g. 1024x1536 or auto")] = None,
    quality: Annotated[
        Quality | None,
        typer.Option("--quality", help="Required: low for drafts, high for final tutorial figures"),
    ] = None,
    output_format: Annotated[
        OutputFormat | None, typer.Option("--output-format", help="Required; recommended: png for source-backed work")
    ] = None,
    detail: Annotated[
        ImageDetail | None, typer.Option("--detail", help="Required for reference images; recommended: high")
    ] = None,
    background: Annotated[
        str | None, typer.Option("--background", help="Required: auto or opaque. Transparent is rejected.")
    ] = None,
    output_compression: Annotated[
        int | None,
        typer.Option("--output-compression", min=0, max=100, help="Required with jpeg or webp; rejected with png"),
    ] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="API request timeout in seconds")] = 1200,
) -> None:
    resolved_size, resolved_aspect_policy = resolve_size(size=size, aspect_policy=aspect_policy, reference_images=image)
    resolved_quality = require_choice(
        quality,
        "--quality",
        "It controls cost, latency, and final polish.",
        "low for exploration, high for final source-backed tutorial figures.",
    )
    resolved_format = require_choice(
        output_format,
        "--output-format",
        "It decides the artifact format.",
        "png for UI/card screenshots because it preserves sharp edges and text best.",
    )
    resolved_background = require_choice(
        background,
        "--background",
        "It controls how unspecified canvas areas are filled.",
        "auto for most source-backed edits; opaque if the result will be post-processed.",
    )
    resolved_detail = resolve_detail(detail, image)
    call_response_image(
        prompt=read_prompt(prompt or DEFAULT_TUTORIAL_PROMPT),
        reference_images=image,
        out=out,
        previous_response_id=None,
        aspect_policy=resolved_aspect_policy,
        size=resolved_size,
        quality=resolved_quality.value,
        output_format=resolved_format.value,
        action="edit",
        detail=resolved_detail,
        background=cast(Literal["opaque", "auto"], resolved_background),
        mask=None,
        moderation=None,
        output_compression=output_compression,
        partial_images=None,
        timeout=timeout,
        json_output=json_output,
    )


@app.command("repair-image", help="Repair a previous Responses API image result")
def repair_image(
    image: Annotated[
        list[str], typer.Option("--image", help="Original source image path; pass multiple times if needed")
    ],
    previous_response_id: Annotated[str, typer.Option("--previous-response-id")],
    issue: Annotated[str, typer.Option("--issue", help="Concrete visual issue to fix")],
    out: Annotated[str, typer.Option("--out")],
    prompt: Annotated[str | None, typer.Option("--prompt", help="Override the default repair prompt")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print result metadata as JSON")] = False,
    aspect_policy: Annotated[
        AspectPolicy | None,
        typer.Option("--aspect-policy", help="Required unless --size is passed; recommended: match-input"),
    ] = None,
    size: Annotated[str | None, typer.Option("--size", help="Exact output size, e.g. 1024x1536 or auto")] = None,
    quality: Annotated[
        Quality | None,
        typer.Option("--quality", help="Required: low for drafts, high for final repairs"),
    ] = None,
    output_format: Annotated[
        OutputFormat | None, typer.Option("--output-format", help="Required; usually keep the original format")
    ] = None,
    detail: Annotated[
        ImageDetail | None, typer.Option("--detail", help="Required for reference images; recommended: high")
    ] = None,
    background: Annotated[
        str | None, typer.Option("--background", help="Required: auto or opaque. Transparent is rejected.")
    ] = None,
    output_compression: Annotated[
        int | None,
        typer.Option("--output-compression", min=0, max=100, help="Required with jpeg or webp; rejected with png"),
    ] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="API request timeout in seconds")] = 1200,
) -> None:
    resolved_size, resolved_aspect_policy = resolve_size(size=size, aspect_policy=aspect_policy, reference_images=image)
    resolved_quality = require_choice(
        quality,
        "--quality",
        "It controls cost, latency, and final polish.",
        "high for final repairs; medium only when speed matters more than polish.",
    )
    resolved_format = require_choice(
        output_format,
        "--output-format",
        "It decides the artifact format.",
        "png for source-backed UI/card work.",
    )
    resolved_background = require_choice(
        background,
        "--background",
        "It controls how unspecified canvas areas are filled.",
        "auto for most repairs.",
    )
    resolved_detail = resolve_detail(detail, image)
    base_prompt = read_prompt(prompt or DEFAULT_REPAIR_PROMPT)
    repair_prompt = f"{base_prompt}\n\nIssue to fix:\n{issue.strip()}\n"
    call_response_image(
        prompt=repair_prompt,
        reference_images=image,
        out=out,
        previous_response_id=previous_response_id,
        aspect_policy=resolved_aspect_policy,
        size=resolved_size,
        quality=resolved_quality.value,
        output_format=resolved_format.value,
        action="edit",
        detail=resolved_detail,
        background=cast(Literal["opaque", "auto"], resolved_background),
        mask=None,
        moderation=None,
        output_compression=output_compression,
        partial_images=None,
        timeout=timeout,
        json_output=json_output,
    )


@app.command("diagnose-image", help="Read source and candidate images, then return repair guidance")
def diagnose_image(
    candidate: Annotated[
        list[str],
        typer.Option("--candidate", help="Candidate generated image to evaluate; pass multiple times if needed"),
    ],
    out: Annotated[str, typer.Option("--out", help="Diagnosis JSON output path")],
    criteria: Annotated[str, typer.Option("--criteria", help="Required acceptance criteria text or file")],
    source: Annotated[
        list[str] | None,
        typer.Option("--source", help="Original source/reference image; pass multiple times if needed"),
    ] = None,
    prompt: Annotated[str | None, typer.Option("--prompt", help="Override the default diagnosis prompt")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print result metadata as JSON")] = False,
    detail: Annotated[ImageDetail | None, typer.Option("--detail", help="Required: high, auto, or low")] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="API request timeout in seconds")] = 1200,
) -> None:
    require_key()
    criteria_text = read_prompt(criteria)
    diagnosis_prompt = read_prompt(prompt or DEFAULT_DIAGNOSE_PROMPT)
    diagnosis_prompt = f"{diagnosis_prompt}\n\nIntended teaching goal or acceptance criteria:\n{criteria_text}\n"
    resolved_detail = require_choice(
        detail,
        "--detail",
        "It controls how much visual information the judge reads from the source and candidate images.",
        "high for source-backed QA; auto only for loose visual checks.",
    )

    content: list[ResponseInputTextParam | ResponseInputImageParam | ResponseInputFileParam] = [
        {"type": "input_text", "text": diagnosis_prompt}
    ]
    for source_image in source or []:
        content.append(
            {
                "type": "input_image",
                "image_url": image_data_url(source_image),
                "detail": resolved_detail.value,
            }
        )
    for candidate_image in candidate:
        content.append(
            {
                "type": "input_image",
                "image_url": image_data_url(candidate_image),
                "detail": resolved_detail.value,
            }
        )

    client = make_client(timeout)
    message: Message = {"role": "user", "content": content}
    response = client.responses.create(
        model=DEFAULT_CONTROLLER_MODEL,
        input=[message],
        store=True,
    )
    data = model_dict(response)
    diagnosis_text = extract_response_text(data)
    diagnosis_json = parse_json_object(diagnosis_text)

    output_path = work_path(out)
    response_path = output_path.with_suffix(output_path.suffix + ".response.json")
    write_json(response_path, data)
    metadata = DiagnoseImageMetadata(
        kind="diagnose-image",
        output_path=str(output_path),
        response_path=str(response_path),
        response_id=data.get("id"),
        reasoning_model=DEFAULT_CONTROLLER_MODEL,
        sources=source or [],
        candidates=candidate,
        criteria=criteria_text,
        diagnosis=diagnosis_json if diagnosis_json is not None else diagnosis_text,
        client=client_metadata(),
    )
    write_json(output_path, metadata)
    emit_result(json_output, metadata)


@app.command("image-generate", help="Direct Images API generation")
def image_generate(
    prompt: Annotated[str, typer.Option("--prompt", help="Prompt text or prompt file")],
    out: Annotated[str, typer.Option("--out")],
    aspect_policy: Annotated[
        AspectPolicy | None,
        typer.Option(
            "--aspect-policy", help="Required unless --size is passed: auto, landscape, portrait, square, or explicit"
        ),
    ] = None,
    size: Annotated[
        str | None, typer.Option("--size", help="Exact output size, e.g. 1024x1536, 1536x1024, or auto")
    ] = None,
    quality: Annotated[
        DirectQuality | None,
        typer.Option("--quality", help="Required: low for drafts, high for final images, auto to delegate"),
    ] = None,
    background: Annotated[
        str | None,
        typer.Option("--background", help="Required: auto or opaque. Transparent is rejected for gpt-image-2."),
    ] = None,
    output_format: Annotated[
        OutputFormat | None, typer.Option("--output-format", help="Required: png, jpeg, or webp")
    ] = None,
    output_compression: Annotated[
        int | None,
        typer.Option("--output-compression", min=0, max=100, help="Required with jpeg or webp; rejected with png"),
    ] = None,
    moderation: Annotated[Moderation | None, typer.Option("--moderation")] = None,
    n: Annotated[int, typer.Option("--n", min=1, max=10)] = 1,
    json_output: Annotated[bool, typer.Option("--json", help="Print result metadata as JSON")] = False,
    timeout: Annotated[float, typer.Option("--timeout", help="API request timeout in seconds")] = 1200,
) -> None:
    resolved_size, resolved_aspect_policy = resolve_size(size=size, aspect_policy=aspect_policy, reference_images=None)
    resolved_quality = require_choice(
        quality,
        "--quality",
        "It controls cost, latency, and final polish.",
        "low for drafts, high for final images, auto only when you deliberately delegate.",
    )
    resolved_format = require_choice(
        output_format,
        "--output-format",
        "It decides the artifact format and whether compression can apply.",
        "png for lossless assets, jpeg for fast drafts, webp for compressed web assets.",
    )
    resolved_background = require_choice(
        background,
        "--background",
        "It controls the generated canvas background.",
        "auto for ordinary images; opaque for predictable post-processing.",
    )
    validate_latest_image_options(
        background=resolved_background,
        output_format=resolved_format.value,
        output_compression=output_compression,
    )
    require_key()
    client = make_client(timeout)
    prompt_text = read_prompt(prompt)
    response = client.images.generate(
        model=DEFAULT_IMAGE_MODEL,
        prompt=prompt_text,
        size=resolved_size,
        quality=resolved_quality.value,
        background=cast(Literal["opaque", "auto"], resolved_background),
        output_format=resolved_format.value,
        output_compression=output_compression if output_compression is not None else omit,
        moderation=moderation.value if moderation is not None else omit,
        n=n,
    )
    output_path = work_path(out)
    data = model_dict(response)
    output_paths = write_images_api_outputs(data, output_path)
    response_path = output_path.with_suffix(output_path.suffix + ".response.json")
    metadata_path = output_path.with_suffix(output_path.suffix + ".json")
    write_json(response_path, data)
    metadata = DirectImageMetadata(
        kind="image-generate",
        output_paths=output_paths,
        output_path=str(output_path),
        metadata_path=str(metadata_path),
        response_path=str(response_path),
        model=DEFAULT_IMAGE_MODEL,
        aspect_policy=resolved_aspect_policy,
        size=resolved_size,
        quality=resolved_quality.value,
        output_format=resolved_format.value,
        background=resolved_background,
        moderation=enum_value(moderation),
        output_compression=output_compression,
        n=n,
        prompt=prompt_text,
        client=client_metadata(),
    )
    write_json(metadata_path, metadata)
    emit_result(json_output, metadata)


@app.command("image-edit", help="Direct Images API edit")
def image_edit(
    prompt: Annotated[str, typer.Option("--prompt", help="Prompt text or prompt file")],
    image: Annotated[list[str], typer.Option("--image", help="Input image path; pass once per image")],
    out: Annotated[str, typer.Option("--out")],
    mask: Annotated[str | None, typer.Option("--mask", help="Optional image mask path")] = None,
    aspect_policy: Annotated[
        AspectPolicy | None,
        typer.Option("--aspect-policy", help="Required unless --size is passed; recommended: match-input"),
    ] = None,
    size: Annotated[
        str | None, typer.Option("--size", help="Exact output size, e.g. 1024x1536, 1536x1024, or auto")
    ] = None,
    quality: Annotated[
        DirectQuality | None,
        typer.Option("--quality", help="Required: low for drafts, high for final edits, auto to delegate"),
    ] = None,
    background: Annotated[
        str | None,
        typer.Option("--background", help="Required: auto or opaque. Transparent is rejected for gpt-image-2."),
    ] = None,
    output_format: Annotated[
        OutputFormat | None, typer.Option("--output-format", help="Required: png, jpeg, or webp")
    ] = None,
    output_compression: Annotated[
        int | None,
        typer.Option("--output-compression", min=0, max=100, help="Required with jpeg or webp; rejected with png"),
    ] = None,
    moderation: Annotated[Moderation | None, typer.Option("--moderation")] = None,
    n: Annotated[int, typer.Option("--n", min=1, max=10)] = 1,
    json_output: Annotated[bool, typer.Option("--json", help="Print result metadata as JSON")] = False,
    timeout: Annotated[float, typer.Option("--timeout", help="API request timeout in seconds")] = 1200,
) -> None:
    resolved_size, resolved_aspect_policy = resolve_size(size=size, aspect_policy=aspect_policy, reference_images=image)
    resolved_quality = require_choice(
        quality,
        "--quality",
        "It controls cost, latency, and final polish.",
        "high for final edits; low only for quick drafts.",
    )
    resolved_format = require_choice(
        output_format,
        "--output-format",
        "It decides the artifact format and whether compression can apply.",
        "png for source-backed edits; jpeg only for throwaway drafts.",
    )
    resolved_background = require_choice(
        background,
        "--background",
        "It controls how unspecified canvas areas are filled.",
        "auto for most edits; opaque for predictable post-processing.",
    )
    validate_latest_image_options(
        background=resolved_background,
        output_format=resolved_format.value,
        output_compression=output_compression,
    )
    require_key()
    validate_mask(mask, image)
    image_paths = [work_path(path) for path in image]
    mask_path = work_path(mask) if mask else None
    output_path = work_path(out)
    client = make_client(timeout)
    prompt_text = read_prompt(prompt)

    files = [path.open("rb") for path in image_paths]
    mask_file = mask_path.open("rb") if mask_path else None
    try:
        kwargs: dict[str, Any] = {
            "image": files,
            "model": DEFAULT_IMAGE_MODEL,
            "prompt": prompt_text,
            "size": resolved_size,
            "quality": resolved_quality.value,
            "background": cast(Literal["opaque", "auto"], resolved_background),
            "output_format": resolved_format.value,
            "output_compression": output_compression if output_compression is not None else omit,
            "n": n,
        }
        if moderation is not None:
            kwargs["moderation"] = moderation.value
        if mask_file:
            kwargs["mask"] = mask_file
        response = client.images.edit(**kwargs)
    finally:
        for file in files:
            file.close()
        if mask_file:
            mask_file.close()

    data = model_dict(response)
    output_paths = write_images_api_outputs(data, output_path)
    response_path = output_path.with_suffix(output_path.suffix + ".response.json")
    metadata_path = output_path.with_suffix(output_path.suffix + ".json")
    write_json(response_path, data)
    metadata = DirectImageMetadata(
        kind="image-edit",
        output_paths=output_paths,
        output_path=str(output_path),
        metadata_path=str(metadata_path),
        response_path=str(response_path),
        model=DEFAULT_IMAGE_MODEL,
        aspect_policy=resolved_aspect_policy,
        size=resolved_size,
        quality=resolved_quality.value,
        output_format=resolved_format.value,
        background=resolved_background,
        output_compression=output_compression,
        n=n,
        prompt=prompt_text,
        images=image,
        mask=mask,
        client=client_metadata(),
    )
    write_json(metadata_path, metadata)
    emit_result(json_output, metadata)


@app.command("contact-sheet", help="Create a local image contact sheet for visual QA")
def contact_sheet(
    image: Annotated[list[str], typer.Option("--image")],
    out: Annotated[str, typer.Option("--out")],
    columns: Annotated[int, typer.Option("--columns")] = 2,
    thumb_width: Annotated[int, typer.Option("--thumb-width")] = 430,
    json_output: Annotated[bool, typer.Option("--json", help="Print result metadata as JSON")] = False,
) -> None:
    images = [work_path(path) for path in image]
    if not images:
        fail("At least one --image is required.")

    label_height = 34
    pad = 18
    thumbs: list[tuple[Path, Image.Image]] = []
    for path in images:
        try:
            loaded_image = Image.open(path).convert("RGB")
        except OSError as exc:
            fail(f"cannot open --image {path}: {exc}")
        height = int(loaded_image.height * thumb_width / loaded_image.width)
        thumbs.append((path, loaded_image.resize((thumb_width, height), Image.Resampling.LANCZOS)))

    cols = max(1, columns)
    rows = (len(thumbs) + cols - 1) // cols
    cell_height = max(loaded_image.height for _, loaded_image in thumbs) + label_height + pad
    sheet = Image.new(
        "RGB",
        (cols * (thumb_width + pad) + pad, rows * cell_height + pad),
        (15, 24, 32),
    )
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 17)
    except OSError:
        font = ImageFont.load_default()

    for index, (path, loaded_image) in enumerate(thumbs):
        x = pad + (index % cols) * (thumb_width + pad)
        y = pad + (index // cols) * cell_height
        draw.text((x, y), path.stem, fill=(245, 234, 215), font=font)
        sheet.paste(loaded_image, (x, y + label_height))

    output_path = work_path(out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    emit_result(
        json_output,
        ContactSheetMetadata(
            kind="contact-sheet",
            output_path=str(output_path),
            images=[str(path) for path in images],
            columns=cols,
            thumb_width=thumb_width,
        ),
    )


@app.command("chroma-alpha", help="Convert a flat chroma background to transparency")
def chroma_alpha(
    image: Annotated[str, typer.Option("--image")],
    out: Annotated[str, typer.Option("--out")],
    color: Annotated[str, typer.Option("--color")] = "#00ff00",
    tolerance: Annotated[int, typer.Option("--tolerance")] = 28,
    feather: Annotated[int, typer.Option("--feather")] = 24,
    json_output: Annotated[bool, typer.Option("--json", help="Print result metadata as JSON")] = False,
) -> None:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        fail(f"--color must be #rrggbb, got: {color}")
    try:
        src = Image.open(work_path(image)).convert("RGBA")
    except OSError as exc:
        fail(f"cannot open --image {image}: {exc}")
    target = tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))
    source = src.tobytes()
    output = bytearray()
    for index in range(0, len(source), 4):
        red = source[index]
        green = source[index + 1]
        blue = source[index + 2]
        alpha = source[index + 3]
        distance = max(
            abs(red - target[0]),
            abs(green - target[1]),
            abs(blue - target[2]),
        )
        if distance <= tolerance:
            output.extend((red, green, blue, 0))
        elif distance <= tolerance + feather:
            fade = (distance - tolerance) / max(1, feather)
            output.extend((red, green, blue, int(alpha * fade)))
        else:
            output.extend((red, green, blue, alpha))
    src = Image.frombytes("RGBA", src.size, bytes(output))

    output_path = work_path(out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    src.save(output_path)
    emit_result(
        json_output,
        ChromaAlphaMetadata(
            kind="chroma-alpha",
            output_path=str(output_path),
            input_path=str(work_path(image)),
            color=color,
            tolerance=tolerance,
            feather=feather,
        ),
    )


def main() -> None:
    try:
        app()
    except OpenAIError as exc:
        typer.echo(f"OpenAI API error: {exc}", err=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
