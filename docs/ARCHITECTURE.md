# Architecture

## Purpose

`trysac-data-contract` is a small, dependency-free Python library (standard library only, Python 3.10+) that validates tabular datasets against a JSON data contract: schema, types, ranges, uniqueness, SQL-style row rules and a freshness SLA with an injected clock.

## Shape

```text
caller code --> data_contract (public API in __init__.py)
                    |
                    +-- contract.py    contract model and JSON loader (no eval)
                    +-- rules.py       row-rule parser and three-valued evaluator
                    +-- validation.py  streaming validation of rows against a Contract
                    +-- csvio.py       streaming CSV reader
                    +-- rendering.py   text and JSON rendering of a report
                    +-- _values.py     type checks, coercion, comparison kinds
                    +-- errors.py      DataContractError and ContractError
```

- **Public API**: the names listed in `__all__` of `src/data_contract/__init__.py`. Anything else is internal and may change without a major version.
- **Errors**: `ContractError` and `DataContractError` carry a stable `code`; bad arguments raise `ValueError` or `TypeError`. The library never prints or exits.
- **Logging**: a module logger with a `NullHandler`; the library never configures logging.
- **Side effects**: `load_contract` and `read_csv_rows` read files; `validate` and `render` are pure functions of their inputs. The clock is injected through `now`.

## Quality contract

`scripts/check.py` is the gate definition used by CI. See [TESTING.md](TESTING.md).

## Decisions

Architecture decisions are recorded in [decisions/](decisions/) as numbered ADRs.
