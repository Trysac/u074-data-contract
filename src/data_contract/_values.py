"""Shared value helpers: type checks, coercion, comparison kinds and safe text."""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from typing import Any, Final

MAX_STRING_LENGTH: Final = 10_000
MAX_LITERAL_LENGTH: Final = 1_000
_MAX_TIMESTAMP_LENGTH: Final = 64

_INTEGER_RE: Final = re.compile(r"[+-]?[0-9]+", re.ASCII)
_NUMBER_RE: Final = re.compile(
    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?",
    re.ASCII,
)
_DATE_RE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)


class Invalid:
    """Sentinel type for a value that failed its declared column type."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "INVALID"


INVALID: Final = Invalid()


def safe_text(text: str, limit: int = 80) -> str:
    """Return ``text`` clipped and escaped so it is single-line ASCII."""
    return text[:limit].encode("unicode_escape").decode("ascii")


def as_aware(value: datetime) -> datetime:
    """Treat a naive datetime as UTC; leave aware datetimes untouched."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def kind_of(value: object) -> str | None:
    """Return the comparison kind of a value, or None when it is not comparable."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "num"
    if isinstance(value, str):
        return "str"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    return None


def value_key(value: Any) -> tuple[str, Any]:
    """Return a hashable, type-strict key (so ``True`` never equals ``1``)."""
    kind = kind_of(value) or "other"
    if isinstance(value, datetime):
        return (kind, as_aware(value))
    return (kind, value)


def is_scalar(value: object) -> bool:
    """Return True for a JSON string, boolean, integer or finite float within limits."""
    if isinstance(value, bool):
        return True
    if isinstance(value, str):
        return len(value) <= MAX_LITERAL_LENGTH
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def parse_date(text: str) -> date | None:
    """Parse ``YYYY-MM-DD`` (ASCII only); return None when invalid."""
    if len(text) != 10 or _DATE_RE.fullmatch(text) is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_datetime(text: str) -> datetime | None:
    """Parse an ISO 8601 datetime (trailing ``Z`` allowed); naive values become UTC."""
    if len(text) > _MAX_TIMESTAMP_LENGTH or not text.isascii():
        return None
    candidate = f"{text[:-1]}+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return as_aware(parsed)


def bound_value(type_name: str, raw: Any) -> Any:
    """Parse a ``min``/``max`` bound for a column type or raise ValueError."""
    if type_name in ("integer", "number"):
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise ValueError("bound must be a finite number")
        if isinstance(raw, float) and not math.isfinite(raw):
            raise ValueError("bound must be a finite number")
        return raw
    if type_name == "date":
        parsed_date = parse_date(raw) if isinstance(raw, str) else None
        if parsed_date is None:
            raise ValueError("bound must be an ISO 8601 date")
        return parsed_date
    if type_name == "datetime":
        parsed_datetime = parse_datetime(raw) if isinstance(raw, str) else None
        if parsed_datetime is None:
            raise ValueError("bound must be an ISO 8601 datetime")
        return parsed_datetime
    raise ValueError(f"min and max are not supported for type {type_name}")


def _coerce_string(type_name: str, text: str) -> Any:
    if type_name == "string":
        return text
    if len(text) > MAX_STRING_LENGTH:
        return INVALID
    if type_name == "integer":
        if _INTEGER_RE.fullmatch(text) is None:
            return INVALID
        try:
            return int(text)
        except ValueError:
            return INVALID
    if type_name == "number":
        if _NUMBER_RE.fullmatch(text) is None:
            return INVALID
        number = float(text)
        return number if math.isfinite(number) else INVALID
    if type_name == "boolean":
        if text == "true":
            return True
        if text == "false":
            return False
        return INVALID
    if type_name == "date":
        parsed_date = parse_date(text)
        return INVALID if parsed_date is None else parsed_date
    if type_name == "datetime":
        parsed_datetime = parse_datetime(text)
        return INVALID if parsed_datetime is None else parsed_datetime
    return INVALID


def _check_python(type_name: str, value: Any) -> Any:
    if type_name == "string":
        return value if isinstance(value, str) else INVALID
    if type_name == "integer":
        return value if isinstance(value, int) and not isinstance(value, bool) else INVALID
    if type_name == "number":
        if isinstance(value, bool):
            return INVALID
        if isinstance(value, int):
            return value
        if isinstance(value, float) and math.isfinite(value):
            return value
        return INVALID
    if type_name == "boolean":
        return value if isinstance(value, bool) else INVALID
    if type_name == "date":
        return value if isinstance(value, date) and not isinstance(value, datetime) else INVALID
    if type_name == "datetime":
        return as_aware(value) if isinstance(value, datetime) else INVALID
    return INVALID


def check_type(type_name: str, value: Any, coerce: bool) -> Any:
    """Return the typed value, or ``INVALID`` when it does not satisfy ``type_name``.

    With ``coerce`` strings are parsed (ASCII only, never stripped); every other value is
    checked as a Python type.
    """
    if coerce and isinstance(value, str):
        return _coerce_string(type_name, value)
    return _check_python(type_name, value)
