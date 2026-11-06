# Contract format and threat model

`data_contract` validates tabular rows against a JSON contract. It uses only the Python standard library.

## Contract

```json
{
  "name": "users",
  "version": "1.0.0",
  "columns": [
    {"name": "id", "type": "integer", "unique": true, "min": 1},
    {"name": "email", "type": "string", "pattern": "[^@ ]+@[^@ ]+"},
    {"name": "updated_at", "type": "datetime"}
  ],
  "allow_extra_columns": true,
  "min_rows": 1,
  "rules": [{"id": "ordered", "expr": {"lte": [{"col": "start"}, {"col": "end"}]}}],
  "freshness": {"column": "updated_at", "max_age": "PT24H"}
}
```

Column types are `string`, `integer`, `number`, `boolean`, `date` and `datetime`. Column options are `required` (default true), `nullable` (default false), `unique`, `enum`, `min`, `max` and `pattern`. `min` and `max` apply to integer, number, date and datetime columns, and `enum` is not allowed on date and datetime columns. Unknown keys are rejected. `load_contract` reports every problem at once in `ContractError.problems`.

## Row rules

Rules are JSON trees and are never passed to `eval`. The operators are `eq`, `ne`, `lt`, `lte`, `gt`, `gte` (two operands each), `and`, `or` (non-empty lists), `not`, and `is_null`. An operand is `{"col": name}` or a JSON literal. A tree may be at most 32 levels deep (the root is level 1) and have at most 1000 nodes.

Evaluation is three-valued, as in SQL. A comparison with a null, or between values of different kinds, is unknown. `and`, `or` and `not` follow Kleene logic. Only `false` is a violation, matching SQL `CHECK` semantics. Kinds are boolean, number, string, date and datetime. Literals are JSON values, so they compare only with booleans, numbers and strings. Naive datetimes are treated as UTC.

## Validation semantics

- Rows are streamed once. `row_count` counts every row, even after the violation list is truncated at `max_violations`.
- A column is present if any row has its key. A required column that no row has gives one `schema` violation. An empty dataset skips these presence checks. A key missing from some rows of a required column gives a row-level `schema` violation.
- With `coerce=True`, strings are parsed by ASCII-only rules and are never stripped. `42` is an integer, while ` 42`, `42.0` and Arabic-Indic digits are not. Non-strings are checked as Python types: `bool` is not an integer, and `1.0` is a number but not an integer.
- Patterns use `re.fullmatch`, are at most 256 characters, and are applied only to string cells. Strings longer than 10 000 characters fail the pattern.
- `max_age` is the ISO 8601 subset `PnDTnHnMnS`. Years and months are rejected because their length varies. A freshness column with no parsable value fails.
- Messages carry column names and row indexes, never cell values. Unexpected column names are escaped and clipped.

## Threat model

Contracts are trusted input. Data rows and CSV files are untrusted.

- Resource limits: contract files are limited to 1 MiB by default, rules to 32 levels and 1000 nodes, patterns to 256 characters, and violations, unique values and extra column names are all capped.
- Regular expressions come from the contract author, so a pathological pattern is the contract author's responsibility. The 10 000 character limit bounds the cost for data values. The Python `re` engine can still backtrack, so do not accept patterns from untrusted parties.
- The library never logs cell values and never configures logging. Its logger has a `NullHandler`.
- Out of scope: warehouses, YAML and Bitol ODCS, drift detection and schema evolution.
