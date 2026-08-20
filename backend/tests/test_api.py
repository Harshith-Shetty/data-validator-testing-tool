"""End-to-end API flow: create a test, upload three files, run it, read results."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SAMPLES = Path(__file__).resolve().parents[2] / "sample-data"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DVT_STORAGE_DIR", str(tmp_path))
    import importlib

    from app import storage

    importlib.reload(storage)
    from app import main

    importlib.reload(main)
    with TestClient(main.app) as test_client:
        yield test_client


def upload(client, test_id: str, role: str, filename: str):
    content = (SAMPLES / filename).read_bytes()
    return client.post(
        f"/api/tests/{test_id}/files/{role}",
        files={"file": (filename, content, "text/csv")},
    )


def test_full_flow(client):
    created = client.post("/api/tests", json={"name": "Daily capture", "description": "smoke"})
    assert created.status_code == 201
    test_id = created.json()["id"]

    for role, filename in (("before", "before.csv"), ("after", "after.csv"), ("delta", "delta.csv")):
        response = upload(client, test_id, role, filename)
        assert response.status_code == 200, response.text

    test = response.json()
    assert test["datasets"]["before"]["row_count"] == 3
    # Config was auto-detected from the uploads.
    assert test["config"]["key_columns"] == ["Id"]
    assert test["config"]["delta_key_columns"] == ["Issuer"]
    assert test["config"]["last_modified_column"] == "last modified"

    run = client.post(f"/api/tests/{test_id}/run")
    assert run.status_code == 200, run.text
    summary = run.json()
    assert summary["status"] == "FAIL"
    assert summary["rows_failed"] == 1

    results = client.get(f"/api/tests/{test_id}/runs/{summary['run_id']}")
    assert results.status_code == 200
    body = results.json()
    assert body["total"] == 3
    assert body["columns"] == ["Id", "att1", "last modified"]

    failed_only = client.get(
        f"/api/tests/{test_id}/runs/{summary['run_id']}", params={"status": "FAIL"}
    ).json()
    assert failed_only["total"] == 1
    assert failed_only["rows"][0]["key"] == "1"

    searched = client.get(
        f"/api/tests/{test_id}/runs/{summary['run_id']}", params={"search": "india"}
    ).json()
    assert searched["total"] == 1

    export = client.get(f"/api/tests/{test_id}/runs/{summary['run_id']}/export")
    assert export.status_code == 200
    assert "row_status" in export.text

    listed = client.get(f"/api/tests/{test_id}/runs").json()
    assert len(listed) == 1


def test_run_requires_all_three_files(client):
    test_id = client.post("/api/tests", json={"name": "incomplete"}).json()["id"]
    upload(client, test_id, "before", "before.csv")
    response = client.post(f"/api/tests/{test_id}/run")
    assert response.status_code == 422
    assert "current" in response.json()["detail"]


def test_config_can_be_overridden(client):
    test_id = client.post("/api/tests", json={"name": "custom"}).json()["id"]
    for role, filename in (("before", "before.csv"), ("after", "after.csv"), ("delta", "delta.csv")):
        upload(client, test_id, role, filename)

    strict = client.post(f"/api/tests/{test_id}/run").json()
    # The feed re-sent 'uk' for issuer 1 but the record became 'india'.
    assert strict["issues_by_code"].get("UNEXPECTED_CHANGE") == 1
    assert strict["status"] == "FAIL"

    config = client.get(f"/api/tests/{test_id}").json()["config"]
    config["strict_unlisted_columns"] = False
    assert client.put(f"/api/tests/{test_id}/config", json=config).status_code == 200

    relaxed = client.post(f"/api/tests/{test_id}/run").json()
    # Downgraded to a warning, but the regressed timestamp still fails the run.
    assert relaxed["cells_warned"] == 1
    assert relaxed["issues_by_code"].get("TIMESTAMP_REGRESSED") == 1


def test_rejects_unsupported_file_type(client):
    test_id = client.post("/api/tests", json={"name": "bad upload"}).json()["id"]
    response = client.post(
        f"/api/tests/{test_id}/files/before",
        files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 422


def test_missing_test_returns_404(client):
    assert client.get("/api/tests/test_does_not_exist").status_code == 404


def test_delete_test(client):
    test_id = client.post("/api/tests", json={"name": "temp"}).json()["id"]
    assert client.delete(f"/api/tests/{test_id}").status_code == 204
    assert client.get(f"/api/tests/{test_id}").status_code == 404
