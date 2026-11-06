"""Typed errors raised by the data_contract library."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal

ErrorCode = Literal["invalid_contract", "invalid_now", "too_large"]

_MAX_MESSAGE_LENGTH: Final = 200


class DataContractError(Exception):
    """Base class of every error raised by this library.

    Attributes:
        code: Stable machine-readable error code.
    """

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message[:_MAX_MESSAGE_LENGTH])
        self.code: ErrorCode = code


class ContractError(DataContractError):
    """Raised when a contract is invalid.

    Attributes:
        problems: Every problem found, each at most 200 characters, never a cell value.
    """

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems: list[str] = [problem[:_MAX_MESSAGE_LENGTH] for problem in problems]
        summary = f"invalid data contract: {len(self.problems)} problem(s)"
        if self.problems:
            summary = f"{summary}; first: {self.problems[0]}"
        super().__init__("invalid_contract", summary)
