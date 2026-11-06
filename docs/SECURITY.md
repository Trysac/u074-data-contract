# Security notes

## Threat model

`trysac-data-contract` has no network access and no runtime dependencies. Its only I/O is reading a contract file (`load_contract`, limited by `max_bytes`, default 1 MiB) and a CSV file (`read_csv_rows`). Contracts are trusted input; data rows are untrusted.

### Defended

- **Code injection from contracts or data**: row rules are JSON trees parsed without `eval`; `exec` and untrusted deserialization are not used.
- **Oversized contracts**: files above `max_bytes` raise `DataContractError` with code `too_large`.
- **Deep or large rule trees**: rule depth is limited to 32 and node count to 1000.
- **Pathological patterns**: patterns are limited to 256 characters and applied only to string values up to 10,000 characters; longer values fail the pattern instead of being matched.
- **Oversized CSV fields**: fields beyond the csv module limit raise `DataContractError` with code `too_large`.
- **Data leakage through errors**: messages carry row indexes and column names, never cell values.
- **Non-finite JSON numbers**: `NaN` and `Infinity` in contracts are rejected.
- **Memory growth in uniqueness checks**: each unique column tracks at most `max_unique_values` values (default 1,000,000); beyond that the column stops being checked and one violation is reported.

### Not defended

- **Resource exhaustion by very large datasets**: `validate` streams rows but per-column uniqueness sets can still grow up to the configured limit per column. Callers must bound input size.
- **Regular-expression cost below the length limits**: a pattern of up to 256 characters can still be expensive on values of up to 10,000 characters; the library does not enforce a time budget.
- **Malicious contracts**: contracts are trusted; a hostile contract file is not sandboxed.
- **Symlink and path policy**: the library opens the path it is given and does not restrict where it points.
- **Timezone-naive data**: naive datetimes in data are treated as UTC, which may hide a mismatch with the caller's expectation.

## Supply chain

No runtime dependencies. Dependabot weekly updates, actions pinned to major versions, minimal workflow permissions, and `gitleaks` in the local gates and in CI.

## Publishing

Releases are published to PyPI with trusted publishing (OIDC) when available, never with a long-lived token stored in the repository.

To report a vulnerability, see [SECURITY.md](../SECURITY.md).
