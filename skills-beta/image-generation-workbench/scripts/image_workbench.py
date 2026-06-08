#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "openai>=2.41.0",
#   "pillow>=12.2.0",
#   "pydantic>=2.12.0",
#   "pydantic-settings>=2.12.0",
#   "typer>=0.20.0",
# ]
# ///
from __future__ import annotations

import base64
import json
import mimetypes
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

ResponseImageSize = Literal["1024x1024", "1024x1536", "1536x1024", "auto"]

app = typer.Typer(
    help="General image generation workbench",
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


class ImageDetail(StrEnum):
    LOW = "low"
    HIGH = "high"
    AUTO = "auto"
    ORIGINAL = "original"


class Background(StrEnum):
    TRANSPARENT = "transparent"
    OPAQUE = "opaque"
    AUTO = "auto"


class InputFidelity(StrEnum):
    HIGH = "high"
    LOW = "low"


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
    image_model_override: str | None
    size: str
    quality: str
    action: str
    output_format: str
    background: str | None
    input_fidelity: str | None
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
    size: str
    quality: str
    output_format: str
    background: str | None
    output_compression: int | None
    n: int
    prompt: str
    client: ClientMetadata
    moderation: str | None = None
    input_fidelity: str | None = None
    images: list[str] | None = None
    mask: str | None = None


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
    return str(value)


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


def first_image_b64(data: dict[str, Any]) -> str:
    items = data.get("data")
    if not isinstance(items, list) or not items:
        fail("Images API response did not include data[0].")
    first = items[0]
    if not isinstance(first, dict):
        fail("Images API response data[0] is not an object.")
    b64_json = first.get("b64_json")
    if not isinstance(b64_json, str):
        fail("Images API response did not include b64_json.")
    return b64_json


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


def check_image_model_options(
    *,
    image_model: str | None,
    background: str | None,
    input_fidelity: str | None,
) -> None:
    if image_model == "gpt-image-2" and input_fidelity:
        fail("Do not pass input_fidelity with gpt-image-2; image inputs are high fidelity by default for this model.")
    if image_model == "gpt-image-2" and background == "transparent":
        fail(
            'gpt-image-2 does not support background="transparent". Use opaque/auto or post-process a green-screen image.'
        )


def check_direct_image_options(
    *,
    model: str,
    background: str | None,
    input_fidelity: str | None,
) -> None:
    check_image_model_options(
        image_model=model,
        background=background,
        input_fidelity=input_fidelity,
    )


def call_response_image(
    *,
    prompt: str,
    reference_images: list[str] | None,
    out: str,
    previous_response_id: str | None,
    reasoning_model: str,
    image_model: str | None,
    size: str,
    quality: str,
    output_format: str,
    action: str,
    detail: str,
    background: str | None,
    input_fidelity: str | None,
    mask: str | None,
    moderation: str | None,
    output_compression: int | None,
    partial_images: int | None,
    timeout: float,
    json_output: bool,
) -> None:
    check_image_model_options(
        image_model=image_model,
        background=background,
        input_fidelity=input_fidelity,
    )
    if partial_images is not None and not 0 <= partial_images <= 3:
        fail("partial_images must be between 0 and 3.")

    require_key()

    text_item: ResponseInputTextParam = {"type": "input_text", "text": prompt}
    content: list[ResponseInputTextParam | ResponseInputImageParam | ResponseInputFileParam] = [text_item]
    for image in reference_images or []:
        image_item: ResponseInputImageParam = {
            "type": "input_image",
            "image_url": image_data_url(image),
            "detail": cast(Literal["low", "high", "auto"], detail),
        }
        content.append(image_item)

    tool: ImageGeneration = {
        "type": "image_generation",
        "size": cast(ResponseImageSize, size),
        "quality": cast(Literal["low", "medium", "high", "auto"], quality),
        "output_format": cast(Literal["png", "jpeg", "webp"], output_format),
        "action": cast(Literal["generate", "edit", "auto"], action),
    }
    if image_model:
        tool["model"] = image_model
    if background:
        tool["background"] = cast(Literal["transparent", "opaque", "auto"], background)
    if input_fidelity:
        tool["input_fidelity"] = cast(Literal["high", "low"], input_fidelity)
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
            model=reasoning_model,
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
            model=reasoning_model,
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
        reasoning_model=reasoning_model,
        image_model_override=image_model,
        size=size,
        quality=quality,
        action=action,
        output_format=output_format,
        background=background,
        input_fidelity=input_fidelity,
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
    out: Annotated[str, typer.Option("--out")],
    image: Annotated[
        list[str] | None, typer.Option("--image", help="Reference image path; pass once per image")
    ] = None,
    previous_response_id: Annotated[str | None, typer.Option("--previous-response-id")] = None,
    reasoning_model: Annotated[
        str, typer.Option("--reasoning-model", "--model", help="Responses API controller model")
    ] = DEFAULT_CONTROLLER_MODEL,
    image_model: Annotated[
        str | None,
        typer.Option(
            "--image-model", help="Optional image generation tool model override; omit to let Responses API select"
        ),
    ] = None,
    size: Annotated[str, typer.Option("--size")] = "1536x1024",
    quality: Annotated[Quality, typer.Option("--quality")] = Quality.MEDIUM,
    output_format: Annotated[OutputFormat, typer.Option("--output-format")] = OutputFormat.PNG,
    action: Annotated[ResponseAction, typer.Option("--action")] = ResponseAction.AUTO,
    detail: Annotated[ImageDetail, typer.Option("--detail")] = ImageDetail.HIGH,
    background: Annotated[Background | None, typer.Option("--background")] = None,
    input_fidelity: Annotated[
        InputFidelity | None,
        typer.Option("--input-fidelity", help="Only for models that support it; do not use with gpt-image-2"),
    ] = None,
    mask: Annotated[str | None, typer.Option("--mask", help="Image mask for edit operations")] = None,
    moderation: Annotated[Moderation | None, typer.Option("--moderation")] = None,
    output_compression: Annotated[int | None, typer.Option("--output-compression")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print result metadata as JSON")] = False,
    partial_images: Annotated[
        int | None,
        typer.Option("--partial-images", min=0, max=3, help="Enable streaming and save partial image frames"),
    ] = None,
    timeout: Annotated[float, typer.Option("--timeout")] = 1200,
) -> None:
    call_response_image(
        prompt=read_prompt(prompt),
        reference_images=image,
        out=out,
        previous_response_id=previous_response_id,
        reasoning_model=reasoning_model,
        image_model=image_model,
        size=size,
        quality=quality.value,
        output_format=output_format.value,
        action=action.value,
        detail=detail.value,
        background=enum_value(background),
        input_fidelity=enum_value(input_fidelity),
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
    reasoning_model: Annotated[str, typer.Option("--reasoning-model", "--model")] = DEFAULT_CONTROLLER_MODEL,
    image_model: Annotated[
        str | None,
        typer.Option(
            "--image-model", help="Optional image generation tool model override; omit to let Responses API select"
        ),
    ] = None,
    size: Annotated[str, typer.Option("--size")] = "1536x1024",
    quality: Annotated[Quality, typer.Option("--quality")] = Quality.MEDIUM,
    detail: Annotated[ImageDetail, typer.Option("--detail")] = ImageDetail.HIGH,
    timeout: Annotated[float, typer.Option("--timeout")] = 1200,
) -> None:
    call_response_image(
        prompt=read_prompt(prompt or DEFAULT_TUTORIAL_PROMPT),
        reference_images=image,
        out=out,
        previous_response_id=None,
        reasoning_model=reasoning_model,
        image_model=image_model,
        size=size,
        quality=quality.value,
        output_format="png",
        action="edit",
        detail=detail.value,
        background=None,
        input_fidelity=None,
        mask=None,
        moderation=None,
        output_compression=None,
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
    reasoning_model: Annotated[str, typer.Option("--reasoning-model", "--model")] = DEFAULT_CONTROLLER_MODEL,
    image_model: Annotated[
        str | None,
        typer.Option(
            "--image-model", help="Optional image generation tool model override; omit to let Responses API select"
        ),
    ] = None,
    size: Annotated[str, typer.Option("--size")] = "1536x1024",
    quality: Annotated[Quality, typer.Option("--quality")] = Quality.MEDIUM,
    detail: Annotated[ImageDetail, typer.Option("--detail")] = ImageDetail.HIGH,
    timeout: Annotated[float, typer.Option("--timeout")] = 1200,
) -> None:
    base_prompt = read_prompt(prompt or DEFAULT_REPAIR_PROMPT)
    repair_prompt = f"{base_prompt}\n\nIssue to fix:\n{issue.strip()}\n"
    call_response_image(
        prompt=repair_prompt,
        reference_images=image,
        out=out,
        previous_response_id=previous_response_id,
        reasoning_model=reasoning_model,
        image_model=image_model,
        size=size,
        quality=quality.value,
        output_format="png",
        action="edit",
        detail=detail.value,
        background=None,
        input_fidelity=None,
        mask=None,
        moderation=None,
        output_compression=None,
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
    source: Annotated[
        list[str] | None,
        typer.Option("--source", help="Original source/reference image; pass multiple times if needed"),
    ] = None,
    criteria: Annotated[str | None, typer.Option("--criteria", help="Acceptance criteria text or file")] = None,
    prompt: Annotated[str | None, typer.Option("--prompt", help="Override the default diagnosis prompt")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print result metadata as JSON")] = False,
    reasoning_model: Annotated[str, typer.Option("--reasoning-model", "--model")] = DEFAULT_CONTROLLER_MODEL,
    detail: Annotated[ImageDetail, typer.Option("--detail")] = ImageDetail.HIGH,
    timeout: Annotated[float, typer.Option("--timeout")] = 1200,
) -> None:
    require_key()
    criteria_text = read_prompt(criteria) if criteria else ""
    diagnosis_prompt = read_prompt(prompt or DEFAULT_DIAGNOSE_PROMPT)
    if criteria_text:
        diagnosis_prompt = f"{diagnosis_prompt}\n\nIntended teaching goal or acceptance criteria:\n{criteria_text}\n"

    content: list[ResponseInputTextParam | ResponseInputImageParam | ResponseInputFileParam] = [
        {"type": "input_text", "text": diagnosis_prompt}
    ]
    for source_image in source or []:
        content.append(
            {
                "type": "input_image",
                "image_url": image_data_url(source_image),
                "detail": cast(Literal["low", "high", "auto"], detail.value),
            }
        )
    for candidate_image in candidate:
        content.append(
            {
                "type": "input_image",
                "image_url": image_data_url(candidate_image),
                "detail": cast(Literal["low", "high", "auto"], detail.value),
            }
        )

    client = make_client(timeout)
    message: Message = {"role": "user", "content": content}
    response = client.responses.create(
        model=reasoning_model,
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
        reasoning_model=reasoning_model,
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
    model: Annotated[str, typer.Option("--model")] = DEFAULT_IMAGE_MODEL,
    size: Annotated[str, typer.Option("--size")] = "1536x1024",
    quality: Annotated[DirectQuality, typer.Option("--quality")] = DirectQuality.MEDIUM,
    background: Annotated[Background | None, typer.Option("--background")] = None,
    output_format: Annotated[OutputFormat, typer.Option("--output-format")] = OutputFormat.PNG,
    output_compression: Annotated[int | None, typer.Option("--output-compression")] = None,
    moderation: Annotated[Moderation | None, typer.Option("--moderation")] = None,
    n: Annotated[int, typer.Option("--n")] = 1,
    json_output: Annotated[bool, typer.Option("--json", help="Print result metadata as JSON")] = False,
    timeout: Annotated[float, typer.Option("--timeout")] = 1200,
) -> None:
    check_direct_image_options(
        model=model,
        background=enum_value(background),
        input_fidelity=None,
    )
    require_key()
    client = make_client(timeout)
    prompt_text = read_prompt(prompt)
    response = client.images.generate(
        model=model,
        prompt=prompt_text,
        size=size,
        quality=quality.value,
        background=background.value if background is not None else omit,
        output_format=output_format.value,
        output_compression=output_compression if output_compression is not None else omit,
        moderation=moderation.value if moderation is not None else omit,
        n=n,
    )
    output_path = work_path(out)
    data = model_dict(response)
    write_b64_image(first_image_b64(data), output_path)
    response_path = output_path.with_suffix(output_path.suffix + ".response.json")
    metadata_path = output_path.with_suffix(output_path.suffix + ".json")
    write_json(response_path, data)
    metadata = DirectImageMetadata(
        kind="image-generate",
        output_path=str(output_path),
        metadata_path=str(metadata_path),
        response_path=str(response_path),
        model=model,
        size=size,
        quality=quality.value,
        output_format=output_format.value,
        background=enum_value(background),
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
    input_fidelity: Annotated[
        InputFidelity | None,
        typer.Option("--input-fidelity", help="Only for models that support it; do not use with gpt-image-2"),
    ] = None,
    model: Annotated[str, typer.Option("--model")] = DEFAULT_IMAGE_MODEL,
    size: Annotated[str, typer.Option("--size")] = "1536x1024",
    quality: Annotated[DirectQuality, typer.Option("--quality")] = DirectQuality.MEDIUM,
    background: Annotated[Background | None, typer.Option("--background")] = None,
    output_format: Annotated[OutputFormat, typer.Option("--output-format")] = OutputFormat.PNG,
    output_compression: Annotated[int | None, typer.Option("--output-compression")] = None,
    moderation: Annotated[Moderation | None, typer.Option("--moderation")] = None,
    n: Annotated[int, typer.Option("--n")] = 1,
    json_output: Annotated[bool, typer.Option("--json", help="Print result metadata as JSON")] = False,
    timeout: Annotated[float, typer.Option("--timeout")] = 1200,
) -> None:
    check_direct_image_options(
        model=model,
        background=enum_value(background),
        input_fidelity=enum_value(input_fidelity),
    )
    require_key()
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
            "model": model,
            "prompt": prompt_text,
            "size": size,
            "quality": quality.value,
            "background": background.value if background is not None else omit,
            "input_fidelity": input_fidelity.value if input_fidelity is not None else omit,
            "output_format": output_format.value,
            "output_compression": output_compression if output_compression is not None else omit,
            "n": n,
        }
        if mask_file:
            kwargs["mask"] = mask_file
        response = client.images.edit(**kwargs)
    finally:
        for file in files:
            file.close()
        if mask_file:
            mask_file.close()

    data = model_dict(response)
    write_b64_image(first_image_b64(data), output_path)
    response_path = output_path.with_suffix(output_path.suffix + ".response.json")
    metadata_path = output_path.with_suffix(output_path.suffix + ".json")
    write_json(response_path, data)
    metadata = DirectImageMetadata(
        kind="image-edit",
        output_path=str(output_path),
        metadata_path=str(metadata_path),
        response_path=str(response_path),
        model=model,
        size=size,
        quality=quality.value,
        output_format=output_format.value,
        background=enum_value(background),
        input_fidelity=enum_value(input_fidelity),
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
        loaded_image = Image.open(path).convert("RGB")
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
    src = Image.open(work_path(image)).convert("RGBA")
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
