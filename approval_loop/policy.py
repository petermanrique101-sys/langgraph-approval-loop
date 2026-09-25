"""The policy node's brain: a pure function of (tool, args, profile, approvals, now).

No I/O, no model, no clock reads. The graph passes `now` in so the decision
is replayable, which is also what makes it testable without a model.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field

from .state import Approval, Decision, Profile

# --- 4.1 Shell-text floor -----------------------------------------------------
#
# Commands that destroy work with no recovery. A hit reclassifies the call to
# `ask` regardless of profile. Each pattern stops at a command separator
# (`[^|;&]*`) and the command is also split on separators before scanning, so
# a harmless leading command cannot hide a destructive one behind a pipe.
#
# Regexes over segments, with tests. Not a quote-aware lexer: the runtime this
# is ported from migrated one detector to a lexer and silently lost coverage.
_FLOOR: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.I), reason)
    for p, reason in [
        (r"\bgit\s+push\b[^|;&]*\s(?:--force\b|--force-with-lease\b|-\w*f\w*\b)", "git force-push"),
        (r"\bgit\s+push\b[^|;&]*\s(?:--delete\b|:\S)", "git delete remote branch"),
        (r"\bgit\s+reset\b[^|;&]*--hard\b", "git reset --hard"),
        (r"\bgit\s+clean\b[^|;&]*-\w*f\w*", "git clean -f"),
        (r"\bgit\s+branch\b[^|;&]*\s-D\b", "git force-delete branch"),
        (r"\bgit\s+filter-branch\b", "git history rewrite"),
        (r"\bgit\s+checkout\s+--\s+\.", "git checkout -- . (discards every unstaged edit)"),
        (r"\brm\s+-\w*r\w*f\w*\b", "rm -rf"),
        (r"\brm\s+-\w*f\w*r\w*\b", "rm -fr"),
        (r"\brm\s+-[rf]\b[^|;&]*\s-[rf]\b", "rm -r -f"),
        # PowerShell aliases of Remove-Item take -Recurse (abbreviable to -Rec).
        (r"\b(?:rm|ri|rmdir|rd|del|erase)\b[^|;&]*\s-rec\w*\b", "Remove-Item -Recurse (alias)"),
        # `rm -r` without -f is exactly as unrecoverable. `git rm -r` is a
        # staged removal the index can undo, so it is excluded.
        (r"(?<!git\s)\brm\b[^|;&]*\s(?:-\w*r\w*|--recursive)\b", "rm -r"),
        # A recursive wipe by composition: find deleting, find handing files
        # to rm, or rm fed by xargs. A find that lists is not a delete.
        (r"\bfind\b[^|;&]*\s-delete\b", "find -delete"),
        (r"\bfind\b[^|;&]*\s-(?:exec|execdir|ok|okdir)\s+(?:rm|unlink|rmdir)\b", "find -exec rm"),
        (r"\bxargs\b[^|;&]*\s(?:rm|unlink|rmdir)\b", "xargs rm"),
        (r"\bdd\b[^|;&]*\sof=", "dd of="),
        (r"\bmkfs\b", "filesystem format"),
        # Native Windows deletes. Remove-Item -Recurse deletes a tree without
        # prompting; rd /s and del /s are the tree forms (/q only silences).
        (r"\bRemove-Item\b[^|;&]*\s-r(?:ec\w*)?\b", "Remove-Item -Recurse"),
        (r"\b(?:rd|rmdir)\b(?:\s+/\w+)*\s+/s\b", "rd /s"),
        (r"\b(?:del|erase)\b(?:\s+/\w+)*\s+/s\b", "del /s"),
    ]
]

_SEPARATORS = re.compile(r"\|\|?|&&|;|&")


def destructive_shell_reason(command: str) -> str | None:
    """The reason a shell command is on the irreversible floor, or None."""
    for segment in _SEPARATORS.split(command):
        for pattern, reason in _FLOOR:
            if pattern.search(segment):
                return reason
    return None


# --- 4.2 What is gated, per scenario -------------------------------------------
#
# The graph is the same for every scenario; only this table changes. That is
# the point of the port: the framework supplies interrupt() and persistence,
# the customer-specific part is which calls are risky and why.
@dataclass(frozen=True)
class Rules:
    # Gated as a whole: `ask` under the normal profile, `allow` under autonomous.
    gated: dict[str, str] = field(default_factory=dict)
    # Irreversible regardless of profile: money leaves, data is gone, a message
    # is sent. Always `ask` (an explicit approval of the exact args is honored).
    irreversible: dict[str, str] = field(default_factory=dict)
    # Tools whose `command` string is scanned against the shell-text floor.
    shell: frozenset[str] = frozenset()
    # Family tools whose risk varies per `action` argument. A family's static
    # tier is its worst NON-destructive action; the destructive actions are
    # listed here so collapsing a family into one tool never weakens its gate.
    actions: dict[str, dict[str, str]] = field(default_factory=dict)


# --- 4.3 Profile and fingerprints ---------------------------------------------

# How long a denial suppresses an IDENTICAL re-issue. Long enough to collapse a
# retry storm, short enough that a deliberate re-request still gets a card.
DECLINE_SUPPRESS_SECONDS = 60.0


def fingerprint(tool_name: str, args: dict) -> str:
    """sha256 over the tool name and the canonical JSON of its args.

    Different args, different fingerprint: approving one command never
    approves a different one.
    """
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{tool_name}\n{canonical}".encode()).hexdigest()


def decide(
    tool_name: str,
    args: dict,
    profile: Profile,
    approvals: list[Approval],
    now: float,
    rules: Rules,
) -> Decision:
    fp = fingerprint(tool_name, args)

    # The irreversible floor sits above the profile: a shell command that
    # destroys a tree, a tool that sends money, a destructive family action.
    floor: str | None = None
    if tool_name in rules.shell:
        hit = destructive_shell_reason(str(args.get("command", "")))
        floor = f"irreversible: {hit}" if hit else None
    if floor is None and tool_name in rules.irreversible:
        floor = f"irreversible: {rules.irreversible[tool_name]}"
    if floor is None:
        action = rules.actions.get(tool_name, {}).get(str(args.get("action", "")))
        floor = f"destructive action: {action}" if action else None
    gated_reason = rules.gated.get(tool_name)

    if floor is None and gated_reason is None:
        return Decision(verdict="allow", reason="not gated", fingerprint=fp)

    # Prior verdicts on these exact args, newest first.
    for prior in reversed(approvals):
        if prior["fingerprint"] != fp:
            continue
        if prior["verdict"] == "approved":
            return Decision(verdict="allow", reason="approved earlier in this thread", fingerprint=fp)
        age = now - prior["at"]
        if age < DECLINE_SUPPRESS_SECONDS:
            return Decision(
                verdict="deny",
                reason=f"suppressed: declined {age:.0f}s ago" + (f" ({prior['reason']})" if prior["reason"] else ""),
                fingerprint=fp,
            )
        break  # a stale denial; ask again

    if floor is not None:
        return Decision(verdict="ask", reason=floor, fingerprint=fp)
    if profile == "autonomous":
        return Decision(verdict="allow", reason="autonomous profile", fingerprint=fp)
    return Decision(verdict="ask", reason=gated_reason, fingerprint=fp)
