# Testing

## Running

```sh
uv run pytest --cov=data_contract   # tests with coverage report
uv run python scripts/check.py      # every gate, as CI runs it
```

## Policy

- Branch coverage of `src/data_contract` must stay at or above 80 %; the gate fails below it.
- Tests exercise the public API (`import data_contract`) and assert observable effects: return values, raised exceptions and their messages.
- Each bug fix starts with a failing test that reproduces it.
- Tests are deterministic: no network, no wall clock, no dependence on test order.

## Layout

`tests/test_<module>.py` mirrors each public module. Shared fixtures go in `tests/conftest.py`.

The acceptance cases the specification requires include: a matching three-row dataset passes; a missing required column yields a `schema` violation; type, nullable, enum, range and pattern failures yield their rule names without cell values; a repeated value in a unique column reports `unique` at the second occurrence; row rules treat null as unknown; the freshness boundary at `PT24H`; `max_violations` truncation; contract problem counting; and a byte-exact golden file for `render(report, 'json')`.
