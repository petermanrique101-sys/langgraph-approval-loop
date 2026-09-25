"""CLI: start a task on a thread, or resume one that is waiting at an approval.

  python run.py --thread demo1 "clean the build directory"
  python run.py --thread demo1 --resume
  python run.py --scenario nutrishop --thread reorder1 "restock whatever is low"
"""

import argparse
import json
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from approval_loop.graph import build_graph
from approval_loop.scenarios import load

DB = Path(__file__).resolve().parent / "checkpoints.db"


def print_card(card: dict) -> None:
    print("\n=== APPROVAL NEEDED ===")
    print(f"tool:        {card['tool']}")
    print(f"args:        {json.dumps(card['args'])}")
    print(f"reason:      {card['reason']}")
    print(f"fingerprint: {card['fingerprint'][:16]}…")
    print("(Ctrl-C now: the graph is checkpointed at this interrupt; --resume picks it up here)")


def ask_human() -> dict:
    answer = input("approve? [y/N] ").strip().lower()
    if answer == "y":
        return {"approved": True}
    reason = input("reason (optional): ").strip()
    return {"approved": False, "reason": reason or None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--thread", required=True)
    ap.add_argument("--profile", choices=["normal", "autonomous"], default="normal")
    ap.add_argument("--scenario", choices=["dev", "nutrishop"], default="dev")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("prompt", nargs="?")
    args = ap.parse_args()
    config = {"configurable": {"thread_id": args.thread}}

    with SqliteSaver.from_conn_string(str(DB)) as checkpointer:
        graph = build_graph(checkpointer=checkpointer, scenario=load(args.scenario))

        if args.resume:
            snapshot = graph.get_state(config)
            pending = [i for task in snapshot.tasks for i in task.interrupts]
            if not pending:
                print(f"thread {args.thread!r} is not waiting at an interrupt (next={snapshot.next})")
                return 1
            print(f"resumed thread {args.thread!r} from its checkpoint")
            print_card(pending[0].value)
            result = graph.invoke(Command(resume=ask_human()), config)
        else:
            if not args.prompt:
                ap.error("a prompt is required unless --resume")
            result = graph.invoke(
                {"messages": [HumanMessage(args.prompt)], "profile": args.profile, "pending": [], "approvals": []},
                config,
            )

        while "__interrupt__" in result:
            print_card(result["__interrupt__"][0].value)
            result = graph.invoke(Command(resume=ask_human()), config)

    print("\n=== DONE ===")
    print(result["messages"][-1].content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
