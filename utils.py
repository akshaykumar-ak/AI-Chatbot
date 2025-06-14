import os
from logging import Logger
from typing import Optional, Union, AsyncGenerator, AsyncIterable, Literal, List

from models.agent_config import FunctionFragment

environment = {}


def setenv(**kwargs):
    for key, value in kwargs.items():
        environment[key] = value


def getenv(key, default=None):
    return environment.get(key) or os.getenv(key, default)


async def openai_get_tokens(gen, logger:Optional[Logger]=None) -> AsyncGenerator[Union[str, FunctionFragment], None]:
    has_finished = False
    async for event in gen:
        usage = event.usage if hasattr(event, 'usage') else None
        if has_finished:
            break
        choices = event.choices
        if len(choices) == 0 and not usage:
            continue
        choice = choices[0]
        delta = choice.delta
        if hasattr(delta, "text") and delta.text:
            token = delta.text
            yield token
        if hasattr(delta, "content") and delta.content:
            token = delta.content
            yield token
        elif hasattr(delta, "function_call") and delta.function_call:
            yield FunctionFragment(
                name=(
                    delta.function_call.name
                    if hasattr(delta.function_call, "name")
                    and delta.function_call.name
                    else ""
                ),
                arguments=(
                    delta.function_call.arguments
                    if hasattr(delta.function_call, "arguments")
                    and delta.function_call.arguments
                    else ""
                ),
            )
        if choice.finish_reason:
            has_finished = True
            continue
