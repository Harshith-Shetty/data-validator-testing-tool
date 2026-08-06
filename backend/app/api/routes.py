"""REST API for the data capture validation screen."""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from .. import ingest, storage
from ..models import (
    DatasetSummary,
    FileRole,
    RunSummary,
    TestConfig,
    TestCreate,
    TestUpdate,
    ValidationTest,
    utcnow,
)
from ..validation.engine import ValidationError, run_validation
from ..validation.suggest import suggest_config

router = APIRouter(prefix="/api")

MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _require_test(test_id: str) -> ValidationTest:
    test = storage.get_test(test_id)
    if test is None:
        raise HTTPException(status_code=404, detail=f"Test '{test_id}' not found")
    return test


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "time": utcnow()}


# --------------------------------------------------------------------------- tests


@router.get("/tests", response_model=list[ValidationTest])
def list_tests() -> list[ValidationTest]:
    return storage.list_tests()


@router.post("/tests", response_model=ValidationTest, status_code=201)
def create_test(payload: TestCreate) -> ValidationTest:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Test name is required")
    test = ValidationTest(id=storage.new_id("test"), name=name, description=payload.description)
    return storage.save_test(test)


@router.get("/tests/{test_id}", response_model=ValidationTest)
def get_test(test_id: str) -> ValidationTest:
    return _require_test(test_id)


@router.patch("/tests/{test_id}", response_model=ValidationTest)
def update_test(test_id: str, payload: TestUpdate) -> ValidationTest:
    test = _require_test(test_id)
    if payload.name is not None:
        test.name = payload.name.strip() or test.name
    if payload.description is not None:
        test.description = payload.description
    test.updated_at = utcnow()
    return storage.save_test(test)


@router.delete("/tests/{test_id}", status_code=204, response_model=None)
def delete_test(test_id: str) -> None:
    if not storage.delete_test(test_id):
        raise HTTPException(status_code=404, detail=f"Test '{test_id}' not found")


# ------------------------------------------------------------------------ datasets


@router.post("/tests/{test_id}/files/{role}", response_model=ValidationTest)
async def upload_file(test_id: str, role: FileRole, file: UploadFile = File(...)) -> ValidationTest:
    test = _require_test(test_id)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 100 MB upload limit")

    try:
        dataset = ingest.parse_upload(file.filename or f"{role.value}.csv", content)
    except ingest.IngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    storage.save_dataset(test_id, role.value, dataset)
    test.datasets[role.value] = DatasetSummary(
        role=role,
        filename=dataset["filename"],
        columns=dataset["columns"],
        row_count=dataset["row_count"],
        uploaded_at=dataset["uploaded_at"],
        preview=ingest.preview(dataset),
    )
    # Re-suggest anything the user has not pinned down yet.
    test.config = suggest_config(*_load_datasets(test_id), current=test.config)
    test.updated_at = utcnow()
    return storage.save_test(test)


@router.get("/tests/{test_id}/files/{role}")
def get_dataset(
    test_id: str,
    role: FileRole,
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    _require_test(test_id)
    dataset = storage.load_dataset(test_id, role.value)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"No '{role.value}' file uploaded yet")
    rows = dataset["rows"]
    return {
        "role": role.value,
        "filename": dataset["filename"],
        "columns": dataset["columns"],
        "row_count": dataset["row_count"],
        "uploaded_at": dataset["uploaded_at"],
        "rows": rows[offset : offset + limit],
    }


def _load_datasets(test_id: str) -> tuple[dict | None, dict | None, dict | None]:
    return (
        storage.load_dataset(test_id, FileRole.BEFORE.value),
        storage.load_dataset(test_id, FileRole.AFTER.value),
        storage.load_dataset(test_id, FileRole.DELTA.value),
    )


# --------------------------------------------------------------------------- config


@router.put("/tests/{test_id}/config", response_model=ValidationTest)
def set_config(test_id: str, config: TestConfig) -> ValidationTest:
    test = _require_test(test_id)
    test.config = config
    test.updated_at = utcnow()
    return storage.save_test(test)


@router.post("/tests/{test_id}/config/suggest", response_model=TestConfig)
def suggest(test_id: str) -> TestConfig:
    _require_test(test_id)
    return suggest_config(*_load_datasets(test_id), current=None)


# ----------------------------------------------------------------------------- runs


@router.post("/tests/{test_id}/run", response_model=RunSummary)
def run_test(test_id: str) -> RunSummary:
    test = _require_test(test_id)
    before, after, delta = _load_datasets(test_id)
    missing = [
        role
        for role, dataset in (("before", before), ("current", after), ("delta", delta))
        if dataset is None
    ]
    if missing:
        raise HTTPException(
            status_code=422, detail=f"Upload the {', '.join(missing)} file before running"
        )

    try:
        result = run_validation(before, after, delta, test.config)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    run_id = storage.new_id("run")
    result["summary"]["run_id"] = run_id
    result["summary"]["test_id"] = test_id
    storage.save_run(test_id, run_id, result)

    summary = RunSummary.model_validate(result["summary"])
    test.last_run = summary
    test.updated_at = utcnow()
    storage.save_test(test)
    return summary


@router.get("/tests/{test_id}/runs", response_model=list[RunSummary])
def list_runs(test_id: str) -> list[RunSummary]:
    _require_test(test_id)
    return [RunSummary.model_validate(s) for s in storage.list_runs(test_id)]


@router.get("/tests/{test_id}/runs/{run_id}")
def get_run(
    test_id: str,
    run_id: str,
    status: str | None = Query(default=None, description="PASS | FAIL | WARN"),
    row_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=20000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    _require_test(test_id)
    run = storage.load_run(test_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    rows = _filter_rows(run["rows"], status, row_type, search)
    return {
        "summary": run["summary"],
        "columns": run["columns"],
        "total": len(rows),
        "rows": rows[offset : offset + limit],
    }


def _filter_rows(
    rows: list[dict[str, Any]], status: str | None, row_type: str | None, search: str | None
) -> list[dict[str, Any]]:
    filtered = rows
    if status:
        wanted = {s.strip().upper() for s in status.split(",") if s.strip()}
        filtered = [r for r in filtered if r["rowStatus"] in wanted]
    if row_type:
        wanted_types = {t.strip().upper() for t in row_type.split(",") if t.strip()}
        filtered = [r for r in filtered if r["rowType"] in wanted_types]
    if search:
        needle = search.casefold()
        filtered = [r for r in filtered if _row_matches(r, needle)]
    return filtered


def _row_matches(row: dict[str, Any], needle: str) -> bool:
    if needle in row["key"].casefold():
        return True
    return any(
        needle in str(cell["before"]).casefold() or needle in str(cell["after"]).casefold()
        for cell in row["cells"].values()
    )


@router.get("/tests/{test_id}/runs/{run_id}/export")
def export_run(test_id: str, run_id: str, status: str | None = Query(default=None)):
    _require_test(test_id)
    run = storage.load_run(test_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    rows = _filter_rows(run["rows"], status, None, None)
    columns: list[str] = run["columns"]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    header = ["key", "row_status", "row_type"]
    for column in columns:
        header += [f"{column} (before)", f"{column} (current)", f"{column} (result)"]
    header.append("messages")
    writer.writerow(header)

    for row in rows:
        record = [row["key"], row["rowStatus"], row["rowType"]]
        for column in columns:
            cell = row["cells"].get(column, {})
            record += [
                cell.get("before", ""),
                cell.get("after", ""),
                f"{cell.get('status', '')}:{cell.get('code', '')}",
            ]
        record.append(" | ".join(row.get("messages", [])))
        writer.writerow(record)

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.csv"'},
    )
