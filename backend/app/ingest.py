"""Spreadsheet ingestion: CSV/XLSX bytes -> plain JSON-serialisable rows."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd

from .models import utcnow

SUPPORTED_SUFFIXES = (".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls")
PREVIEW_ROWS = 10


class IngestError(ValueError):
    """Raised when an uploaded file cannot be parsed into a table."""


def _read_frame(filename: str, content: bytes) -> pd.DataFrame:
    lower = filename.lower()
    try:
        if lower.endswith((".xlsx", ".xlsm", ".xls")):
            return pd.read_excel(io.BytesIO(content), dtype=object)
        sep = "\t" if lower.endswith(".tsv") else None
        # sep=None asks the python engine to sniff the delimiter.
        return pd.read_csv(
            io.BytesIO(content),
            dtype=object,
            sep=sep,
            engine="python",
            skipinitialspace=True,
        )
    except Exception as exc:  # pragma: no cover - surfaced to the user verbatim
        raise IngestError(f"Could not parse '{filename}': {exc}") from exc


def parse_upload(filename: str, content: bytes) -> dict[str, Any]:
    """Parse an upload into the dataset document persisted under datasets/."""

    if not filename.lower().endswith(SUPPORTED_SUFFIXES):
        raise IngestError(
            f"Unsupported file type '{filename}'. Expected one of: {', '.join(SUPPORTED_SUFFIXES)}"
        )

    frame = _read_frame(filename, content)
    frame.columns = [str(c).strip() for c in frame.columns]
    frame = frame.loc[:, [c for c in frame.columns if c and not c.startswith("Unnamed:")]]

    if frame.empty and not len(frame.columns):
        raise IngestError(f"'{filename}' contains no columns.")

    # NaN/NaT are not valid JSON, so normalise every blank to None.
    frame = frame.astype(object).where(pd.notna(frame), None)
    rows = frame.to_dict(orient="records")
    rows = [{k: _jsonable(v) for k, v in row.items()} for row in rows]

    return {
        "filename": filename,
        "columns": list(frame.columns),
        "row_count": len(rows),
        "uploaded_at": utcnow(),
        "rows": rows,
    }


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ")
    return str(value)


def preview(dataset: dict[str, Any], limit: int = PREVIEW_ROWS) -> list[dict[str, Any]]:
    return dataset.get("rows", [])[:limit]
