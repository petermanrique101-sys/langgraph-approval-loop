"""The coding-assistant scenario: read, write, shell."""

from ..policy import Rules
from ..tools import bash, read_file, write_file
from . import Scenario

SCENARIO = Scenario(
    name="dev",
    system_prompt=(
        "You are a careful coding assistant working inside a sandboxed workspace. "
        "Use the tools to do what the user asks. Some tool calls need the user's approval; "
        "if one is denied, read the reason in the tool result and adapt instead of retrying it."
    ),
    tools=[read_file, write_file, bash],
    rules=Rules(
        gated={"write_file": "writes a file"},
        shell=frozenset({"bash"}),
    ),
)
