from openai import AsyncOpenAI
from openai.types.responses import ResponseInputTextParam, ResponseTextDeltaEvent
from openai.types.responses.response_input_param import Message


async def stream_response(client: AsyncOpenAI, prompt: str) -> str:
    """Stream a response and return the full text."""
    text_item: ResponseInputTextParam = {"type": "input_text", "text": prompt}
    message: Message = {"role": "user", "content": [text_item]}

    stream = await client.responses.create(
        model="gpt-5.2",
        input=[message],
        stream=True,
    )

    full_text = ""
    async for event in stream:
        if isinstance(event, ResponseTextDeltaEvent):
            full_text += event.delta
            print(event.delta, end="", flush=True)

    print()  # Newline after streaming
    return full_text
