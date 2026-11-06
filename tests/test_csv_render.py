"""Tests for read_csv_rows and render, including the byte-exact JSON golden file."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from data_contract import (
    DataContractError,
    FreshnessResult,
    ValidationReport,
    Violation,
    load_contract,
    read_csv_rows,
    render,
    validate,
)

GOLDEN = Path(__file__).parent / "golden" / "report.json"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def golden_report() -> ValidationReport:
    contract = load_contract(
        {
            "name": "users",
            "version": "1.0.0",
            "columns": [
                {"name": "id", "type": "integer", "unique": True, "min": 1},
                {"name": "email", "type": "string", "pattern": "[^@ ]+@[^@ ]+"},
                {"name": "updated_at", "type": "datetime"},
            ],
            "freshness": {"column": "updated_at", "max_age": "PT24H"},
        }
    )
    rows = [
        {"id": 1, "email": "a@example.com", "updated_at": T0},
        {"id": 1, "email": "not-an-email", "updated_at": T0},
        {"id": 0, "email": "c@example.com", "updated_at": T0},
    ]
    return validate(rows, contract, now=datetime(2026, 1, 3, tzinfo=timezone.utc))


def test_json_render_matches_golden_file() -> None:
    rendered = render(golden_report(), "json")
    assert rendered.encode("utf-8") == GOLDEN.read_bytes().rstrip(b"\n")
    assert rendered == json.dumps(json.loads(rendered), sort_keys=True, indent=2)


def test_json_render_without_freshness() -> None:
    report = ValidationReport(
        passed=True, row_count=0, violations=[], truncated=False, freshness=None
    )
    parsed = json.loads(render(report, "json"))
    assert parsed == {
        "freshness": None,
        "passed": True,
        "row_count": 0,
        "truncated": False,
        "violations": [],
    }
    missing = ValidationReport(
        passed=False,
        row_count=0,
        violations=[],
        truncated=False,
        freshness=FreshnessResult(newest=None, age_seconds=None, ok=False),
    )
    freshness = json.loads(render(missing, "json"))["freshness"]
    assert freshness == {"age_seconds": None, "newest": None, "ok": False}


def test_text_render_of_a_failed_report() -> None:
    report = ValidationReport(
        passed=False,
        row_count=3,
        violations=[
            Violation("unique", "id", 1, "value repeats an earlier row"),
            Violation("min_rows", None, None, "expected at least 5 rows"),
        ],
        truncated=True,
        freshness=FreshnessResult(newest=None, age_seconds=None, ok=False),
    )
    assert render(report, "text") == (
        "Data contract validation: FAILED\n"
        "Rows: 3\n"
        "Violations: 2 (truncated)\n"
        "Freshness: FAILED (no valid timestamp)\n"
        "- [unique] column 'id', row 1: value repeats an earlier row\n"
        "- [min_rows] expected at least 5 rows"
    )


def test_text_render_of_passed_reports() -> None:
    plain = ValidationReport(
        passed=True, row_count=3, violations=[], truncated=False, freshness=None
    )
    assert render(plain, "text") == ("Data contract validation: PASSED\nRows: 3\nViolations: 0")
    fresh = ValidationReport(
        passed=True,
        row_count=1,
        violations=[],
        truncated=False,
        freshness=FreshnessResult(newest=T0, age_seconds=86400.0, ok=True),
    )
    assert "Freshness: ok (newest 2026-01-01T00:00:00+00:00, age 86400.0s)" in render(fresh, "text")
    stale = ValidationReport(
        passed=False,
        row_count=1,
        violations=[],
        truncated=False,
        freshness=FreshnessResult(newest=T0, age_seconds=172800.0, ok=False),
    )
    assert "Freshness: FAILED (newest" in render(stale, "text")


def test_text_render_escapes_control_characters() -> None:
    report = ValidationReport(
        passed=False,
        row_count=1,
        violations=[Violation("schema", "bad\ncol", None, "unexpected column")],
        truncated=False,
        freshness=None,
    )
    text = render(report, "text")
    assert "bad\ncol" not in text
    assert "bad\\ncol" in text
    assert len(text.splitlines()) == 4


def test_render_rejects_unknown_format() -> None:
    report = ValidationReport(
        passed=True, row_count=0, violations=[], truncated=False, freshness=None
    )
    with pytest.raises(ValueError, match="fmt"):
        render(report, "xml")  # type: ignore[arg-type]


def test_read_csv_rows_basic(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_bytes("\ufeffid,name\n1,Ada\n\n2,Grace\n".encode())
    assert list(read_csv_rows(path)) == [
        {"id": "1", "name": "Ada"},
        {"id": "2", "name": "Grace"},
    ]
    assert list(read_csv_rows(str(path))) == list(read_csv_rows(path))


def test_read_csv_rows_ragged_rows_and_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "ragged.csv"
    path.write_text("a,b\n1\n1,2,3\n", encoding="utf-8")
    assert list(read_csv_rows(path)) == [{"a": "1"}, {"a": "1", "b": "2"}]
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    assert list(read_csv_rows(empty)) == []
    header_only = tmp_path / "header.csv"
    header_only.write_text("a,b\n", encoding="utf-8")
    assert list(read_csv_rows(header_only)) == []


def test_read_csv_rows_encoding(tmp_path: Path) -> None:
    path = tmp_path / "latin.csv"
    path.write_bytes("name\ncaf\u00e9\n".encode("latin-1"))
    assert list(read_csv_rows(path, encoding="latin-1")) == [{"name": "caf\u00e9"}]


def test_read_csv_rows_field_limit(tmp_path: Path) -> None:
    path = tmp_path / "big.csv"
    path.write_text("a\n" + "x" * 200_000 + "\n", encoding="utf-8")
    with pytest.raises(DataContractError) as info:
        list(read_csv_rows(path))
    assert info.value.code == "too_large"


def test_read_csv_rows_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        list(read_csv_rows(tmp_path / "nope.csv"))


def test_csv_feeds_validate_with_coercion(tmp_path: Path) -> None:
    path = tmp_path / "users.csv"
    path.write_text("id,name\n1,Ada\n2,Grace\n2,Linus\nx,Zed\n", encoding="utf-8")
    contract = load_contract(
        {
            "name": "users",
            "version": "1",
            "columns": [
                {"name": "id", "type": "integer", "unique": True},
                {"name": "name", "type": "string"},
            ],
        }
    )
    report = validate(read_csv_rows(path), contract, now=T0, coerce=True)
    assert report.row_count == 4
    assert [(v.rule, v.row_index) for v in report.violations] == [("unique", 2), ("type", 3)]
