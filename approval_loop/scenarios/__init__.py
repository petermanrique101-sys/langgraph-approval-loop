"""A scenario is a tool set plus the rules that say which calls are risky."""

from dataclasses import dataclass
from typing import Callable

from langchain_core.tools import BaseTool

from ..policy import Rules


@dataclass(frozen=True)
class Scenario:
    name: str
    system_prompt: str
    tools: list[BaseTool]
    rules: Rules
    # One plain-English question for the approval card, built from the call's
    # own args by code, never by the model, so it cannot misstate what runs.
    describe: Callable[[str, dict], str]


def load(name: str) -> Scenario:
    if name == "dev":
        from .dev import SCENARIO
    elif name == "nutrishop":
        from .nutrishop import SCENARIO
    else:
        raise ValueError(f"unknown scenario {name!r}; choose dev or nutrishop")
    return SCENARIO
