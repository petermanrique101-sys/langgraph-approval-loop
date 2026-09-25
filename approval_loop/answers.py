"""Turn whatever the owner typed at a card into {"approved": bool, "reason": str | None}.

Accepts the structured form ({"approved": true}), a boolean (Studio's YAML box
parses a bare `yes` / `no` into one), or plain words: "yes", "no",
"no, Ghost raised prices". Anything that is not a clear yes is a denial, with
the text kept as the reason: an unclear answer must never send money.
"""

import re

_YES = ["yes", "yeah", "yep", "y", "ok", "okay", "sure", "approve", "approved", "go ahead", "send it", "do it", "true"]
_NO = ["no", "nope", "n", "deny", "denied", "hold", "stop", "false"]
# Longest phrase first so "send it" wins over a shorter prefix.
_PHRASES = sorted([(p, True) for p in _YES] + [(p, False) for p in _NO], key=lambda x: -len(x[0]))
_LEADING_PUNCT = re.compile(r"^[\s,:;.!\-–—]+")


def parse_answer(answer) -> dict:
    if isinstance(answer, dict) and "approved" in answer:
        return {"approved": bool(answer["approved"]), "reason": answer.get("reason") or None}
    if isinstance(answer, bool):
        return {"approved": answer, "reason": None}
    text = str(answer or "").strip().strip('"').strip()
    if not text:
        return {"approved": False, "reason": None}
    lower = text.lower()
    for phrase, approved in _PHRASES:
        if lower.startswith(phrase) and (len(lower) == len(phrase) or not lower[len(phrase)].isalnum()):
            rest = _LEADING_PUNCT.sub("", text[len(phrase):]).strip()
            return {"approved": approved, "reason": rest or None}
    return {"approved": False, "reason": text}
