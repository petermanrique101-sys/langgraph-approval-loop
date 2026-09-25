"""Five nodes, one conditional edge.

call_model -> route -> policy | END
policy     -> approve | execute | call_model (denied)
approve    -> execute | call_model
execute    -> call_model
"""

import os
import time
from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .answers import parse_answer
from .policy import decide
from .scenarios import Scenario, load
from .state import Approval, State


def _after_tool(pending: list[dict]) -> Literal["policy", "call_model"]:
    """After one tool call is answered, decide the next one or go back to the model."""
    return "policy" if pending else "call_model"


def _tool_message(call: dict, content: str, *, error: bool = False) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call["id"], name=call["name"], status="error" if error else "success")


def build_graph(model=None, checkpointer=None, scenario: Scenario | None = None):
    scenario = scenario or load("dev")
    model = model or init_chat_model(os.environ.get("MODEL", "ollama:qwen3.6:27b"))
    model_with_tools = model.bind_tools(scenario.tools)
    tools_by_name = {t.name: t for t in scenario.tools}
    rules = scenario.rules

    def call_model(state: State):
        messages = [SystemMessage(scenario.system_prompt), *state["messages"]]
        ai = model_with_tools.invoke(messages)
        return {"messages": [ai], "pending": list(ai.tool_calls), "decision": None}

    def route(state: State) -> Literal["policy", "__end__"]:
        return "policy" if state["pending"] else END

    def policy(state: State) -> Command[Literal["approve", "execute", "policy", "call_model"]]:
        call = state["pending"][0]
        decision = decide(call["name"], call["args"], state["profile"], state["approvals"], time.time(), rules)
        if decision["verdict"] == "deny":
            rest = state["pending"][1:]
            return Command(
                update={"decision": decision, "pending": rest,
                        "messages": [_tool_message(call, f"Denied without asking: {decision['reason']}", error=True)]},
                goto=_after_tool(rest),
            )
        return Command(update={"decision": decision}, goto="approve" if decision["verdict"] == "ask" else "execute")

    def approve(state: State) -> Command[Literal["execute", "policy", "call_model"]]:
        # interrupt() must be the first statement: on resume LangGraph re-runs
        # the node from the top, and resume values match interrupts by index.
        call = state["pending"][0]
        decision = state["decision"]
        answer = interrupt({
            "question": scenario.describe(call["name"], call["args"]),
            "answer_with": "yes, or no plus a reason (e.g. no, wait until Friday)",
            "tool": call["name"],
            "args": call["args"],
            "reason": decision["reason"],
            "fingerprint": decision["fingerprint"],
        })
        parsed = parse_answer(answer)
        approved = parsed["approved"]
        human_reason = parsed["reason"]
        record = Approval(
            fingerprint=decision["fingerprint"],
            verdict="approved" if approved else "denied",
            at=time.time(),
            reason=human_reason,
        )
        if approved:
            return Command(update={"approvals": [record]}, goto="execute")
        rest = state["pending"][1:]
        text = f"Denied by the user: {human_reason}" if human_reason else "Denied by the user (no reason given)"
        return Command(
            update={"approvals": [record], "pending": rest, "messages": [_tool_message(call, text, error=True)]},
            goto=_after_tool(rest),
        )

    def execute(state: State) -> Command[Literal["policy", "call_model"]]:
        call = state["pending"][0]
        try:
            result = tools_by_name[call["name"]].invoke(call["args"])
            msg = _tool_message(call, str(result))
        except Exception as e:  # the model should see tool failures, not the process
            msg = _tool_message(call, f"{type(e).__name__}: {e}", error=True)
        rest = state["pending"][1:]
        return Command(update={"pending": rest, "messages": [msg]}, goto=_after_tool(rest))

    builder = StateGraph(State)
    builder.add_node("call_model", call_model)
    builder.add_node("policy", policy)
    builder.add_node("approve", approve)
    builder.add_node("execute", execute)
    builder.add_edge(START, "call_model")
    builder.add_conditional_edges("call_model", route)
    return builder.compile(checkpointer=checkpointer)
