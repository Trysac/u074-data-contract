"""Render a ValidationReport as plain text or deterministic JSON."""

from __future__ import annotations

import json
from typing import Any, Literal

from ._values import safe_text
from .validation import ValidationReport


def _as_dict(report: ValidationReport) -> dict[str, Any]:
    freshness: dict[str, Any] | None = None
    if report.freshness is not None:
        newest = report.freshness.newest
        freshness = {
            "age_seconds": report.freshness.age_seconds,
            "newest": None if newest is None else newest.isoformat(),
            "ok": report.freshness.ok,
        }
    return {
        "freshness": freshness,
        "passed": report.passed,
        "row_count": report.row_count,
        "truncated": report.truncated,
        "violations": [
            {
                "column": violation.column,
                "message": violation.message,
                "row_index": violation.row_index,
                "rule": violation.rule,
            }
            for violation in report.violations
        ],
    }


def _as_text(report: ValidationReport) -> str:
    status = "PASSED" if report.passed else "FAILED"
    suffix = " (truncated)" if report.truncated else ""
    lines = [
        f"Data contract validation: {status}",
        f"Rows: {report.row_count}",
        f"Violations: {len(report.violations)}{suffix}",
    ]
    freshness = report.freshness
    if freshness is not None:
        if freshness.newest is None:
            lines.append("Freshness: FAILED (no valid timestamp)")
        else:
            state = "ok" if freshness.ok else "FAILED"
            lines.append(
                f"Freshness: {state} (newest {freshness.newest.isoformat()}, "
                f"age {freshness.age_seconds}s)"
            )
    for violation in report.violations:
        where: list[str] = []
        if violation.column is not None:
            where.append(f"column '{safe_text(violation.column)}'")
        if violation.row_index is not None:
            where.append(f"row {violation.row_index}")
        prefix = f"{', '.join(where)}: " if where else ""
        lines.append(f"- [{violation.rule}] {prefix}{safe_text(violation.message, 200)}")
    return "\n".join(lines)


def render(report: ValidationReport, fmt: Literal["text", "json"]) -> str:
    """Render ``report`` as ``'text'`` or ``'json'``.

    The JSON form uses sorted keys, an indent of 2 and no trailing newline. Row indexes
    are zero-based.

    Raises:
        ValueError: when ``fmt`` is neither ``'text'`` nor ``'json'``.
    """
    if fmt == "json":
        return json.dumps(_as_dict(report), sort_keys=True, indent=2)
    if fmt == "text":
        return _as_text(report)
    raise ValueError("fmt must be 'text' or 'json'")
