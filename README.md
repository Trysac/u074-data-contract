# data-contract

[![PyPI version](https://img.shields.io/pypi/v/trysac-data-contract)](https://pypi.org/project/trysac-data-contract/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-data-contract)](LICENSE)
[![CI](https://github.com/Trysac/u074-data-contract/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u074-data-contract/actions/workflows/ci.yml)

Validate tabular datasets against a JSON data contract: schema, types, ranges, uniqueness, SQL-style row rules and a freshness SLA with an injected clock

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-data-contract
# or
uv add trysac-data-contract
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import data_contract

# normalize() trims surrounding whitespace and lower-cases the text.
print(data_contract.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    data_contract.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
