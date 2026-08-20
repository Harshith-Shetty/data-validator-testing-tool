# Data Validator Testing Tool

A dashboard for running data validations. The first screen is **data capture
validation**: you upload three files and the tool tells you, cell by cell,
whether a capture run changed the data the way it was supposed to.

- **Before data** — the snapshot as it looked before the capture run
- **Current data** — the snapshot as it looks now
- **Delta file** — the records the run was handed to apply

The third file is an **upsert feed**, not a diff. A record in it does not mean
the data had to change: applying `{id: 7, country: uk}` to a record that
already says `uk` is a legitimate no-op, and applying it to a key that does not
exist yet is an insert. So the engine builds the state the current file *should*
be in — `before`, with every feed record applied as an upsert — and compares the
actual file against that. Update, no-op and insert all fall out of one rule.

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
cd backend && .venv/bin/python -m pytest      # 24 tests: engine rules + API flow
cd frontend && npm run build
```

## Getting a URL you can share

The app also runs as a single container: the Angular bundle is compiled and
then served by the FastAPI app, so the dashboard and the API sit behind one
port.

```bash
docker compose up --build        # → http://localhost:8000
```

That same `Dockerfile` is all any container host needs for a public https URL —
Render (a `render.yaml` blueprint is included), Railway and Fly.io all build it
directly. Set `DVT_STORAGE_DIR` to a mounted volume to keep tests and run
history across restarts; hosts that inject `$PORT` are handled automatically.

There is no authentication in front of the dashboard, so put it behind your own
access control before exposing it to anything but a trusted network.

## Try it with the sample data

`sample-data/` holds the worked example:

| before.csv | | | | after.csv | | | | delta.csv | |
|---|---|---|---|---|---|---|---|---|---|
| **Id** | **last modified** | **att1** | | **Id** | **last modified** | **att1** | | **Issuer** | **country** |
| 1 | 2026-08-02 12:23:00 | uk | | 1 | 2026-08-01 14:02:00 | india | | 1 | uk |
| 2 | 2026-05-01 15:56:00 | usa | | 2 | 2026-05-01 15:56:00 | usa | | 3 | usa |
| 3 | 2026-04-28 06:45:00 | Australia | | 3 | 2026-08-01 14:02:00 | usa | | | |

New test → drop the three files → **Run validation**. The result:

- **Row 1 — FAIL.** The feed re-sent `uk`, which the record already held, so
  nothing should have happened — instead the value became `india` and the
  last-modified timestamp went *backwards*. Two red cells.
- **Row 2 — PASS.** Not in the feed, and nothing moved. Green.
- **Row 3 — PASS.** Updated to `usa` as the feed carries, with the timestamp
  bumped forward. Green.

## How the files are lined up

The delta file rarely uses the same column names as the data (`Issuer` for
`Id`, `country` for `att1`), so the backend auto-detects the mapping on upload
by combining name similarity with how well the actual values overlap. Every
guess is editable on the test setup screen:

- **Key column** in the data, and the column that matches it in the delta
- **Last modified column** (optional)
- **Columns to compare**
- **Delta column → data column** mapping

### What the feed implies

| In before? | In the feed? | Feed value vs before | Expected outcome |
|---|---|---|---|
| yes | yes | differs | **Update** — current holds the feed value, last-modified bumped |
| yes | yes | same | **No-op** — nothing moves, including the timestamp |
| no | yes | — | **Insert** — the record exists in the current file |
| yes | no | — | **Untouched** — current still matches before |
| no | no | — | a row appeared that nothing asked for |
| yes | — | absent from current | the row was deleted |

On an inserted row, columns the feed does not carry are marked *not evaluated* —
nothing in the three files says what a brand-new record should hold there.

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
| `CORRECT_UPDATE` | PASS | the feed carried a new value and it landed |
| `CORRECT_NOOP` | PASS | the feed re-sent the value the record already held, and nothing moved |
| `CORRECT_UNCHANGED` | PASS | the feed says nothing about this row and it is untouched |
| `CORRECT_INSERT` | PASS | a new record arrived with the values the feed carries |
| `MISSING_UPDATE` | FAIL | the feed carried a new value that never landed |
| `WRONG_VALUE` | FAIL | the value changed, but not to what the feed carries |
| `UNEXPECTED_CHANGE` | FAIL* | a value moved with nothing in the feed asking for it |
| `MISSING_INSERT` | FAIL | the feed carries a new record that was never inserted |
| `WRONG_INSERT_VALUE` | FAIL | the record was inserted with the wrong values |
| `UNEXPECTED_INSERT` | FAIL* | a row appeared that is in neither the before file nor the feed |
| `ROW_MISSING_IN_AFTER` | FAIL* | a row disappeared from the current file |
| `TIMESTAMP_OK` | PASS | last-modified moved with a real change, or stayed put without one |
| `TIMESTAMP_NOT_UPDATED` | FAIL | the record changed but last-modified was not bumped |
| `TIMESTAMP_REGRESSED` | FAIL | last-modified went backwards |
| `NOOP_TIMESTAMP_MOVED` | WARN* | the feed re-sent a record unchanged, but it was stamped as modified |
| `TIMESTAMP_MOVED_WITHOUT_CHANGE` | WARN* | last-modified moved on a row nothing touched |
| `TIMESTAMP_UNPARSEABLE` | WARN | last-modified is not a readable date |
| `DUPLICATE_KEY` | WARN | a key appears twice; only the first occurrence is compared |
| `NOT_EVALUATED` | INFO | nothing in the three files can say what this cell should hold |

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
Dockerfile               builds frontend + backend into one image
docker-compose.yml       one-command local run on :8000
render.yaml              Render blueprint (Railway/Fly need no config)
backend/
  app/
    main.py                FastAPI app, CORS, serves the built dashboard
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
