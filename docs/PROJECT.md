# Project record

## Objective

Provide a small, dependency-free validator that checks tabular datasets against a JSON data contract (schema, types, ranges, uniqueness, SQL-style row rules and a freshness SLA with an injected clock), so that pipeline failures are reported clearly in CI or at ingestion.

## Scope

- In scope: the public API documented in [README.md](../README.md), typed and tested: contract loading, streaming validation, CSV reading and text or JSON rendering.
- Out of scope: warehouses, YAML and Bitol ODCS contract formats, drift detection and schema evolution. Anything that needs runtime dependencies or I/O beyond reading a contract file and a CSV file requires an accepted ADR.

## Timeline

| Date | Event |
|---|---|
| 2026 | Repository created from the factory utility template. |

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 485304 / 253723 |
| Hours (human) | pending measurement |
| Cost (USD) | 1.5679 |

## Factory run u074 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | claude-sonnet-5-5 | yes | 2261 | 128000 | 0 | 4246 | 0.6427 |
| generation | claude-sonnet-5-5 | yes | 2261 | 112849 | 0 | 4246 | 0.5669 |
| fix-1 | claude-sonnet-5-5 | no | 4 | 584 | 6588 | 25307 | 0.0248 |
| fix-2 | claude-sonnet-5-5 | no | 8 | 909 | 6470 | 55018 | 0.0308 |
| audit | claude-sonnet-5-5 | no | 16 | 6587 | 47087 | 222395 | 0.2059 |
| fix-3 | claude-sonnet-5-5 | no | 0 | 0 | 0 | 0 | 0.0000 |
| docs | claude-haiku-5-5 | no | 169542 | 4794 | 0 | 0 | 0.0968 |

Total: $1.5679. Prices: Anthropic list prices.
