"""JSON-file storage.

Uploaded spreadsheets are parsed once and persisted as JSON so that opening a
test later never re-parses a CSV/XLSX. Layout:

    storage/
      tests/<test_id>/test.json
      tests/<test_id>/datasets/<role>.json
      tests/<test_id>/runs/<run_id>.json
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from .models import ValidationTest

STORAGE_ROOT = Path(os.environ.get("DVT_STORAGE_DIR", Path(__file__).resolve().parents[1] / "storage"))


def _tests_dir() -> Path:
    return STORAGE_ROOT / "tests"


def test_dir(test_id: str) -> Path:
    return _tests_dir() / test_id


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, default=str)
    tmp.replace(path)


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- tests


def list_tests() -> list[ValidationTest]:
    root = _tests_dir()
    if not root.exists():
        return []
    tests = []
    for entry in root.iterdir():
        meta = entry / "test.json"
        if meta.exists():
            tests.append(ValidationTest.model_validate(_read_json(meta)))
    return sorted(tests, key=lambda t: t.created_at, reverse=True)


def get_test(test_id: str) -> ValidationTest | None:
    meta = test_dir(test_id) / "test.json"
    if not meta.exists():
        return None
    return ValidationTest.model_validate(_read_json(meta))


def save_test(test: ValidationTest) -> ValidationTest:
    _write_json(test_dir(test.id) / "test.json", test.model_dump(mode="json"))
    return test


def delete_test(test_id: str) -> bool:
    target = test_dir(test_id)
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


# ------------------------------------------------------------------------ datasets


def save_dataset(test_id: str, role: str, payload: dict[str, Any]) -> None:
    _write_json(test_dir(test_id) / "datasets" / f"{role}.json", payload)


def load_dataset(test_id: str, role: str) -> dict[str, Any] | None:
    path = test_dir(test_id) / "datasets" / f"{role}.json"
    if not path.exists():
        return None
    return _read_json(path)


# ---------------------------------------------------------------------------- runs


def save_run(test_id: str, run_id: str, payload: dict[str, Any]) -> None:
    _write_json(test_dir(test_id) / "runs" / f"{run_id}.json", payload)


def load_run(test_id: str, run_id: str) -> dict[str, Any] | None:
    path = test_dir(test_id) / "runs" / f"{run_id}.json"
    if not path.exists():
        return None
    return _read_json(path)


def list_runs(test_id: str) -> list[dict[str, Any]]:
    runs_dir = test_dir(test_id) / "runs"
    if not runs_dir.exists():
        return []
    summaries = [_read_json(p).get("summary", {}) for p in runs_dir.glob("*.json")]
    return sorted(summaries, key=lambda s: s.get("started_at", ""), reverse=True)
