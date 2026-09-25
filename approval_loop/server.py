"""Graphs for `langgraph dev` (Studio and Agent Chat UI). The server supplies
the checkpointer, so these are compiled without one. Absolute imports: the
server loads this file by path, not as part of the package."""

from approval_loop.graph import build_graph
from approval_loop.scenarios import load

dev = build_graph(scenario=load("dev"))
nutrishop = build_graph(scenario=load("nutrishop"))
