"""The eval set: (profile, tool, args) -> expected decision. No model in the loop."""

import pytest

from approval_loop.policy import DECLINE_SUPPRESS_SECONDS, Rules, decide, fingerprint
from approval_loop.scenarios.dev import SCENARIO as DEV
from approval_loop.scenarios.nutrishop import SCENARIO as SHOP
from approval_loop.state import Approval

NOW = 1_000_000.0


def verdict(profile, tool, args, approvals=(), now=NOW, rules=DEV.rules):
    return decide(tool, args, profile, list(approvals), now, rules)["verdict"]


# --- must card, profile normal --------------------------------------------------
@pytest.mark.parametrize("command", [
    "rm -rf build",
    'find . -name "*.log" -delete',
    "ls | xargs rm",
    "git push --force origin main",
])
def test_normal_bash_floor_asks(command):
    assert verdict("normal", "bash", {"command": command}) == "ask"


def test_normal_write_file_asks():
    assert verdict("normal", "write_file", {"path": "src/index.ts", "content": "..."}) == "ask"


# --- must not card, profile normal -----------------------------------------------
@pytest.mark.parametrize("command", [
    "git rm --cached notes.txt",  # the git rm exclusion
    "ls -la && cat README.md",
])
def test_normal_bash_benign_allows(command):
    assert verdict("normal", "bash", {"command": command}) == "allow"


def test_normal_read_file_allows():
    assert verdict("normal", "read_file", {"path": "src/index.ts"}) == "allow"


# --- profile autonomous --------------------------------------------------------------
def test_autonomous_write_file_allows():
    assert verdict("autonomous", "write_file", {"path": "a.txt", "content": "x"}) == "allow"


def test_autonomous_floor_still_asks():
    assert verdict("autonomous", "bash", {"command": "rm -rf build"}) == "ask"


# --- fingerprints --------------------------------------------------------------------
def approved(tool, args, at=NOW - 5):
    return Approval(fingerprint=fingerprint(tool, args), verdict="approved", at=at, reason=None)


def denied(tool, args, at, reason=None):
    return Approval(fingerprint=fingerprint(tool, args), verdict="denied", at=at, reason=reason)


def test_same_args_after_approval_allow():
    args = {"path": "a.txt", "content": "x"}
    assert verdict("normal", "write_file", args, [approved("write_file", args)]) == "allow"


def test_different_args_after_approval_ask():
    assert verdict("normal", "write_file", {"path": "b.txt", "content": "x"},
                   [approved("write_file", {"path": "a.txt", "content": "x"})]) == "ask"


def test_fingerprint_ignores_key_order():
    assert fingerprint("t", {"a": 1, "b": 2}) == fingerprint("t", {"b": 2, "a": 1})


def test_recent_denial_is_suppressed_with_machine_reason():
    args = {"command": "rm -rf build"}
    d = decide("bash", args, "normal", [denied("bash", args, NOW - 40, "keep the cache")], NOW, DEV.rules)
    assert d["verdict"] == "deny"
    assert d["reason"] == "suppressed: declined 40s ago (keep the cache)"


def test_stale_denial_asks_again():
    args = {"command": "rm -rf build"}
    assert verdict("normal", "bash", args, [denied("bash", args, NOW - DECLINE_SUPPRESS_SECONDS - 1)]) == "ask"


# --- the floor's edges ---------------------------------------------------------------
@pytest.mark.parametrize("command", [
    "echo ok; rm -r build",                     # hidden behind a separator
    "Remove-Item -Recurse -Force build",        # PowerShell
    "powershell -Command \"Remove-Item -Rec 'C:\\x'\"",
    "rd /s /q build",
    "del /s *.log",
    "git reset --hard HEAD~1",
    "find build -exec rm {} +",
    "dd if=/dev/zero of=/dev/sda",
])
def test_floor_hits(command):
    assert verdict("autonomous", "bash", {"command": command}) == "ask"


@pytest.mark.parametrize("command", [
    "git rm -r --cached vendor",   # staged removal, the index can undo it
    "find . -name '*.log'",        # a find that lists
    "ls | xargs wc -l",            # an xargs that counts
    "rm notes.txt",                # one file, not a tree
    "git push origin main",
])
def test_floor_misses(command):
    assert verdict("autonomous", "bash", {"command": command}) == "allow"


def test_action_table_reclassifies_a_family_tool():
    rules = Rules(actions={"protocol": {"delete": "deletes a saved protocol"}})
    assert verdict("autonomous", "protocol", {"action": "delete", "name": "x"}, rules=rules) == "ask"
    assert verdict("autonomous", "protocol", {"action": "list"}, rules=rules) == "allow"


# --- the NutriShop scenario: same policy, business tools -------------------------------
def test_shop_reading_stock_is_free():
    assert verdict("normal", "read_inventory", {}, rules=SHOP.rules) == "allow"
    assert verdict("normal", "find_low_stock", {}, rules=SHOP.rules) == "allow"


def test_shop_draft_is_gated_by_profile():
    args = {"supplier": "Optimum", "lines": [{"sku": "WHEY-CHOC-5LB", "qty": 12}]}
    assert verdict("normal", "draft_purchase_order", args, rules=SHOP.rules) == "ask"
    assert verdict("autonomous", "draft_purchase_order", args, rules=SHOP.rules) == "allow"


def test_shop_sending_money_always_cards():
    d = decide("send_purchase_order", {"po_id": "PO-1"}, "autonomous", [], NOW, SHOP.rules)
    assert d["verdict"] == "ask"
    assert d["reason"] == "irreversible: commits the store to paying the supplier"


def test_shop_approving_one_po_does_not_approve_another():
    prior = [approved("send_purchase_order", {"po_id": "PO-1"})]
    assert verdict("normal", "send_purchase_order", {"po_id": "PO-1"}, prior, rules=SHOP.rules) == "allow"
    assert verdict("normal", "send_purchase_order", {"po_id": "PO-2"}, prior, rules=SHOP.rules) == "ask"