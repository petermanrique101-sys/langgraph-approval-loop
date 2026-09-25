"""Does prompt caching kick in on the NutriShop restock? One run per model.

    python evals/cache_test.py anthropic:claude-sonnet-5 anthropic:claude-haiku-4-5

Puts a cache breakpoint on the system prompt (Anthropic caches tools + system
up to that point), runs the same restock as compare_models.py, and prints what
the API reports per model call: plain input, cache writes, cache reads.
Product code is untouched; the breakpoint is patched in for this script only.
"""

import os
import sys
import tempfile
from pathlib import Path

PRICES = {"claude-sonnet-5": (2.0, 10.0), "claude-haiku-4-5": (1.0, 5.0)}
GHOST_REASON = "Ghost raised prices last month, hold that one until I call them"


def cached_system(text):
    from langchain_core.messages import SystemMessage
    return SystemMessage(content=[{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}])


def run(model_id: str) -> None:
    os.environ["WORKSPACE"] = tempfile.mkdtemp()
    for mod in [m for m in sys.modules if m.startswith("approval_loop")]:
        del sys.modules[mod]
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    import approval_loop.graph as graph_mod
    from approval_loop.scenarios import load

    graph_mod.SystemMessage = cached_system
    graph = graph_mod.build_graph(model=init_chat_model(model_id), checkpointer=InMemorySaver(), scenario=load("nutrishop"))
    short = model_id.split(":")[-1]
    cfg = {"configurable": {"thread_id": f"cache-{short}"}, "run_name": f"nutrishop-cache-{short}", "tags": ["cache-test", short]}
    result = graph.invoke({"messages": [HumanMessage("restock whatever is low")], "profile": "autonomous",
                           "pending": [], "approvals": []}, cfg)
    while "__interrupt__" in result:
        q = result["__interrupt__"][0].value["question"]
        result = graph.invoke(Command(resume=f"no, {GHOST_REASON}" if "Ghost" in q else "yes"), cfg)

    pin, pout = PRICES[short]
    total_plain = total_write = total_read = total_out = 0
    print(f"\n{model_id}")
    for i, m in enumerate([m for m in result["messages"] if isinstance(m, AIMessage)], 1):
        u = m.usage_metadata or {}
        d = u.get("input_token_details", {}) or {}
        write, read = d.get("cache_creation", 0) or 0, d.get("cache_read", 0) or 0
        plain = u.get("input_tokens", 0) - write - read
        total_plain, total_write, total_read, total_out = total_plain + plain, total_write + write, total_read + read, total_out + u.get("output_tokens", 0)
        print(f"  call {i}: plain in {plain}, cache write {write}, cache read {read}, out {u.get('output_tokens', 0)}")
    cached_cost = (total_plain + total_write * 1.25 + total_read * 0.1) * pin / 1e6 + total_out * pout / 1e6
    uncached_cost = (total_plain + total_write + total_read) * pin / 1e6 + total_out * pout / 1e6
    print(f"  total: plain {total_plain}, write {total_write}, read {total_read}, out {total_out}")
    print(f"  cost with caching ${cached_cost:.4f} vs same tokens uncached ${uncached_cost:.4f}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    for model_id in sys.argv[1:]:
        run(model_id)
