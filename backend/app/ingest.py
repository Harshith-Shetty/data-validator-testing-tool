"""Spreadsheet ingestion: CSV/XLSX bytes -> plain JSON-serialisable rows."""

from __future__ import annotations

import csv
import io
import logging
import time
from typing import Any

import pandas as pd

from .models import utcnow

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = (".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls")
PREVIEW_ROWS = 10


class IngestError(ValueError):
    """Raised when an uploaded file cannot be parsed into a table."""


def _sniff_delimiter(content: bytes) -> str | None:
    sample = content[:65536].decode("utf-8", errors="ignore")
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return None


def _read_frame(filename: str, content: bytes) -> pd.DataFrame:
    lower = filename.lower()
    try:
        if lower.endswith((".xlsx", ".xlsm", ".xls")):
            return pd.read_excel(io.BytesIO(content), dtype=object)

        sep = "\t" if lower.endswith(".tsv") else (_sniff_delimiter(content) or ",")

        try:
            # pandas' default C engine is many times faster than the python
            # engine `sep=None` forces for delimiter-sniffing, so sniff the
            # delimiter ourselves first and only fall back to that slower,
            # more forgiving engine if the quick guess was wrong.
            frame = pd.read_csv(io.BytesIO(content), dtype=object, sep=sep, skipinitialspace=True)
            if frame.shape[1] > 1 or sep == "\t":
                return frame
        except Exception:
            pass  # fall through to the slower, more forgiving parser below

        return pd.read_csv(
            io.BytesIO(content), dtype=object, sep=None, engine="python", skipinitialspace=True
        )
    except Exception as exc:  # pragma: no cover - surfaced to the user verbatim
        raise IngestError(f"Could not parse '{filename}': {exc}") from exc


def parse_upload(filename: str, content: bytes) -> dict[str, Any]:
    """Parse an upload into the dataset document persisted under datasets/."""

    if not filename.lower().endswith(SUPPORTED_SUFFIXES):
        raise IngestError(
            f"Unsupported file type '{filename}'. Expected one of: {', '.join(SUPPORTED_SUFFIXES)}"
        )

    started = time.time()
    logger.info("Parsing '%s' (%.1f KB)...", filename, len(content) / 1024)

    frame = _read_frame(filename, content)
    frame.columns = [str(c).strip() for c in frame.columns]
    frame = frame.loc[:, [c for c in frame.columns if c and not c.startswith("Unnamed:")]]

    if frame.empty and not len(frame.columns):
        raise IngestError(f"'{filename}' contains no columns.")

    # NaN/NaT are not valid JSON, so normalise every blank to None.
    frame = frame.astype(object).where(pd.notna(frame), None)
    columns = list(frame.columns)
    # itertuples() is noticeably faster than to_dict(orient="records") on a
    # wide/large frame, since the latter builds an intermediate structure
    # pandas has to walk generically rather than iterating the raw values.
    rows = [
        {column: _jsonable(value) for column, value in zip(columns, record)}
        for record in frame.itertuples(index=False, name=None)
    ]

    elapsed_ms = int((time.time() - started) * 1000)
    logger.info(
        "Parsed '%s': %d rows, %d columns (%d ms)", filename, len(rows), len(frame.columns), elapsed_ms
    )

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
