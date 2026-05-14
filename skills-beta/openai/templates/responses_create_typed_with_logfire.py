from __future__ import annotations

import asyncio

import logfire
from openai import AsyncOpenAI
from openai.types.responses import ResponseInputTextParam
from openai.types.responses.response_input_param import Message


async def call_model_with_observability(
    *,
    model: str,
    text: str,
    timeout_s: float = 60.0,
) -> str:
    """Typed call with logfire span and timeout."""
    client = AsyncOpenAI()

    text_item: ResponseInputTextParam = {"type": "input_text", "text": text}
    message: Message = {"role": "user", "content": [text_item]}

    with logfire.span("openai.responses.create", model=model) as span:
        try:
            response_task = client.responses.create(
                model=model,
                input=[message],
                stream=False,
            )
            resp = await asyncio.wait_for(response_task, timeout=timeout_s)
            return resp.output_text or ""
        except Exception as e:  # noqa: BLE001
            span.record_exception(e)
            span.set_level("error")
            raise
