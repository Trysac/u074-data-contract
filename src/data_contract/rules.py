"""Row rules: JSON expression trees, parsed without eval and evaluated three-valued."""

from __future__ import annotations

import operator
from collections.abc import Callable, Collection, Mapping
from typing import Any, Final

from ._values import as_aware, is_scalar, kind_of, safe_text
from .errors import ContractError

MAX_RULE_DEPTH: Final = 32
MAX_RULE_NODES: Final = 1000

_COMPARISONS: Final[dict[str, Callable[[Any, Any], Any]]] = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "lte": operator.le,
    "gt": operator.gt,
    "gte": operator.ge,
}


class RuleSyntaxError(ValueError):
    """A row rule is malformed; the message is safe to show."""


class _Parser:
    def __init__(self, columns: Collection[str]) -> None:
        self._columns = columns
        self._nodes = 0

    def _count(self) -> None:
        self._nodes += 1
        if self._nodes > MAX_RULE_NODES:
            raise RuleSyntaxError(f"rule has more than {MAX_RULE_NODES} nodes")

    def expr(self, raw: Any, depth: int) -> dict[str, Any]:
        if depth > MAX_RULE_DEPTH:
            raise RuleSyntaxError(f"rule is nested deeper than {MAX_RULE_DEPTH} levels")
        self._count()
        if not isinstance(raw, Mapping) or len(raw) != 1:
            raise RuleSyntaxError("expression must be an object with exactly one operator")
        op, arg = next(iter(raw.items()))
        if op in _COMPARISONS:
            if not isinstance(arg, list) or len(arg) != 2:
                raise RuleSyntaxError(f"{op} takes a list of exactly two operands")
            return {op: [self.operand(arg[0]), self.operand(arg[1])]}
        if op in ("and", "or"):
            if not isinstance(arg, list) or not arg:
                raise RuleSyntaxError(f"{op} takes a non-empty list of expressions")
            return {op: [self.expr(item, depth + 1) for item in arg]}
        if op == "not":
            return {op: self.expr(arg, depth + 1)}
        if op == "is_null":
            return {op: self.operand(arg)}
        raise RuleSyntaxError(f"unknown operator {safe_text(str(op), 40)}")

    def operand(self, raw: Any) -> Any:
        self._count()
        if isinstance(raw, Mapping):
            if len(raw) == 1 and "col" in raw:
                name = raw["col"]
                if not isinstance(name, str) or name not in self._columns:
                    raise RuleSyntaxError("operand references an undeclared column")
                return {"col": name}
            raise RuleSyntaxError("operand object must have the form {'col': name}")
        if raw is None or is_scalar(raw):
            return raw
        raise RuleSyntaxError("operand must be a column reference or a JSON scalar")


def parse_expr(raw: Any, columns: Collection[str]) -> dict[str, Any]:
    """Validate a rule expression and return a normalized deep copy.

    Raises:
        RuleSyntaxError: on the first problem (depth over 32, over 1000 nodes, bad shape).
    """
    return _Parser(columns).expr(raw, 1)


def _operand(raw: Any, row: Mapping[str, Any]) -> Any:
    if isinstance(raw, Mapping):
        return row.get(raw["col"])
    return raw


def _compare(fn: Callable[[Any, Any], Any], left: Any, right: Any) -> bool | None:
    if left is None or right is None:
        return None
    kind = kind_of(left)
    if kind is None or kind != kind_of(right):
        return None
    if kind == "datetime":
        left, right = as_aware(left), as_aware(right)
    return bool(fn(left, right))


def evaluate(expr: Mapping[str, Any], row: Mapping[str, Any]) -> bool | None:
    """Evaluate an expression with SQL three-valued logic; None means unknown."""
    op, arg = next(iter(expr.items()))
    if op in _COMPARISONS:
        return _compare(_COMPARISONS[op], _operand(arg[0], row), _operand(arg[1], row))
    if op == "and":
        unknown = False
        for item in arg:
            result = evaluate(item, row)
            if result is False:
                return False
            unknown = unknown or result is None
        return None if unknown else True
    if op == "or":
        unknown = False
        for item in arg:
            result = evaluate(item, row)
            if result is True:
                return True
            unknown = unknown or result is None
        return None if unknown else False
    if op == "not":
        inner = evaluate(arg, row)
        return None if inner is None else not inner
    if op == "is_null":
        return _operand(arg, row) is None
    raise ContractError([f"row rule uses unknown operator {safe_text(str(op), 40)}"])
