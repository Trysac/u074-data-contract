"""End-to-end tests of load_contract and validate through the public API."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

import data_contract
from data_contract import (
    ColumnSpec,
    Contract,
    ContractError,
    DataContractError,
    FreshnessResult,
    FreshnessSpec,
    RowRule,
    ValidationReport,
    Violation,
    load_contract,
    validate,
)

NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)


def contract_of(columns: list[dict[str, Any]], **extra: Any) -> Contract:
    return load_contract({"name": "t", "version": "1", "columns": columns, **extra})


def shape(report: ValidationReport) -> list[tuple[str, str | None, int | None]]:
    return [(v.rule, v.column, v.row_index) for v in report.violations]


def test_version() -> None:
    assert data_contract.__version__ == "0.1.0"


def test_matching_dataset_passes() -> None:
    contract = contract_of(
        [
            {"name": "id", "type": "integer", "unique": True},
            {"name": "email", "type": "string"},
            {"name": "age", "type": "integer", "nullable": True, "min": 0, "max": 150},
        ]
    )
    rows = [
        {"id": 1, "email": "a@example.com", "age": 30},
        {"id": 2, "email": "b@example.com", "age": None},
        {"id": 3, "email": "c@example.com", "age": 0},
    ]
    report = validate(rows, contract, now=NOW)
    assert report.passed is True
    assert report.row_count == 3
    assert report.violations == []
    assert report.truncated is False
    assert report.freshness is None


def test_missing_required_column_yields_one_schema_violation() -> None:
    contract = contract_of([{"name": "id", "type": "integer"}, {"name": "email", "type": "string"}])
    report = validate([{"id": 1}, {"id": 2}], contract, now=NOW)
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation == Violation(
        rule="schema", column="email", row_index=None, message=violation.message
    )
    assert report.passed is False


def test_extra_column_with_allow_extra_columns_false() -> None:
    contract = contract_of(
        [{"name": "id", "type": "integer"}, {"name": "email", "type": "string"}],
        allow_extra_columns=False,
    )
    report = validate([{"id": 1, "debug": "x"}, {"id": 2, "debug": "y"}], contract, now=NOW)
    assert shape(report) == [("schema", "email", None), ("schema", "debug", None)]
    allowed = validate(
        [{"id": 1, "email": "e", "debug": 1}],
        contract_of([{"name": "id", "type": "integer"}, {"name": "email", "type": "string"}]),
        now=NOW,
    )
    assert allowed.passed is True


def test_extra_column_names_are_sanitized_and_deduplicated() -> None:
    contract = contract_of([{"name": "id", "type": "integer"}], allow_extra_columns=False)
    rows = [{"id": 1, "bad\nname": 1}, {"id": 2, "bad\nname": 2}]
    report = validate(rows, contract, now=NOW)
    assert len(report.violations) == 1
    assert "\n" not in report.violations[0].message
    assert report.violations[0].column == "bad\nname"


def test_extra_column_tracking_is_capped() -> None:
    contract = contract_of([{"name": "id", "type": "integer"}], allow_extra_columns=False)
    report = validate([{"id": 1, "a": 1, "b": 1, "c": 1}], contract, now=NOW, max_violations=2)
    assert len(report.violations) == 2
    assert report.truncated is True


def test_type_nullable_enum_range_pattern_failures() -> None:
    contract = contract_of(
        [
            {"name": "status", "type": "string", "enum": ["a", "b"]},
            {"name": "score", "type": "integer", "min": 0, "max": 10},
            {"name": "code", "type": "string", "pattern": "[A-Z]{3}"},
        ]
    )
    rows = [
        {"status": "zzz-secret", "score": 5, "code": "ABC"},
        {"status": "a", "score": 99, "code": "ABC"},
        {"status": "a", "score": 5, "code": "abc-secret"},
        {"status": "a", "score": "text-secret", "code": "ABC"},
        {"status": None, "score": 5, "code": "ABC"},
    ]
    report = validate(rows, contract, now=NOW)
    assert shape(report) == [
        ("enum", "status", 0),
        ("range", "score", 1),
        ("pattern", "code", 2),
        ("type", "score", 3),
        ("nullable", "status", 4),
    ]
    for violation in report.violations:
        assert "secret" not in violation.message
        assert "99" not in violation.message


def test_bool_and_float_are_not_integers_but_float_is_number() -> None:
    contract = contract_of([{"name": "i", "type": "integer"}, {"name": "n", "type": "number"}])
    rows = [
        {"i": True, "n": 1.0},
        {"i": 1.0, "n": True},
        {"i": 1, "n": 1.0},
        {"i": 1, "n": float("nan")},
        {"i": 1, "n": float("inf")},
        {"i": 1, "n": 7},
    ]
    report = validate(rows, contract, now=NOW)
    assert shape(report) == [
        ("type", "i", 0),
        ("type", "i", 1),
        ("type", "n", 1),
        ("type", "n", 3),
        ("type", "n", 4),
    ]


def test_python_date_and_datetime_types() -> None:
    contract = contract_of([{"name": "d", "type": "date"}, {"name": "t", "type": "datetime"}])
    ok = {"d": date(2026, 1, 1), "t": datetime(2026, 1, 1)}
    bad = {"d": datetime(2026, 1, 1), "t": date(2026, 1, 1)}
    report = validate([ok, bad], contract, now=NOW)
    assert shape(report) == [("type", "d", 1), ("type", "t", 1)]


@pytest.mark.parametrize(
    ("type_name", "text", "valid"),
    [
        ("integer", "42", True),
        ("integer", "+7", True),
        ("integer", "-0", True),
        ("integer", " 42", False),
        ("integer", "42.0", False),
        ("integer", "\u0664\u0662", False),
        ("integer", "42\n", False),
        ("integer", "", False),
        ("integer", "4 2", False),
        ("integer", "1" * 10_001, False),
        ("number", "1.5", True),
        ("number", "1e3", True),
        ("number", ".5", True),
        ("number", "5.", True),
        ("number", "nan", False),
        ("number", "inf", False),
        ("number", "1e999", False),
        ("number", "1_0", False),
        ("number", " 1", False),
        ("boolean", "true", True),
        ("boolean", "false", True),
        ("boolean", "True", False),
        ("boolean", "1", False),
        ("date", "2026-01-31", True),
        ("date", "2026-02-30", False),
        ("date", "20260131", False),
        ("date", "2026-01-31T00:00:00", False),
        ("datetime", "2026-01-01T00:00:00Z", True),
        ("datetime", "2026-01-01T00:00:00+02:00", True),
        ("datetime", "not a date", False),
        ("datetime", "\uff12\uff10\uff12\uff16-01-01T00:00:00", False),
        ("datetime", "2026-01-01T" + "0" * 80, False),
        ("string", "anything at all", True),
    ],
)
def test_coercion_of_strings(type_name: str, text: str, valid: bool) -> None:
    contract = contract_of([{"name": "v", "type": type_name}])
    report = validate([{"v": text}], contract, now=NOW, coerce=True)
    assert report.passed is valid


def test_without_coerce_strings_are_type_errors() -> None:
    contract = contract_of([{"name": "v", "type": "integer"}])
    assert validate([{"v": "42"}], contract, now=NOW).passed is False
    assert validate([{"v": "42"}], contract, now=NOW, coerce=True).passed is True
    assert validate([{"v": 42}], contract, now=NOW, coerce=True).passed is True
    assert validate([{"v": 4.5}], contract, now=NOW, coerce=True).passed is False


def test_coerced_values_feed_enum_range_and_unique() -> None:
    contract = contract_of(
        [{"name": "v", "type": "integer", "unique": True, "min": 1, "max": 5, "enum": [1, 2, 9]}]
    )
    report = validate(
        [{"v": "1"}, {"v": "1"}, {"v": "3"}, {"v": "9"}], contract, now=NOW, coerce=True
    )
    assert shape(report) == [
        ("unique", "v", 1),
        ("enum", "v", 2),
        ("range", "v", 3),
    ]


def test_unique_reports_second_occurrence() -> None:
    contract = contract_of([{"name": "id", "type": "integer", "unique": True}])
    report = validate([{"id": 1}, {"id": 2}, {"id": 1}], contract, now=NOW)
    assert shape(report) == [("unique", "id", 2)]


def test_unique_allows_repeated_nulls() -> None:
    contract = contract_of([{"name": "id", "type": "integer", "unique": True, "nullable": True}])
    report = validate([{"id": None}, {"id": None}, {"id": 1}], contract, now=NOW)
    assert report.passed is True


def test_unique_tracking_limit() -> None:
    contract = contract_of([{"name": "id", "type": "integer", "unique": True}])
    report = validate(
        [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 1}],
        contract,
        now=NOW,
        max_unique_values=2,
    )
    assert shape(report) == [("unique", "id", 2)]
    assert "limit reached" in report.violations[0].message


def test_enum_with_mixed_types_is_type_strict() -> None:
    mixed = contract_of([{"name": "v", "type": "integer", "enum": [1, "a", True]}])
    report = validate([{"v": 1}, {"v": 2}], mixed, now=NOW)
    assert shape(report) == [("enum", "v", 1)]
    boolean = contract_of([{"name": "v", "type": "boolean", "enum": [1]}])
    assert shape(validate([{"v": True}], boolean, now=NOW)) == [("enum", "v", 0)]
    floaty = contract_of([{"name": "v", "type": "integer", "enum": [1.0]}])
    assert validate([{"v": 1}], floaty, now=NOW).passed is True


def test_ranges_for_number_date_and_datetime() -> None:
    numbers = contract_of([{"name": "v", "type": "number", "min": 0.5, "max": 1.5}])
    rows: list[dict[str, Any]] = [{"v": x} for x in (0.4, 1.6, 1, 1.5, 0.5)]
    assert shape(validate(rows, numbers, now=NOW)) == [("range", "v", 0), ("range", "v", 1)]
    dates = contract_of([{"name": "d", "type": "date", "min": "2026-01-01", "max": "2026-12-31"}])
    date_rows = [{"d": date(2025, 12, 31)}, {"d": date(2027, 1, 1)}, {"d": date(2026, 6, 1)}]
    assert shape(validate(date_rows, dates, now=NOW)) == [("range", "d", 0), ("range", "d", 1)]
    stamps = contract_of([{"name": "t", "type": "datetime", "min": "2026-01-01T00:00:00Z"}])
    stamp_rows = [{"t": datetime(2025, 12, 31)}, {"t": datetime(2026, 1, 1, tzinfo=timezone.utc)}]
    assert shape(validate(stamp_rows, stamps, now=NOW)) == [("range", "t", 0)]


def test_pattern_uses_fullmatch_and_length_limit() -> None:
    contract = contract_of([{"name": "s", "type": "string", "pattern": "[a-z]+"}])
    values = ["ab", "abc1", "abc\n", "a" * 10_001, "a" * 10_000]
    report = validate([{"s": v} for v in values], contract, now=NOW)
    assert shape(report) == [("pattern", "s", 1), ("pattern", "s", 2), ("pattern", "s", 3)]
    non_string = contract_of([{"name": "n", "type": "integer", "pattern": "[0-9]"}])
    assert validate([{"n": 55}], non_string, now=NOW).passed is True


DATE_COLUMNS = [
    {"name": "start_date", "type": "date"},
    {"name": "end_date", "type": "date", "nullable": True},
]


def test_row_rule_lte_and_null_semantics() -> None:
    rule = {"id": "dates_ordered", "expr": {"lte": [{"col": "start_date"}, {"col": "end_date"}]}}
    contract = contract_of(DATE_COLUMNS, rules=[rule])
    rows = [
        {"start_date": date(2026, 1, 1), "end_date": date(2026, 1, 2)},
        {"start_date": date(2026, 1, 5), "end_date": date(2026, 1, 2)},
        {"start_date": date(2026, 1, 5), "end_date": None},
    ]
    report = validate(rows, contract, now=NOW)
    assert shape(report) == [("row_rule", None, 1)]
    assert "dates_ordered" in report.violations[0].message
    catcher = {"id": "end_required", "expr": {"not": {"is_null": {"col": "end_date"}}}}
    both = contract_of(DATE_COLUMNS, rules=[rule, catcher])
    report = validate(rows, both, now=NOW)
    assert shape(report) == [("row_rule", None, 1), ("row_rule", None, 2)]
    assert "end_required" in report.violations[1].message


A = {"col": "a"}
B = {"col": "b"}
INT_COLUMNS = [
    {"name": "a", "type": "integer", "nullable": True},
    {"name": "b", "type": "integer", "nullable": True},
]


def rule_rows(expr: dict[str, Any], a: Any, b: Any) -> list[int | None]:
    contract = contract_of(INT_COLUMNS, rules=[{"id": "r1", "expr": expr}])
    report = validate([{"a": a, "b": b}], contract, now=NOW)
    return [v.row_index for v in report.violations if v.rule == "row_rule"]


@pytest.mark.parametrize(
    ("op", "a", "b", "flagged"),
    [
        ("eq", 1, 1, False),
        ("eq", 1, 2, True),
        ("eq", None, 1, False),
        ("ne", 1, 2, False),
        ("ne", 1, 1, True),
        ("lt", 1, 2, False),
        ("lt", 2, 2, True),
        ("lt", 3, 2, True),
        ("lte", 2, 2, False),
        ("lte", 3, 2, True),
        ("gt", 3, 2, False),
        ("gt", 2, 2, True),
        ("gte", 2, 2, False),
        ("gte", 1, 2, True),
    ],
)
def test_comparison_operators(op: str, a: Any, b: Any, flagged: bool) -> None:
    assert (rule_rows({op: [A, B]}, a, b) == [0]) is flagged


AND = {"and": [{"eq": [A, 1]}, {"eq": [B, 1]}]}
OR = {"or": [{"eq": [A, 1]}, {"eq": [B, 1]}]}


@pytest.mark.parametrize(
    ("expr", "a", "b", "flagged"),
    [
        (AND, 2, None, True),
        (AND, 1, None, False),
        (AND, 1, 1, False),
        (OR, 1, None, False),
        (OR, 2, None, False),
        (OR, 2, 2, True),
        ({"not": {"eq": [A, 1]}}, 1, 0, True),
        ({"not": {"eq": [A, 1]}}, 2, 0, False),
        ({"not": {"eq": [A, 1]}}, None, 0, False),
        ({"is_null": A}, None, 0, False),
        ({"is_null": A}, 1, 0, True),
        ({"eq": [A, "1"]}, 1, 1, False),
        ({"eq": [A, True]}, 1, 1, False),
        ({"eq": [A, None]}, 1, 1, False),
        ({"gt": [A, 0]}, -1, 1, True),
    ],
)
def test_kleene_logic_and_unknowns(expr: dict[str, Any], a: Any, b: Any, flagged: bool) -> None:
    assert (rule_rows(expr, a, b) == [0]) is flagged


def test_rules_over_strings_datetimes_and_dates() -> None:
    strings = contract_of(
        [{"name": "s", "type": "string"}],
        rules=[{"id": "r1", "expr": {"lt": [{"col": "s"}, "m"]}}],
    )
    report = validate([{"s": "a"}, {"s": "z"}], strings, now=NOW)
    assert shape(report) == [("row_rule", None, 1)]
    stamps = contract_of(
        [{"name": "t1", "type": "datetime"}, {"name": "t2", "type": "datetime"}],
        rules=[{"id": "r1", "expr": {"lt": [{"col": "t1"}, {"col": "t2"}]}}],
    )
    aware = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    rows = [
        {"t1": datetime(2026, 1, 1), "t2": aware},
        {"t1": datetime(2026, 1, 1, 2), "t2": aware},
    ]
    assert shape(validate(rows, stamps, now=NOW)) == [("row_rule", None, 1)]
    mixed = contract_of(
        [{"name": "d", "type": "date"}, {"name": "t", "type": "datetime"}],
        rules=[{"id": "r1", "expr": {"eq": [{"col": "d"}, {"col": "t"}]}}],
    )
    row = {"d": date(2026, 1, 1), "t": datetime(2026, 1, 1)}
    assert validate([row], mixed, now=NOW).passed is True


def test_invalid_cell_makes_rule_unknown_not_violated() -> None:
    contract = contract_of(
        [{"name": "a", "type": "integer"}],
        rules=[{"id": "r1", "expr": {"eq": [A, 1]}}],
    )
    assert shape(validate([{"a": "x"}], contract, now=NOW)) == [("type", "a", 0)]


def test_absent_optional_column_is_null_in_rules() -> None:
    contract = contract_of(
        [{"name": "a", "type": "integer", "required": False}, {"name": "b", "type": "integer"}],
        rules=[{"id": "r1", "expr": {"not": {"is_null": A}}}],
    )
    assert shape(validate([{"b": 1}], contract, now=NOW)) == [("row_rule", None, 0)]


def fresh_contract() -> Contract:
    return contract_of(
        [{"name": "updated_at", "type": "datetime", "nullable": True}],
        freshness={"column": "updated_at", "max_age": "PT24H"},
    )


def test_freshness_boundary_and_one_second_later() -> None:
    rows = [{"updated_at": "2026-01-01T00:00:00Z"}]
    ok = validate(
        rows, fresh_contract(), now=datetime(2026, 1, 2, tzinfo=timezone.utc), coerce=True
    )
    assert ok.passed is True
    assert ok.freshness == FreshnessResult(
        newest=datetime(2026, 1, 1, tzinfo=timezone.utc), age_seconds=86400.0, ok=True
    )
    late_now = datetime(2026, 1, 2, tzinfo=timezone.utc) + timedelta(seconds=1)
    late = validate(rows, fresh_contract(), now=late_now, coerce=True)
    assert late.passed is False
    assert late.freshness is not None
    assert late.freshness.age_seconds == 86401
    assert late.freshness.ok is False
    assert shape(late) == [("freshness", "updated_at", None)]


def test_naive_or_invalid_now_is_rejected() -> None:
    contract = fresh_contract()
    with pytest.raises(DataContractError) as info:
        validate([], contract, now=datetime(2026, 1, 2))
    assert info.value.code == "invalid_now"
    with pytest.raises(DataContractError) as info2:
        validate([], contract, now="2026-01-02")  # type: ignore[arg-type]
    assert info2.value.code == "invalid_now"


def test_all_null_and_empty_freshness_columns_fail() -> None:
    nulls = validate([{"updated_at": None}, {"updated_at": None}], fresh_contract(), now=NOW)
    assert nulls.freshness == FreshnessResult(newest=None, age_seconds=None, ok=False)
    assert nulls.passed is False
    assert shape(nulls) == [("freshness", "updated_at", None)]
    empty = validate([], fresh_contract(), now=NOW)
    assert empty.freshness is not None
    assert empty.freshness.ok is False
    assert empty.row_count == 0


def test_freshness_picks_newest_value_of_any_supported_kind() -> None:
    contract = contract_of(
        [{"name": "ts", "type": "string", "nullable": True}],
        freshness={"column": "ts", "max_age": "P1D"},
    )
    rows = [
        {"ts": "garbage"},
        {"ts": "2026-01-01T12:00:00Z"},
        {"ts": "2025-12-31T00:00:00Z"},
        {"ts": 5},
    ]
    report = validate(rows, contract, now=NOW)
    assert report.freshness is not None
    assert report.freshness.newest == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    naive = contract_of(
        [{"name": "ts", "type": "datetime"}], freshness={"column": "ts", "max_age": "P1D"}
    )
    report = validate([{"ts": datetime(2026, 1, 1, 6)}], naive, now=NOW)
    assert report.freshness is not None
    assert report.freshness.newest == datetime(2026, 1, 1, 6, tzinfo=timezone.utc)
    dated = contract_of(
        [{"name": "ts", "type": "date"}], freshness={"column": "ts", "max_age": "P1D"}
    )
    report = validate([{"ts": date(2026, 1, 1)}], dated, now=NOW)
    assert report.freshness is not None
    assert report.freshness.newest == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert report.passed is True


def test_future_timestamp_has_negative_age_and_passes() -> None:
    report = validate(
        [{"updated_at": "2026-01-03T00:00:00Z"}], fresh_contract(), now=NOW, coerce=True
    )
    assert report.freshness is not None
    assert report.freshness.age_seconds == -86400.0
    assert report.passed is True


def test_max_violations_truncates_but_counts_all_rows() -> None:
    contract = contract_of([{"name": "id", "type": "integer"}])
    rows = [{"id": "x"} for _ in range(10)]
    report = validate(rows, contract, now=NOW, max_violations=5)
    assert len(report.violations) == 5
    assert report.truncated is True
    assert report.row_count == 10
    assert report.passed is False
    exact = validate(rows[:5], contract, now=NOW, max_violations=5)
    assert len(exact.violations) == 5
    assert exact.truncated is False


@pytest.mark.parametrize("kwargs", [{"max_violations": 0}, {"max_unique_values": 0}])
def test_bad_limits_raise_value_error(kwargs: dict[str, int]) -> None:
    contract = contract_of([{"name": "id", "type": "integer"}])
    with pytest.raises(ValueError, match="at least 1"):
        validate([], contract, now=NOW, **kwargs)


def test_min_rows_on_empty_dataset() -> None:
    contract = contract_of([{"name": "id", "type": "integer"}], min_rows=1)
    report = validate([], contract, now=NOW)
    assert shape(report) == [("min_rows", None, None)]
    assert report.row_count == 0
    relaxed = contract_of([{"name": "id", "type": "integer"}], min_rows=0)
    assert validate([], relaxed, now=NOW).passed is True
    short = contract_of([{"name": "id", "type": "integer"}], min_rows=3)
    assert shape(validate([{"id": 1}, {"id": 2}], short, now=NOW)) == [("min_rows", None, None)]


def test_rows_are_streamed_once() -> None:
    def generate() -> Iterator[dict[str, int]]:
        yield from ({"id": i} for i in range(3))

    contract = contract_of([{"name": "id", "type": "integer"}])
    report = validate(generate(), contract, now=NOW)
    assert report.row_count == 3
    assert report.passed is True


def test_non_mapping_row_is_a_schema_violation() -> None:
    contract = contract_of([{"name": "id", "type": "integer"}])
    report = validate([{"id": 1}, 5], contract, now=NOW)  # type: ignore[list-item]
    assert shape(report) == [("schema", None, 1)]
    assert report.row_count == 2


def test_key_missing_from_some_rows_of_a_required_column() -> None:
    contract = contract_of([{"name": "id", "type": "integer"}, {"name": "name", "type": "string"}])
    rows = [{"id": 1}, {"id": 2, "name": "x"}, {"id": 3}]
    assert shape(validate(rows, contract, now=NOW)) == [
        ("schema", "name", 0),
        ("schema", "name", 2),
    ]


def test_pending_missing_key_buffer_is_capped() -> None:
    contract = contract_of([{"name": "id", "type": "integer"}, {"name": "name", "type": "string"}])
    rows = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4, "name": "x"}]
    report = validate(rows, contract, now=NOW, max_violations=1)
    assert shape(report) == [("schema", "name", 0)]
    assert report.truncated is True


def test_optional_column_may_be_absent() -> None:
    contract = contract_of(
        [{"name": "id", "type": "integer"}, {"name": "opt", "type": "string", "required": False}]
    )
    assert validate([{"id": 1}, {"id": 2}], contract, now=NOW).passed is True


def test_hand_built_contracts_are_checked() -> None:
    unknown_op = Contract(
        name="t",
        version="1",
        columns=[ColumnSpec(name="a", type="integer")],
        rules=[RowRule(id="r", expr={"xor": []})],
    )
    with pytest.raises(ContractError):
        validate([{"a": 1}], unknown_op, now=NOW)
    for spec in (
        ColumnSpec(name="a", type="string", pattern="("),
        ColumnSpec(name="a", type="integer", min="x"),
        ColumnSpec(name="a", type="integer", enum=[[1]]),
    ):
        with pytest.raises(ContractError):
            validate([], Contract(name="t", version="1", columns=[spec]), now=NOW)
    bad_freshness = Contract(
        name="t",
        version="1",
        columns=[ColumnSpec(name="a", type="integer")],
        freshness=FreshnessSpec(column="a", max_age="P1M"),
    )
    with pytest.raises(ContractError):
        validate([], bad_freshness, now=NOW)


def test_report_is_immutable() -> None:
    contract = contract_of([{"name": "id", "type": "integer"}])
    report = validate([{"id": 1}], contract, now=NOW)
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.passed = False  # type: ignore[misc]


def test_logging_is_not_configured_and_never_leaks_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("data_contract")
    assert any(isinstance(handler, logging.NullHandler) for handler in logger.handlers)
    contract = contract_of([{"name": "id", "type": "integer"}])
    with caplog.at_level(logging.DEBUG, logger="data_contract"):
        validate([{"id": "SECRETVALUE"}], contract, now=NOW)
    assert "SECRETVALUE" not in caplog.text
