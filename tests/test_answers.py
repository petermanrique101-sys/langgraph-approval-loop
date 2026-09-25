"""Plain answers at a card. Anything that is not a clear yes is a no."""

import pytest

from approval_loop.answers import parse_answer


@pytest.mark.parametrize("answer, expected", [
    ({"approved": True}, {"approved": True, "reason": None}),
    ({"approved": False, "reason": "later"}, {"approved": False, "reason": "later"}),
    (True, {"approved": True, "reason": None}),   # Studio YAML: bare `yes`
    (False, {"approved": False, "reason": None}),  # Studio YAML: bare `no`
    ("yes", {"approved": True, "reason": None}),
    ("Y", {"approved": True, "reason": None}),
    ("send it", {"approved": True, "reason": None}),
    ("yes it's fine", {"approved": True, "reason": "it's fine"}),
    ("no", {"approved": False, "reason": None}),
    ("no, Ghost raised prices last month", {"approved": False, "reason": "Ghost raised prices last month"}),
    ("No - wait for Friday", {"approved": False, "reason": "wait for Friday"}),
    ('"yes"', {"approved": True, "reason": None}),
    ("", {"approved": False, "reason": None}),
    ("nothing yet", {"approved": False, "reason": "nothing yet"}),  # "no" prefix inside a word is not a no-word match
    ("maybe tomorrow", {"approved": False, "reason": "maybe tomorrow"}),
    ("yesterday's price was better", {"approved": False, "reason": "yesterday's price was better"}),
])
def test_parse_answer(answer, expected):
    assert parse_answer(answer) == expected
