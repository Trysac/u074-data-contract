"""Contract model and the JSON loader (standard library only, no eval)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Final, Literal, cast, get_args

from ._values import bound_value, is_scalar
from .errors import ContractError, DataContractError
from .rules import RuleSyntaxError, parse_expr

ColumnType = Literal["string", "integer", "number", "boolean", "date", "datetime"]

DEFAULT_MAX_BYTES: Final = 1_048_576
MAX_COLUMNS: Final = 10_000
MAX_RULES: Final = 1_000
MAX_ENUM_VALUES: Final = 10_000
MAX_PATTERN_LENGTH: Final = 256
MAX_NAME_LENGTH: Final = 200
MAX_RULE_ID_LENGTH: Final = 100
MAX_PROBLEMS: Final = 100

_CONTRACT_KEYS: Final = frozenset(
    {"name", "version", "columns", "allow_extra_columns", "min_rows", "rules", "freshness"}
)
_COLUMN_KEYS: Final = frozenset(
    {"name", "type", "required", "nullable", "unique", "enum", "min", "max", "pattern"}
)
_RULE_KEYS: Final = frozenset({"id", "expr"})
_FRESHNESS_KEYS: Final = frozenset({"column", "max_age"})

_DURATION_RE: Final = re.compile(
    r"P(?:([0-9]{1,7})D)?(?:T(?:([0-9]{1,7})H)?(?:([0-9]{1,7})M)?(?:([0-9]{1,7})S)?)?",
    re.ASCII,
)
_BAD_DURATION: Final = (
    "max_age must be an ISO 8601 duration such as PT24H or P1DT2H30M "
    "(years and months are not supported)"
)


@dataclass(frozen=True)
class ColumnSpec:
    """One column of a contract."""

    name: str
    type: ColumnType
    required: bool = True
    nullable: bool = False
    unique: bool = False
    enum: list[Any] | None = None
    min: int | float | str | None = None
    max: int | float | str | None = None
    pattern: str | None = None


@dataclass(frozen=True)
class RowRule:
    """A named row rule; ``expr`` is a normalized JSON expression tree."""

    id: str
    expr: dict[str, Any]


@dataclass(frozen=True)
class FreshnessSpec:
    """Freshness SLA: the newest value of ``column`` must be younger than ``max_age``."""

    column: str
    max_age: str

    @property
    def max_age_delta(self) -> timedelta:
        """The maximum age as a timedelta.

        Raises:
            ContractError: if ``max_age`` is not a valid ``PnDTnHnMnS`` duration.
        """
        try:
            return parse_max_age(self.max_age)
        except ValueError as exc:
            raise ContractError([f"freshness: {exc}"]) from exc


@dataclass(frozen=True)
class Contract:
    """A validated data contract."""

    name: str
    version: str
    columns: list[ColumnSpec]
    allow_extra_columns: bool = True
    min_rows: int | None = None
    rules: list[RowRule] = field(default_factory=list)
    freshness: FreshnessSpec | None = None


def parse_max_age(text: object) -> timedelta:
    """Parse the ISO 8601 duration subset ``PnDTnHnMnS``.

    Raises:
        ValueError: for anything else, including years and months.
    """
    if isinstance(text, str) and len(text) <= 64:
        match = _DURATION_RE.fullmatch(text)
        if match is not None and text != "P" and not text.endswith("T"):
            days, hours, minutes, seconds = (int(group) if group else 0 for group in match.groups())
            return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    raise ValueError(_BAD_DURATION)


def _clip(value: object, limit: int = 40) -> str:
    return repr(value)[:limit]


def _check_keys(
    raw: Mapping[Any, Any], allowed: frozenset[str], label: str, problems: list[str]
) -> None:
    unknown = sorted(str(key) for key in raw if key not in allowed)
    for key in unknown[:5]:
        problems.append(f"{label}: unknown key {_clip(key)}")


def _text(raw: Any, key: str, label: str, problems: list[str], limit: int) -> str:
    if not isinstance(raw, str) or not raw or len(raw) > limit:
        problems.append(f"{label}: {key} must be a non-empty string of at most {limit} characters")
        return ""
    return raw


def _flag(raw: Mapping[str, Any], key: str, default: bool, label: str, problems: list[str]) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        problems.append(f"{label}: {key} must be a boolean")
        return default
    return value


def _column_type(raw: object) -> ColumnType | None:
    if isinstance(raw, str) and raw in get_args(ColumnType):
        return cast(ColumnType, raw)
    return None


def _enum(
    raw: Any, column_type: ColumnType | None, label: str, problems: list[str]
) -> list[Any] | None:
    if raw is None:
        return None
    if column_type in ("date", "datetime"):
        problems.append(f"{label}: enum is not supported for type {column_type}")
        return None
    if not isinstance(raw, list) or not raw or len(raw) > MAX_ENUM_VALUES:
        problems.append(
            f"{label}: enum must be a non-empty list of at most {MAX_ENUM_VALUES} values"
        )
        return None
    if not all(is_scalar(item) for item in raw):
        problems.append(f"{label}: enum values must be strings, numbers or booleans")
        return None
    return list(raw)


def _bound(
    raw: Mapping[str, Any],
    key: str,
    column_type: ColumnType | None,
    label: str,
    problems: list[str],
) -> Any:
    value = raw.get(key)
    if value is None or column_type is None:
        return None
    try:
        return bound_value(column_type, value)
    except ValueError as exc:
        problems.append(f"{label}: {key}: {exc}")
        return None


def _pattern(raw: Any, label: str, problems: list[str]) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or len(raw) > MAX_PATTERN_LENGTH:
        problems.append(
            f"{label}: pattern must be a string of at most {MAX_PATTERN_LENGTH} characters"
        )
        return None
    try:
        re.compile(raw)
    except (re.error, OverflowError, RecursionError):
        problems.append(f"{label}: pattern is not a valid regular expression")
        return None
    return raw


def _build_column(raw: Any, index: int, problems: list[str]) -> ColumnSpec | None:
    label = f"columns[{index}]"
    if not isinstance(raw, Mapping):
        problems.append(f"{label}: must be an object")
        return None
    start = len(problems)
    if isinstance(raw.get("name"), str):
        label = f"{label} ({_clip(raw['name'], 60)})"
    _check_keys(raw, _COLUMN_KEYS, label, problems)
    name = _text(raw.get("name"), "name", label, problems, MAX_NAME_LENGTH)
    column_type = _column_type(raw.get("type"))
    if column_type is None:
        problems.append(f"{label}: type must be one of {', '.join(get_args(ColumnType))}")
    required = _flag(raw, "required", True, label, problems)
    nullable = _flag(raw, "nullable", False, label, problems)
    unique = _flag(raw, "unique", False, label, problems)
    enum = _enum(raw.get("enum"), column_type, label, problems)
    low = _bound(raw, "min", column_type, label, problems)
    high = _bound(raw, "max", column_type, label, problems)
    if low is not None and high is not None and low > high:
        problems.append(f"{label}: min is greater than max")
    pattern = _pattern(raw.get("pattern"), label, problems)
    if column_type is None or len(problems) > start:
        return None
    return ColumnSpec(
        name=name,
        type=column_type,
        required=required,
        nullable=nullable,
        unique=unique,
        enum=enum,
        min=raw.get("min"),
        max=raw.get("max"),
        pattern=pattern,
    )


def _build_columns(raw: Any, problems: list[str]) -> tuple[list[ColumnSpec], set[str]]:
    if not isinstance(raw, list) or not raw or len(raw) > MAX_COLUMNS:
        problems.append(f"columns must be a non-empty list of at most {MAX_COLUMNS} items")
        return [], set()
    names = {
        item["name"]
        for item in raw
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }
    columns: list[ColumnSpec] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        spec = _build_column(item, index, problems)
        if spec is None:
            continue
        if spec.name in seen:
            problems.append(f"columns[{index}]: duplicate column name")
        seen.add(spec.name)
        columns.append(spec)
    return columns, names


def _build_rules(raw: Any, columns: set[str], problems: list[str]) -> list[RowRule]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_RULES:
        problems.append(f"rules must be a list of at most {MAX_RULES} items")
        return []
    rules: list[RowRule] = []
    ids: set[str] = set()
    for index, item in enumerate(raw):
        label = f"rules[{index}]"
        if not isinstance(item, Mapping):
            problems.append(f"{label}: must be an object")
            continue
        _check_keys(item, _RULE_KEYS, label, problems)
        rule_id = _text(item.get("id"), "id", label, problems, MAX_RULE_ID_LENGTH)
        if rule_id and rule_id in ids:
            problems.append(f"{label}: duplicate rule id")
        if "expr" not in item:
            problems.append(f"{label}: expr is required")
            continue
        try:
            expr = parse_expr(item["expr"], columns)
        except RuleSyntaxError as exc:
            problems.append(f"{label}: {exc}")
            continue
        if rule_id:
            ids.add(rule_id)
            rules.append(RowRule(id=rule_id, expr=expr))
    return rules


def _build_freshness(raw: Any, columns: set[str], problems: list[str]) -> FreshnessSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        problems.append("freshness must be an object")
        return None
    start = len(problems)
    _check_keys(raw, _FRESHNESS_KEYS, "freshness", problems)
    column = raw.get("column")
    if not isinstance(column, str) or column not in columns:
        problems.append("freshness: column must name a declared column")
    max_age = raw.get("max_age")
    try:
        parse_max_age(max_age)
    except ValueError as exc:
        problems.append(f"freshness: {exc}")
    if len(problems) > start:
        return None
    return FreshnessSpec(column=str(column), max_age=str(max_age))


def _build_min_rows(raw: Any, problems: list[str]) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        problems.append("min_rows must be a non-negative integer")
        return None
    return raw


def _build_contract(data: Any) -> Contract:
    if not isinstance(data, Mapping):
        raise ContractError(["contract must be a JSON object"])
    problems: list[str] = []
    _check_keys(data, _CONTRACT_KEYS, "contract", problems)
    name = _text(data.get("name"), "name", "contract", problems, MAX_NAME_LENGTH)
    version = _text(data.get("version"), "version", "contract", problems, MAX_NAME_LENGTH)
    columns, names = _build_columns(data.get("columns"), problems)
    allow_extra = _flag(data, "allow_extra_columns", True, "contract", problems)
    min_rows = _build_min_rows(data.get("min_rows"), problems)
    rules = _build_rules(data.get("rules"), names, problems)
    freshness = _build_freshness(data.get("freshness"), names, problems)
    if problems:
        raise ContractError(problems[:MAX_PROBLEMS])
    return Contract(
        name=name,
        version=version,
        columns=columns,
        allow_extra_columns=allow_extra,
        min_rows=min_rows,
        rules=rules,
        freshness=freshness,
    )


def _reject_constant(_name: str) -> Any:
    raise ValueError("non-finite JSON number")


def _read_json(path: Path, max_bytes: int) -> Any:
    try:
        with path.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError as exc:
        raise ContractError(["contract file cannot be read"]) from exc
    if len(raw) > max_bytes:
        raise DataContractError("too_large", f"contract exceeds {max_bytes} bytes")
    try:
        return json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ContractError(["contract is not valid UTF-8 JSON"]) from exc


def load_contract(
    source: Path | Mapping[str, Any], *, max_bytes: int = DEFAULT_MAX_BYTES
) -> Contract:
    """Load and validate a contract from a JSON file or an already parsed mapping.

    Args:
        source: A ``pathlib.Path`` to a UTF-8 JSON file, or a mapping.
        max_bytes: Largest accepted file size in bytes (default 1 MiB).

    Raises:
        ContractError: when the contract is invalid; ``problems`` lists every problem.
        DataContractError: with code ``too_large`` when the file exceeds ``max_bytes``.
        ValueError: when ``max_bytes`` is below 1.
    """
    if max_bytes < 1:
        raise ValueError("max_bytes must be at least 1")
    if isinstance(source, Path):
        data: Any = _read_json(source, max_bytes)
    elif isinstance(source, Mapping):
        data = source
    else:
        raise ContractError(["source must be a pathlib.Path or a mapping"])
    return _build_contract(data)
