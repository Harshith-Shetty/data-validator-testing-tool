# Data Validator Testing Tool

A dashboard for running data validations. The first screen is **data capture
validation**: you upload three files and the tool tells you, cell by cell,
whether a capture run changed the data the way it was supposed to.

- **Before data** — the snapshot as it looked before the capture run
- **Current data** — the snapshot as it looks now
- **Delta file** — the changes the run was supposed to apply

Every cell in the results grid is coloured: **green** when it is where it should
be (correctly updated, or correctly left alone) and **red** when it is not
(update never landed, landed with the wrong value, or something moved that
nobody asked to move).

```
Python + FastAPI            Angular + ag-Grid
┌──────────────────┐        ┌──────────────────────┐
│ upload → parse   │        │ dashboard (tests)    │
│ CSV/XLSX → JSON  │◀──────▶│ setup   (uploads +   │
│ validation engine│  REST  │          mapping)    │
│ runs → JSON      │        │ results (ag-Grid)    │
└──────────────────┘        └──────────────────────┘
```

Uploads are parsed once and stored as JSON under `backend/storage/`, so
reopening a test never re-parses a spreadsheet.

## Running it

```bash
./scripts/dev.sh          # installs deps on first run, then starts both
```

- Dashboard: <http://localhost:4200>
- API + OpenAPI docs: <http://localhost:8000/docs>

Or start the halves separately:

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000

cd frontend && npm install && npm start     # proxies /api to :8000
```

Tests:

```bash
cd backend && .venv/bin/python -m pytest      # 20 tests: engine rules + API flow
cd frontend && npm run build
```

## Try it with the sample data

`sample-data/` holds the worked example:

| before.csv | | | | after.csv | | | | delta.csv | |
|---|---|---|---|---|---|---|---|---|---|
| **Id** | **last modified** | **att1** | | **Id** | **last modified** | **att1** | | **Issuer** | **country** |
| 1 | 2026-08-02 12:23:00 | uk | | 1 | 2026-08-01 14:02:00 | india | | 1 | uk |
| 2 | 2026-05-01 15:56:00 | usa | | 2 | 2026-05-01 15:56:00 | usa | | 3 | usa |
| 3 | 2026-04-28 06:45:00 | Australia | | 3 | 2026-08-01 14:02:00 | usa | | | |

New test → drop the three files → **Run validation**. The result:

- **Row 1 — FAIL.** The delta asked for `uk`, the capture wrote `india`, and the
  last-modified timestamp went *backwards*. Two red cells.
- **Row 2 — PASS.** Not in the delta, and nothing moved. Green.
- **Row 3 — PASS.** Updated to `usa` as requested, with the timestamp bumped
  forward. Green.

## How the files are lined up

The delta file rarely uses the same column names as the data (`Issuer` for
`Id`, `country` for `att1`), so the backend auto-detects the mapping on upload
by combining name similarity with how well the actual values overlap. Every
guess is editable on the test setup screen:

- **Key column** in the data, and the column that matches it in the delta
- **Last modified column** (optional)
- **Columns to compare**
- **Delta column → data column** mapping

### What the delta file means

Your example is ambiguous on one point — for issuer 1 the delta value (`uk`)
is the *old* value, while for issuer 3 (`usa`) it is the *new* one. Rather than
guess, the mode is a setting:

| Mode | The delta value is… | A cell passes when |
|---|---|---|
| `new_value` *(default)* | the value the current file should now show | current == delta value |
| `old_value` | the value the row moved away from | the value changed, and the before file matches the delta value |
| `presence_only` | ignored — the delta only marks which rows/columns should have moved | the value changed |

## The rules

| Verdict | Meaning |
|---|---|
| 🟢 PASS | correctly updated, or correctly left alone |
| 🔴 FAIL | provably wrong |
| 🟡 WARN | suspicious but not provably wrong |
| ⚪ INFO | not evaluated (key columns) |

A row's verdict is the worst verdict among its cells; the run's verdict is the
worst among its rows.

| Code | Verdict | Fires when |
|---|---|---|
| `CORRECT_UPDATE` | PASS | the delta asked for a change and the change landed |
| `CORRECT_UNCHANGED` | PASS | no change was expected and none happened |
| `MISSING_UPDATE` | FAIL | the delta asked for a change that never landed |
| `WRONG_VALUE` | FAIL | the cell changed, but not to the value the delta asked for |
| `UNEXPECTED_CHANGE` | FAIL* | the cell changed with no delta entry asking for it |
| `DELTA_BEFORE_VALUE_MISMATCH` | WARN | `old_value` mode: the delta's previous value disagrees with the before file |
| `TIMESTAMP_OK` | PASS | last-modified moved forward with a change, or stayed put without one |
| `TIMESTAMP_NOT_UPDATED` | FAIL | the row changed but last-modified was not bumped |
| `TIMESTAMP_REGRESSED` | FAIL | last-modified went backwards |
| `TIMESTAMP_MOVED_WITHOUT_CHANGE` | WARN* | last-modified moved but no data changed |
| `TIMESTAMP_UNPARSEABLE` | WARN | last-modified is not a readable date |
| `ROW_ADDED_IN_AFTER` | FAIL* | the row is only in the current file |
| `ROW_MISSING_IN_AFTER` | FAIL* | the row disappeared from the current file |
| `DELTA_KEY_NOT_FOUND` | FAIL | a delta row points at a key in neither data file |
| `DUPLICATE_KEY` | WARN | a key appears twice; only the first occurrence is compared |

\* toggleable on the setup screen.

Comparison is case- and whitespace-insensitive by default, numbers compare
numerically (`1` == `1.0`) with an optional tolerance, and both can be changed
per test.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/tests` | list tests |
| `POST` | `/api/tests` | create a test |
| `GET/PATCH/DELETE` | `/api/tests/{id}` | read / rename / delete |
| `POST` | `/api/tests/{id}/files/{before\|after\|delta}` | upload a CSV/XLSX (parsed to JSON) |
| `GET` | `/api/tests/{id}/files/{role}` | paged rows of an uploaded file |
| `PUT` | `/api/tests/{id}/config` | save the column mapping and rule toggles |
| `POST` | `/api/tests/{id}/config/suggest` | re-detect the mapping from the files |
| `POST` | `/api/tests/{id}/run` | run the validation, returns the summary |
| `GET` | `/api/tests/{id}/runs` | run history |
| `GET` | `/api/tests/{id}/runs/{runId}` | results, filterable by `status`, `row_type`, `search` |
| `GET` | `/api/tests/{id}/runs/{runId}/export` | results as CSV |

## Layout

```
backend/
  app/
    main.py                FastAPI app + CORS
    models.py              config, verdicts, rule codes
    ingest.py              CSV/XLSX → JSON rows
    storage.py             JSON file store (tests, datasets, runs)
    validation/
      compare.py           value normalisation, timestamps
      engine.py            the rules
      suggest.py           column auto-detection
    api/routes.py          REST endpoints
  tests/                   pytest
frontend/
  src/app/
    core/                  API client + shared types
    pages/dashboard/       test list
    pages/test-detail/     uploads, mapping, rules, run history
    pages/results/         summary tiles + ag-Grid
sample-data/               the worked example
```

## Adding another validation screen

The sidebar is stubbed for more validation types (reconciliation, schema
checks). To add one: give it a rule module under `backend/app/validation/`, a
run type in `models.py`, and an Angular page under `frontend/src/app/pages/`.
Storage, uploads and the run history are already generic.
