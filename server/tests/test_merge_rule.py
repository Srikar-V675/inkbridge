"""The element merge rule and N1 (INK-111, decision 0080). The rule table is shared with the web."""

import itertools
import json
from pathlib import Path

import pytest

from inkbridge.db import elements

TABLE = json.loads((Path(__file__).parent / "data" / "merge_rules.json").read_text())


@pytest.mark.parametrize("row", TABLE, ids=[r["name"] for r in TABLE])
def test_rule_table(row):
    i, c = row["incoming"], row["current"]
    got = elements.wins(
        elements._int(i["version"]),
        elements._int(i["nonce"]),
        elements._int(c["version"]),
        elements._int(c["nonce"]),
    )
    assert got is row["wins"]


def _stamp(side):
    return elements._int(side["version"]), elements._int(side["nonce"])


def test_rule_is_antisymmetric_except_full_ties():
    sides = [r[k] for r in TABLE for k in ("incoming", "current")]
    checked = 0
    for a, b in itertools.permutations(sides, 2):
        if _stamp(a) == _stamp(b):
            continue
        ab, ba = elements.wins(*_stamp(a), *_stamp(b)), elements.wins(*_stamp(b), *_stamp(a))
        assert ab != ba, (a, b)
        checked += 1
    assert checked > 10


def test_equal_stamps_never_win_either_way():
    assert elements.wins(3, 4, 3, 4) is False


def test_n1_refuses_draft_flagged_element():
    el = {"id": "a", "customData": {"draft": True, "op_id": "o1"}}
    assert elements.n1_violations([el], set()) == ["a"]


def test_n1_refuses_new_op_prefixed_id():
    assert elements.n1_violations([{"id": "op1:0"}], set()) == ["op1:0"]


def test_n1_allows_existing_op_prefixed_id():
    assert elements.n1_violations([{"id": "op1:0"}], {"op1:0"}) == []


def test_n1_refuses_a_draft_even_when_its_row_exists():
    el = {"id": "op1:0", "customData": {"draft": True}}
    assert elements.n1_violations([el], {"op1:0"}) == ["op1:0"]


def test_n1_ignores_non_dict_custom_data():
    assert elements.n1_violations([{"id": "a", "customData": "draft"}], set()) == []
    assert elements.n1_violations([{"id": "a", "customData": None}], set()) == []
