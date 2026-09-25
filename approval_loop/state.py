"""Graph state. One thread = one task."""

import operator
from typing import Annotated, Literal, TypedDict

from langgraph.graph.message import add_messages

Profile = Literal["normal", "autonomous"]
Verdict = Literal["allow", "ask", "deny"]


class Approval(TypedDict):
    fingerprint: str
    verdict: Literal["approved", "denied"]
    at: float  # epoch seconds
    reason: str | None


class Decision(TypedDict):
    verdict: Verdict
    reason: str
    fingerprint: str


class State(TypedDict):
    messages: Annotated[list, add_messages]
    # Tool calls from the latest AI message that have not been answered yet.
    # The head is the one being decided; every entry gets a tool message
    # before the model runs again.
    pending: list[dict]
    decision: Decision | None
    profile: Profile
    approvals: Annotated[list[Approval], operator.add]
