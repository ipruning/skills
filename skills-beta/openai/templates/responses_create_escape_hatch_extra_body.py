from __future__ import annotations

from openai import AsyncOpenAI
from openai.types.responses import ResponseInputTextParam
from openai.types.responses.response_input_param import Message


async def call_model_with_escape_hatch(*, model: str, text: str) -> str:
    """Example: pass a new/untyped field without losing type safety on inputs."""
    client = AsyncOpenAI()

    text_item: ResponseInputTextParam = {"type": "input_text", "text": text}
    message: Message = {"role": "user", "content": [text_item]}

    resp = await client.responses.create(
        model=model,
        input=[message],
        stream=False,
        extra_body={
            "some_new_top_level_param": "value",
        },
    )
    return resp.output_text or ""
