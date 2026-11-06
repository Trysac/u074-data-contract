"""Streaming CSV reader that yields rows ready for validate()."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from .errors import DataContractError


def read_csv_rows(path: Path | str, *, encoding: str = "utf-8-sig") -> Iterator[dict[str, str]]:
    """Yield each CSV data row as a ``{header: cell}`` dict, one row at a time.

    Blank lines are skipped. A short row simply lacks its trailing keys; cells beyond the
    header are ignored. Cells are never stripped or converted.

    Raises:
        DataContractError: with code ``too_large`` when a field exceeds the csv module's
            field size limit (131072 characters by default).
        OSError: when the file cannot be opened.
    """
    with Path(path).open(newline="", encoding=encoding) as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader, None)
            if header is None:
                return
            for cells in reader:
                if not cells:
                    continue
                yield dict(zip(header, cells, strict=False))
        except csv.Error as exc:
            if "field larger than field limit" in str(exc):
                raise DataContractError(
                    "too_large", "CSV field exceeds the parser field size limit"
                ) from exc
            raise
