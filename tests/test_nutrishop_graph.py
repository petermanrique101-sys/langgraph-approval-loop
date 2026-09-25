"""The NutriShop scenario through the graph with a scripted model: the draft
passes under autonomous, the send cards, a denial's reason reaches the model."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import approval_loop.scenarios.nutrishop as shop
from approval_loop.graph import build_graph
from tests.test_graph import scripted

CONFIG = {"configurable": {"thread_id": "reorder1"}}


def _point_workspace_at(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(shop, "INVENTORY", tmp_path / "inventory.csv")
    monkeypatch.setattr(shop, "ORDERS", tmp_path / "orders")


def test_send_cards_after_autonomous_draft_and_denial_reason_lands(tmp_path, monkeypatch):
    _point_workspace_at(tmp_path, monkeypatch)
    draft = AIMessage(content="", tool_calls=[{
        "name": "draft_purchase_order", "id": "c1",
        "args": {"supplier": "Optimum", "lines": [{"sku": "WHEY-CHOC-5LB", "qty": 12}]},
    }])
    graph = build_graph(model=scripted(draft, AIMessage("drafted")), checkpointer=InMemorySaver(), scenario=shop.SCENARIO)
    result = graph.invoke({"messages": [HumanMessage("restock")], "profile": "autonomous", "pending": [], "approvals": []}, CONFIG)
    draft_msg = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert draft_msg.content.endswith("1 lines, total $528.00")
    po_id = draft_msg.content.split()[0]
    assert (tmp_path / "orders" / f"{po_id}.json").exists()
    assert "__interrupt__" not in result  # autonomous: the draft went through without a card

    send = AIMessage(content="", tool_calls=[{"name": "send_purchase_order", "id": "c2", "args": {"po_id": po_id}}])
    graph2 = build_graph(model=scripted(send, AIMessage("holding the order")),
                         checkpointer=graph.checkpointer, scenario=shop.SCENARIO)
    result = graph2.invoke({"messages": [HumanMessage("now send it")]}, CONFIG)
    card = result["__interrupt__"][0].value
    assert card["tool"] == "send_purchase_order"
    assert card["reason"] == "irreversible: commits the store to paying the supplier"

    final = graph2.invoke(Command(resume={"approved": False, "reason": "wait for Friday's cash"}), CONFIG)
    denial = [m for m in final["messages"] if isinstance(m, ToolMessage)][-1]
    assert denial.content == "Denied by the user: wait for Friday's cash"
    assert (tmp_path / "orders" / f"{po_id}.json").read_text().count('"status": "draft"') == 1
