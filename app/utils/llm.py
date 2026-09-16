"""
Thin wrapper over the OpenAI Responses API (/v1/responses).

Centralises the per-model quirks so call sites stay simple:
  - `reasoning` is only sent to reasoning models (gpt-5.x, o-series);
    gpt-4o / gpt-4.1 reject it.
  - Reasoning models only accept a custom `temperature` when effort is
    "none", so it is dropped otherwise.
  - `max_output_tokens` includes reasoning tokens, so extra headroom is
    added when the model is allowed to think.
"""
import re

import openai

from app.config import get_settings

# Extra output budget when reasoning is on (reasoning tokens count toward it).
_REASONING_HEADROOM = {"minimal": 1000, "low": 2000, "medium": 4000, "high": 8000, "xhigh": 16000}

_REASONING_MODEL = re.compile(r"^(gpt-5|o\d)")


def is_reasoning_model(model: str) -> bool:
    return bool(_REASONING_MODEL.match(model)) and "chat-latest" not in model


def client() -> openai.OpenAI:
    return openai.OpenAI(api_key=get_settings().openai_api_key)


def respond(
    model: str,
    input,
    *,
    instructions: str | None = None,
    effort: str | None = None,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    json_mode: bool = False,
    tools: list | None = None,
    tool_choice: str | None = None,
    timeout: float | None = None,
    oa: openai.OpenAI | None = None,
):
    """Call responses.create() with model-appropriate parameters.

    `effort` defaults to OPENAI_REASONING_EFFORT. Returns the Response;
    use `.output_text` for the reply and `.output` for tool calls.
    """
    kwargs: dict = {"model": model, "input": input, "store": False}
    if instructions:
        kwargs["instructions"] = instructions

    thinking = False
    if is_reasoning_model(model):
        effort = effort or get_settings().openai_reasoning_effort or "none"
        kwargs["reasoning"] = {"effort": effort}
        thinking = effort != "none"
        if thinking:
            # store=False: reasoning items must round-trip as encrypted content
            # so tool-call follow-ups can pass response.output back in.
            kwargs["include"] = ["reasoning.encrypted_content"]

    if temperature is not None and not thinking:
        kwargs["temperature"] = temperature
    if max_output_tokens is not None:
        kwargs["max_output_tokens"] = max_output_tokens + (_REASONING_HEADROOM.get(effort, 2000) if thinking else 0)
    if json_mode:
        kwargs["text"] = {"format": {"type": "json_object"}}
        # The API requires "json" in the input messages (instructions don't count).
        if isinstance(input, str):
            input = [{"role": "user", "content": input}]
        kwargs["input"] = [{"role": "developer", "content": "Responde en formato JSON."}, *input]
    if tools is not None:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    if timeout is not None:
        kwargs["timeout"] = timeout

    return (oa or client()).responses.create(**kwargs)


def function_calls(response) -> list:
    """Function-call output items (have .call_id, .name, .arguments)."""
    return [item for item in response.output if item.type == "function_call"]
