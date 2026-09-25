"""The graph with a scripted model: the interrupt fires, survives a fresh graph
instance on the same checkpoint, resumes, and denial reasons reach the model."""

import sqlite3

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from approval_loop.graph import build_graph

CONFIG = {"configurable": {"thread_id": "t1"}}


class ScriptedModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def scripted(*messages):
    return ScriptedModel(messages=iter(messages))


def start(graph, prompt="clean the build directory", profile="normal"):
    return graph.invoke({"messages": [HumanMessage(prompt)], "profile": profile, "pending": [], "approvals": []}, CONFIG)


def rm_rf_call():
    return AIMessage(content="", tool_calls=[{"name": "bash", "args": {"command": "rm -rf build"}, "id": "c1"}])


def test_floor_hit_interrupts_and_resumes_across_graph_instances(tmp_path):
    conn = sqlite3.connect(tmp_path / "cp.db", check_same_thread=False)
    saver = SqliteSaver(conn)

    graph1 = build_graph(model=scripted(rm_rf_call(), AIMessage("done")), checkpointer=saver)
    result = start(graph1)
    card = result["__interrupt__"][0].value
    assert card["tool"] == "bash" and card["reason"] == "irreversible: rm -rf"

    # "Kill the process": a new graph on the same checkpoint is still at the card.
    graph2 = build_graph(model=scripted(AIMessage("done")), checkpointer=saver)
    snapshot = graph2.get_state(CONFIG)
    assert snapshot.next == ("approve",)
    assert snapshot.tasks[0].interrupts[0].value == card

    final = graph2.invoke(Command(resume={"approved": True}), CONFIG)
    tool_msgs = [m for m in final["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs[0].content.startswith("exit ")
    assert final["messages"][-1].content == "done"
    assert final["approvals"][0]["verdict"] == "approved"


def test_denial_reason_reaches_the_model_verbatim():
    graph = build_graph(model=scripted(rm_rf_call(), AIMessage("ok, leaving it")), checkpointer=InMemorySaver())
    start(graph)
    final = graph.invoke(Command(resume={"approved": False, "reason": "keep the cache"}), CONFIG)
    tool_msg = next(m for m in final["messages"] if isinstance(m, ToolMessage))
    assert tool_msg.content == "Denied by the user: keep the cache"
    assert tool_msg.status == "error"


def test_ungated_read_runs_without_a_card(tmp_path, monkeypatch):
    import approval_loop.tools as tools
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    read = AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": "a.txt"}, "id": "c1"}])
    graph = build_graph(model=scripted(read, AIMessage("it says hello")), checkpointer=InMemorySaver())
    final = start(graph, "read a.txt")
    assert "__interrupt__" not in final
    assert next(m for m in final["messages"] if isinstance(m, ToolMessage)).content == "hello"


def test_autonomous_write_runs_but_floor_still_cards(tmp_path, monkeypatch):
    import approval_loop.tools as tools
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    write = AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": "b.txt", "content": "x"}, "id": "c1"}])
    graph = build_graph(model=scripted(write, rm_rf_call(), AIMessage("done")), checkpointer=InMemorySaver())
    result = start(graph, profile="autonomous")
    assert (tmp_path / "b.txt").read_text() == "x"
    assert result["__interrupt__"][0].value["tool"] == "bash"
