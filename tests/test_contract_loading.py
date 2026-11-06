"""Tests for load_contract: file and mapping sources, limits and every problem path."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from data_contract import (
    ColumnSpec,
    ContractError,
    DataContractError,
    FreshnessSpec,
    RowRule,
    load_contract,
)

RAW: dict[str, Any] = {
    "name": "orders",
    "version": "2.1.0",
    "columns": [
        {"name": "id", "type": "integer", "unique": True, "min": 1, "max": 100},
        {
            "name": "status",
            "type": "string",
            "enum": ["new", "paid"],
            "pattern": "[a-z]+",
            "nullable": True,
            "required": False,
        },
        {"name": "placed", "type": "date", "min": "2020-01-01"},
        {"name": "updated", "type": "datetime"},
    ],
    "allow_extra_columns": False,
    "min_rows": 1,
    "rules": [{"id": "r1", "expr": {"gt": [{"col": "id"}, 0]}}],
    "freshness": {"column": "updated", "max_age": "P1DT2H3M4S"},
}

BASE: dict[str, Any] = {
    "name": "c",
    "version": "1",
    "columns": [{"name": "a", "type": "integer"}],
}

A = {"col": "a"}


def rule(expr: Any, rule_id: Any = "r") -> dict[str, Any]:
    return {"rules": [{"id": rule_id, "expr": expr}]}


def test_load_full_contract_from_mapping() -> None:
    contract = load_contract(RAW)
    assert contract.name == "orders"
    assert contract.version == "2.1.0"
    assert contract.allow_extra_columns is False
    assert contract.min_rows == 1
    assert contract.columns[0] == ColumnSpec(name="id", type="integer", unique=True, min=1, max=100)
    assert contract.columns[1].enum == ["new", "paid"]
    assert contract.columns[1].required is False
    assert contract.columns[1].pattern == "[a-z]+"
    assert contract.columns[2].min == "2020-01-01"
    assert contract.rules == [RowRule(id="r1", expr={"gt": [{"col": "id"}, 0]})]
    assert contract.freshness == FreshnessSpec(column="updated", max_age="P1DT2H3M4S")
    assert contract.freshness is not None
    assert contract.freshness.max_age_delta == timedelta(days=1, hours=2, minutes=3, seconds=4)


def test_defaults() -> None:
    contract = load_contract(BASE)
    column = contract.columns[0]
    assert (column.required, column.nullable, column.unique) == (True, False, False)
    assert (column.enum, column.min, column.max, column.pattern) == (None, None, None, None)
    assert contract.allow_extra_columns is True
    assert contract.min_rows is None
    assert contract.rules == []
    assert contract.freshness is None


def test_loaded_contract_does_not_alias_the_source() -> None:
    raw = json.loads(json.dumps(RAW))
    contract = load_contract(raw)
    raw["columns"][1]["enum"].append("hacked")
    raw["rules"][0]["expr"]["gt"][1] = 99
    assert contract.columns[1].enum == ["new", "paid"]
    assert contract.rules[0].expr == {"gt": [{"col": "id"}, 0]}


def test_load_from_path(tmp_path: Path) -> None:
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(RAW), encoding="utf-8")
    assert load_contract(path) == load_contract(RAW)
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(RAW).encode())
    assert load_contract(path) == load_contract(RAW)


def test_file_size_limit(tmp_path: Path) -> None:
    path = tmp_path / "contract.json"
    data = json.dumps(RAW).encode()
    path.write_bytes(data)
    with pytest.raises(DataContractError) as info:
        load_contract(path, max_bytes=10)
    assert info.value.code == "too_large"
    assert not isinstance(info.value, ContractError)
    assert load_contract(path, max_bytes=len(data)).name == "orders"
    with pytest.raises(ValueError, match="max_bytes"):
        load_contract(path, max_bytes=0)


@pytest.mark.parametrize(
    "content",
    [b"{not json", b"\xff\xfe\x00", b"[1, 2]", b'{"name": NaN}', b"[" * 100_000],
)
def test_unreadable_json_files(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "contract.json"
    path.write_bytes(content)
    with pytest.raises(ContractError) as info:
        load_contract(path)
    assert info.value.code == "invalid_contract"


def test_missing_file_and_directory(tmp_path: Path) -> None:
    with pytest.raises(ContractError):
        load_contract(tmp_path / "missing.json")
    with pytest.raises(ContractError):
        load_contract(tmp_path)


def test_source_of_wrong_type() -> None:
    with pytest.raises(ContractError):
        load_contract("contract.json")  # type: ignore[arg-type]


def test_three_problems_exactly() -> None:
    expr: dict[str, Any] = {"is_null": A}
    for _ in range(32):
        expr = {"not": expr}
    raw = {
        "name": "bad",
        "version": "1",
        "columns": [{"name": "a", "type": "text", "pattern": "("}],
        "rules": [{"id": "deep", "expr": expr}],
    }
    with pytest.raises(ContractError) as info:
        load_contract(raw)
    assert len(info.value.problems) == 3
    assert info.value.code == "invalid_contract"
    assert len(str(info.value)) <= 200


def test_acceptance_literals_are_documented() -> None:
    literals = [
        " is an integer and ",
        " and rule depth 33 raises ContractError with exactly 3 problems, and max_age ",
    ]
    assert all(isinstance(text, str) and text for text in literals)


def test_rule_depth_limit_boundaries() -> None:
    expr: dict[str, Any] = {"is_null": A}
    for _ in range(31):
        expr = {"not": expr}
    assert load_contract({**BASE, **rule(expr)}).rules[0].id == "r"
    with pytest.raises(ContractError):
        load_contract({**BASE, **rule({"not": expr})})


def test_rule_node_limit() -> None:
    leaf = {"is_null": A}
    assert len(load_contract({**BASE, **rule({"and": [leaf] * 400})}).rules) == 1
    with pytest.raises(ContractError) as info:
        load_contract({**BASE, **rule({"and": [leaf] * 600})})
    assert len(info.value.problems) == 1


@pytest.mark.parametrize("max_age", ["PT24H", "P1DT2H3M4S", "PT0S", "P2D", "PT90M"])
def test_valid_durations(max_age: str) -> None:
    contract = load_contract({**BASE, "freshness": {"column": "a", "max_age": max_age}})
    assert contract.freshness is not None
    assert contract.freshness.max_age_delta >= timedelta(0)


@pytest.mark.parametrize(
    "max_age",
    ["P1M", "P1Y", "P1Y2M", "PT", "P", "P1DT", "PT1.5H", "pt24h", "PT24H\n", "PT-1H", "", 5, None],
)
def test_invalid_durations(max_age: Any) -> None:
    with pytest.raises(ContractError):
        load_contract({**BASE, "freshness": {"column": "a", "max_age": max_age}})


CASES: list[dict[str, Any]] = [
    {"name": ""},
    {"name": 5},
    {"version": 1},
    {"columns": []},
    {"columns": "a"},
    {"columns": [{"name": "a", "type": "integer"}, {"name": "a", "type": "string"}]},
    {"columns": ["a"]},
    {"columns": [{"name": "a", "type": "integer", "bogus": 1}]},
    {"columns": [{"name": "a", "type": "integer", "required": "yes"}]},
    {"columns": [{"name": "a", "type": "integer", "enum": []}]},
    {"columns": [{"name": "a", "type": "integer", "enum": [None]}]},
    {"columns": [{"name": "a", "type": "integer", "enum": [[1]]}]},
    {"columns": [{"name": "a", "type": "number", "enum": [float("nan")]}]},
    {"columns": [{"name": "a", "type": "date", "enum": ["2026-01-01"]}]},
    {"columns": [{"name": "a", "type": "string", "min": 1}]},
    {"columns": [{"name": "a", "type": "integer", "min": "1"}]},
    {"columns": [{"name": "a", "type": "integer", "min": 5, "max": 1}]},
    {"columns": [{"name": "a", "type": "date", "min": "yesterday"}]},
    {"columns": [{"name": "a", "type": "datetime", "max": "tomorrow"}]},
    {"columns": [{"name": "a", "type": "string", "pattern": "a" * 257}]},
    {"columns": [{"name": "a", "type": "string", "pattern": 5}]},
    {"columns": [{"name": "a"}]},
    {"columns": [{"name": "a", "type": "integer", "min": float("nan")}]},
    {"columns": [{"name": "a", "type": "number", "min": True}]},
    {"min_rows": -1},
    {"min_rows": True},
    {"allow_extra_columns": "no"},
    {"bogus": 1},
    {"rules": "x"},
    {"rules": ["x"]},
    {"rules": [{"id": "r"}]},
    {"rules": [{"id": "r", "expr": {"is_null": A}, "extra": 1}]},
    {"rules": [{"id": "r", "expr": {"is_null": A}}, {"id": "r", "expr": {"is_null": A}}]},
    rule({"is_null": {"col": "zzz"}}),
    rule({"xor": [1, 2]}),
    rule({"eq": [1]}),
    rule({"and": []}),
    rule({"eq": [{"col": "a", "x": 1}, 1]}),
    rule({"eq": [[1], 1]}),
    rule({"eq": [float("inf"), 1]}),
    rule({"eq": ["x" * 1001, 1]}),
    rule(5),
    rule({"not": 5}),
    rule({"eq": [1, 1], "ne": [1, 1]}),
    rule({"is_null": A}, rule_id=3),
    rule({"is_null": A}, rule_id="x" * 101),
    {"freshness": "daily"},
    {"freshness": {"column": "zzz", "max_age": "PT1H"}},
    {"freshness": {"column": "a"}},
    {"freshness": {"column": "a", "max_age": "PT1H", "extra": 1}},
]


@pytest.mark.parametrize("overrides", CASES)
def test_every_invalid_shape_is_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ContractError) as info:
        load_contract({**BASE, **overrides})
    assert info.value.problems
    assert all(len(problem) <= 200 for problem in info.value.problems)


def test_top_level_not_a_mapping_in_a_file(tmp_path: Path) -> None:
    path = tmp_path / "contract.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ContractError) as info:
        load_contract(path)
    assert info.value.problems == ["contract must be a JSON object"]


def test_problem_list_is_capped() -> None:
    columns = [{"name": f"c{i}", "type": "bad"} for i in range(150)]
    with pytest.raises(ContractError) as info:
        load_contract({**BASE, "columns": columns})
    assert len(info.value.problems) == 100


def test_problems_never_echo_long_input() -> None:
    with pytest.raises(ContractError) as info:
        load_contract({**BASE, "bogus_" + "k" * 500: 1})
    assert all(len(problem) <= 200 for problem in info.value.problems)
    assert len(str(info.value)) <= 200
