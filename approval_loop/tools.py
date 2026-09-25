"""Three tools. Every path is confined to WORKSPACE; bash runs with it as cwd."""

import os
import shutil
import subprocess
from pathlib import Path

from langchain.tools import tool

WORKSPACE = Path(os.environ.get("WORKSPACE", Path(__file__).resolve().parent.parent / "workspace")).resolve()
OUTPUT_LIMIT = 4000


def _confined(path: str) -> Path:
    resolved = (WORKSPACE / path).resolve()
    if resolved != WORKSPACE and WORKSPACE not in resolved.parents:
        raise ValueError(f"path escapes the workspace: {path}")
    return resolved


@tool
def read_file(path: str) -> str:
    """Read a UTF-8 text file. `path` is relative to the workspace."""
    return _confined(path).read_text(encoding="utf-8")[:OUTPUT_LIMIT]


@tool
def write_file(path: str, content: str) -> str:
    """Create or overwrite a UTF-8 text file. `path` is relative to the workspace."""
    target = _confined(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} chars to {path}"


@tool
def bash(command: str) -> str:
    """Run a shell command in the workspace and return its output."""
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    shell = shutil.which("bash")
    argv = [shell, "-c", command] if shell else command
    proc = subprocess.run(
        argv, shell=shell is None, cwd=WORKSPACE, capture_output=True, text=True, timeout=30
    )
    out = (proc.stdout + proc.stderr).strip()[:OUTPUT_LIMIT]
    return f"exit {proc.returncode}\n{out}" if out else f"exit {proc.returncode}"


TOOLS = [read_file, write_file, bash]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
