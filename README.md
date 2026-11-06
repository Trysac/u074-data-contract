# data-contract

[![PyPI version](https://img.shields.io/pypi/v/trysac-data-contract)](https://pypi.org/project/trysac-data-contract/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-data-contract)](LICENSE)
[![CI](https://github.com/Trysac/u074-data-contract/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u074-data-contract/actions/workflows/ci.yml)

Validate tabular datasets against a JSON data contract: schema, types, ranges, uniqueness, SQL-style row rules and a freshness SLA with an injected clock.

## Problem

Pipelines break silently when an upstream team renames a column, sends nulls or stops refreshing a table, and the problem shows up in a dashboard days later. Full data-quality platforms need warehouses and servers. This small validator runs in CI or at ingestion and reports such failures clearly.

## Install

```sh
pip install trysac-data-contract
# or
uv add trysac-data-contract
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
from datetime import datetime, timezone
from pathlib import Path

from data_contract import load_contract, read_csv_rows, render, validate

contract = load_contract(Path("contract.json"))  # raises ContractError listing every problem
report = validate(
    read_csv_rows(Path("data.csv")),
    contract,
    now=datetime.now(timezone.utc),  # injected, timezone-aware clock
    coerce=True,  # parse CSV strings per column type
)
print(render(report, "text"))  # or render(report, "json")
```

See [the contract format](docs/CONTRACT_FORMAT.md) for columns, row rules and freshness.

## Public API

- `load_contract(source, *, max_bytes=1_048_576) -> Contract`: `source` is a `pathlib.Path` to a UTF-8 JSON file or a mapping. Raises `ContractError` (code `invalid_contract`, `problems` lists every problem) or `DataContractError` (code `too_large`).
- `validate(rows, contract, *, now, max_violations=1000, coerce=False, max_unique_values=1_000_000) -> ValidationReport`: streams rows once. `now` must be timezone-aware, otherwise `DataContractError` with code `invalid_now`. `row_count` counts every row even after truncation.
- `read_csv_rows(path, *, encoding='utf-8-sig') -> Iterator[dict[str, str]]`: blank lines are skipped; cells are never stripped or converted.
- `render(report, fmt) -> str`: `'text'` or `'json'` (sorted keys, indent 2, no trailing newline). Other values raise `ValueError`.
- Violation rules: `schema`, `min_rows`, `type`, `nullable`, `enum`, `range`, `pattern`, `unique`, `row_rule`, `freshness`.
- Limits: row rules at most depth 32 and 1000 nodes; patterns at most 256 characters, applied to values up to 10,000 characters; `max_age` uses the ISO 8601 subset `PnDTnHnMnS` (no years or months).
- Options: `coerce` parses CSV strings per column type (integer, number, boolean, date, datetime); `allow_extra_columns` on the contract; `max_unique_values` bounds uniqueness tracking.

Trust model: contracts are trusted input; data rows are untrusted. Messages carry row indexes and column names, never cell values. See [security notes](docs/SECURITY.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
