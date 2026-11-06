"""Validate tabular datasets against a JSON data contract."""

from __future__ import annotations

import logging

from .contract import ColumnSpec, Contract, FreshnessSpec, RowRule, load_contract
from .csvio import read_csv_rows
from .errors import ContractError, DataContractError
from .rendering import render
from .validation import FreshnessResult, ValidationReport, Violation, validate

__all__ = [
    "ColumnSpec",
    "Contract",
    "ContractError",
    "DataContractError",
    "FreshnessResult",
    "FreshnessSpec",
    "RowRule",
    "ValidationReport",
    "Violation",
    "__version__",
    "load_contract",
    "read_csv_rows",
    "render",
    "validate",
]

__version__ = "0.1.0"

logging.getLogger(__name__).addHandler(logging.NullHandler())
