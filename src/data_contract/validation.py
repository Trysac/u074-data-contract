"""Streaming validation of tabular rows against a Contract."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal

from ._values import (
    INVALID,
    MAX_STRING_LENGTH,
    as_aware,
    bound_value,
    check_type,
    parse_datetime,
    safe_text,
    value_key,
)
from .contract import ColumnSpec, Contract
from .errors import ContractError, DataContractError
from .rules import evaluate

_LOGGER = logging.getLogger(__name__)

RuleName = Literal[
    "schema",
    "min_rows",
    "type",
    "nullable",
    "enum",
    "range",
    "pattern",
    "unique",
    "row_rule",
    "freshness",
]


@dataclass(frozen=True)
class Violation:
    """One contract violation; ``row_index`` is zero-based and None for dataset-level rules."""

    rule: RuleName
    column: str | None
    row_index: int | None
    message: str


@dataclass(frozen=True)
class FreshnessResult:
    """Outcome of the freshness check (``newest`` is timezone-aware UTC-normalized)."""

    newest: datetime | None
    age_seconds: float | None
    ok: bool


@dataclass(frozen=True)
class ValidationReport:
    """Result of :func:`validate`; ``row_count`` counts every row, even after truncation."""

    passed: bool
    row_count: int
    violations: list[Violation]
    truncated: bool
    freshness: FreshnessResult | None


@dataclass(frozen=True)
class _ColumnPlan:
    spec: ColumnSpec
    enum_keys: frozenset[tuple[str, Any]] | None
    low: Any
    high: Any
    regex: re.Pattern[str] | None


def _plan_for(spec: ColumnSpec) -> _ColumnPlan:
    try:
        enum_keys = None
        if spec.enum is not None:
            enum_keys = frozenset(value_key(item) for item in spec.enum)
        low = None if spec.min is None else bound_value(spec.type, spec.min)
        high = None if spec.max is None else bound_value(spec.type, spec.max)
        regex = None if spec.pattern is None else re.compile(spec.pattern)
    except (ValueError, TypeError, re.error) as exc:
        raise ContractError([f"column {safe_text(spec.name)}: invalid constraint"]) from exc
    return _ColumnPlan(spec, enum_keys, low, high, regex)


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return as_aware(value)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str):
        return parse_datetime(value)
    return None


class _Run:
    def __init__(
        self,
        contract: Contract,
        now: datetime,
        max_violations: int,
        coerce: bool,
        max_unique_values: int,
    ) -> None:
        self.contract = contract
        self.now = now
        self.max_violations = max_violations
        self.coerce = coerce
        self.max_unique_values = max_unique_values
        self.plans = [_plan_for(spec) for spec in contract.columns]
        self.declared = {spec.name for spec in contract.columns}
        self.freshness_limit = (
            None if contract.freshness is None else contract.freshness.max_age_delta
        )
        self.violations: list[Violation] = []
        self.truncated = False
        self.row_count = 0
        self.seen: set[str] = set()
        self.pending: dict[str, list[int]] = {}
        self.overflowed: set[str] = set()
        self.extras: dict[str, None] = {}
        self.extras_overflow = False
        self.unique_sets: dict[str, set[tuple[str, Any]]] = {
            plan.spec.name: set() for plan in self.plans if plan.spec.unique
        }
        self.unique_stopped: set[str] = set()
        self.newest: datetime | None = None

    def add(self, rule: RuleName, column: str | None, row_index: int | None, message: str) -> None:
        if len(self.violations) >= self.max_violations:
            self.truncated = True
            return
        self.violations.append(Violation(rule, column, row_index, message))

    def feed(self, index: int, row: Any) -> None:
        self.row_count += 1
        if not isinstance(row, Mapping):
            self.add("schema", None, index, "row is not a mapping")
            return
        if not self.contract.allow_extra_columns:
            self._track_extras(row)
        typed: dict[str, Any] = {}
        for plan in self.plans:
            name = plan.spec.name
            if name not in row:
                self._absent(plan.spec, index)
                continue
            if name not in self.seen:
                self._first_seen(name)
            typed[name] = self._cell(plan, index, row[name])
        freshness = self.contract.freshness
        if freshness is not None:
            candidate = _timestamp(row.get(freshness.column))
            if candidate is not None and (self.newest is None or candidate > self.newest):
                self.newest = candidate
        for rule in self.contract.rules:
            if evaluate(rule.expr, typed) is False:
                self.add("row_rule", None, index, f"row rule '{rule.id}' violated")

    def _track_extras(self, row: Mapping[str, Any]) -> None:
        for key in row:
            if not isinstance(key, str) or key in self.declared or key in self.extras:
                continue
            if len(self.extras) < self.max_violations:
                self.extras[key] = None
            else:
                self.extras_overflow = True

    def _first_seen(self, name: str) -> None:
        self.seen.add(name)
        for pending_index in self.pending.pop(name, []):
            self.add("schema", name, pending_index, "required column is missing from this row")
        if name in self.overflowed:
            self.truncated = True

    def _absent(self, spec: ColumnSpec, index: int) -> None:
        if not spec.required:
            return
        if spec.name in self.seen:
            self.add("schema", spec.name, index, "required column is missing from this row")
            return
        bucket = self.pending.setdefault(spec.name, [])
        if len(bucket) < self.max_violations:
            bucket.append(index)
        else:
            self.overflowed.add(spec.name)

    def _cell(self, plan: _ColumnPlan, index: int, value: Any) -> Any:
        spec = plan.spec
        name = spec.name
        if value is None:
            if not spec.nullable:
                self.add("nullable", name, index, "null value in a non-nullable column")
            return None
        typed = check_type(spec.type, value, self.coerce)
        if typed is INVALID:
            self.add("type", name, index, f"value is not a valid {spec.type}")
            return INVALID
        if plan.enum_keys is not None and value_key(typed) not in plan.enum_keys:
            self.add("enum", name, index, "value is not in the allowed set")
        if plan.low is not None and typed < plan.low:
            self.add("range", name, index, "value is below the minimum")
        elif plan.high is not None and typed > plan.high:
            self.add("range", name, index, "value is above the maximum")
        if plan.regex is not None and isinstance(value, str):
            mismatch = len(value) > MAX_STRING_LENGTH or plan.regex.fullmatch(value) is None
            if mismatch:
                self.add("pattern", name, index, "value does not match the required pattern")
        if spec.unique:
            self._track_unique(name, index, typed)
        return typed

    def _track_unique(self, name: str, index: int, typed: Any) -> None:
        if name in self.unique_stopped:
            return
        seen = self.unique_sets[name]
        key = value_key(typed)
        if key in seen:
            self.add("unique", name, index, "value repeats an earlier row")
        elif len(seen) >= self.max_unique_values:
            self.unique_stopped.add(name)
            del self.unique_sets[name]
            self.add(
                "unique",
                name,
                index,
                "unique tracking limit reached; column is no longer checked",
            )
        else:
            seen.add(key)

    def _freshness(self) -> FreshnessResult | None:
        spec = self.contract.freshness
        limit = self.freshness_limit
        if spec is None or limit is None:
            return None
        if self.newest is None:
            self.add(
                "freshness", spec.column, None, "no valid timestamp found in the freshness column"
            )
            return FreshnessResult(newest=None, age_seconds=None, ok=False)
        age = (self.now - self.newest).total_seconds()
        ok = age <= limit.total_seconds()
        if not ok:
            self.add(
                "freshness",
                spec.column,
                None,
                f"newest value is older than the maximum age {spec.max_age}",
            )
        return FreshnessResult(newest=self.newest, age_seconds=age, ok=ok)

    def finish(self) -> ValidationReport:
        if self.row_count > 0:
            for plan in self.plans:
                name = plan.spec.name
                if plan.spec.required and name not in self.seen:
                    self.add("schema", name, None, "required column is missing from the dataset")
            for extra in self.extras:
                self.add("schema", extra[:200], None, f"unexpected column {safe_text(extra)}")
            if self.extras_overflow:
                self.truncated = True
        minimum = self.contract.min_rows
        if minimum is not None and self.row_count < minimum:
            self.add(
                "min_rows",
                None,
                None,
                f"expected at least {minimum} rows, got {self.row_count}",
            )
        freshness = self._freshness()
        _LOGGER.debug("validated %d rows with %d violations", self.row_count, len(self.violations))
        return ValidationReport(
            passed=not self.violations and not self.truncated,
            row_count=self.row_count,
            violations=self.violations,
            truncated=self.truncated,
            freshness=freshness,
        )


def validate(
    rows: Iterable[Mapping[str, Any]],
    contract: Contract,
    *,
    now: datetime,
    max_violations: int = 1000,
    coerce: bool = False,
    max_unique_values: int = 1_000_000,
) -> ValidationReport:
    """Validate ``rows`` (streamed once) against ``contract``.

    Args:
        rows: Any iterable of mappings; every row is counted in ``row_count``.
        contract: The contract to enforce.
        now: Timezone-aware instant used for the freshness check.
        max_violations: Violations kept in the report; further ones set ``truncated``.
        coerce: Parse string cells according to the column type.
        max_unique_values: Distinct values tracked per unique column.

    Raises:
        DataContractError: with code ``invalid_now`` when ``now`` is not timezone-aware.
        ContractError: when a hand-built contract is inconsistent.
        ValueError: when ``max_violations`` or ``max_unique_values`` is below 1.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise DataContractError("invalid_now", "now must be a timezone-aware datetime")
    if max_violations < 1:
        raise ValueError("max_violations must be at least 1")
    if max_unique_values < 1:
        raise ValueError("max_unique_values must be at least 1")
    run = _Run(contract, now, max_violations, coerce, max_unique_values)
    for index, row in enumerate(rows):
        run.feed(index, row)
    return run.finish()
