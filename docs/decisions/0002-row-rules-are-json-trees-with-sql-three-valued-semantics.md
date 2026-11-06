# Row rules are JSON trees with SQL three-valued semantics

Status: accepted (generated, pending human review)

## Context

Data contracts need cross-column checks such as start_date <= end_date. Evaluating user-supplied expression strings with eval is unsafe. Using a different null semantics from SQL CHECK constraints would surprise data engineers, because a null end_date would suddenly fail a rule that a warehouse accepts.

## Decision

Row rules are JSON expression trees (eq, ne, lt, lte, gt, gte, and, or, not, is_null) that are parsed into a normalized copy with a depth limit of 32 and a node limit of 1000, and then interpreted. Evaluation is three-valued: a comparison with null or with mismatched kinds is unknown, and/or/not follow Kleene logic, and only false is a violation. Contracts are trusted and data is untrusted, so patterns are length-limited at 256 characters and applied only to values up to 10 000 characters. The library depends only on the standard library.

## Consequences

Rules cannot execute code and cannot recurse without bound. A null cell never trips a rule by itself, and authors who want to forbid nulls must say so with not/is_null or nullable=false. Rule literals are JSON scalars, so comparing a date column to a literal date string is unknown; two columns, or a typed value, must be used instead. Regular expression backtracking on hostile patterns remains the contract author's responsibility and is documented in the threat model.
