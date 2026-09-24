# INTERFACE.md — frozen contracts for F0

Every writer codes against THIS file, not against the files on disk (another writer may be mid-write
in the same repo). Names here are final; do not rename anything.

## Runtime

- Python 3.12, single container, `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, `PORT` default `7860`.
- Local venv at `.venv` (uv). Install: `uv pip install -r requirements.txt`.
- HF Space: Docker SDK, `app_port: 7860`, public, CPU Basic.

## Environment variables (names are frozen)

| Name | Used by | Notes |
|---|---|---|
| `DATABASE_URL` | `app/db.py` | Postgres DSN, `postgresql+psycopg://...`. No default; absent → `/health/db` reports `db: "unconfigured"`, the app still boots. |
| `PORT` | `Dockerfile`, `app/config.py` | default `7860` |
| `APP_ENV` | `app/config.py` | `dev` or `prod`, default `dev` |
| `GATE_OPEN` | `app/main.py` | `"true"` opens the app to `/register`; anything else keeps the public gate page. Default `false`. |
| `SESSION_SECRET`, `HF_TOKEN`, `RESEND_API_KEY` | later phases | listed in `.env.example` only, unused in F0 |

## HTTP routes (F0)

| Route | Method | Behaviour |
|---|---|---|
| `/` | GET | renders `gate.html` while `GATE_OPEN` is not `true`. 200, no database call. |
| `/health` | GET | `{"status":"ok","version":"<APP_VERSION>","commit":"<short sha or 'dev'>"}`. No database call, no template. |
| `/health/db` | GET | `{"db":"ok"}` after `SELECT 1`, `{"db":"unconfigured"}` when `DATABASE_URL` is missing, `{"db":"error","detail":"<message>"}` on failure. Always HTTP 200 so a monitor can read the body. |
| `/static/*` | GET | static files from `app/static` |

## Python module contracts

- `app/config.py`: `class Settings` with attributes `database_url: str | None`, `port: int`, `app_env: str`, `gate_open: bool`, `app_version: str`, and a module-level `settings = Settings.from_env()`.
- `app/db.py`: `engine` (created lazily so a missing DSN does not crash import), `SessionLocal`, `def get_session()` FastAPI dependency, `def check_db() -> tuple[str, str | None]` returning `(status, detail)`.
- `app/main.py`: `app = FastAPI(...)`, includes `StaticFiles` at `/static`, defines the four routes above, and `APP_VERSION = "0.1.0"`.

## Templates (Jinja2, `app/templates/`)

- `base.html` blocks a child may override: `title`, `head`, `content`, `footer`. It links `/static/tokens.css` itself.
- `gate.html` extends `base.html`; the visible copy must contain the exact sentence
  `Aplikasi ini belum dibuka untuk umum.` (verification greps for it).

## CSS contract

`app/static/tokens.css` defines exactly these custom properties, values verbatim from `DESIGN.md`:

```
--paper --surface --raised --ink --muted --rule --scale --fit --warn --misfit
--font-ui --font-mono
--step-12 --step-13 --step-14 --step-16 --step-20 --step-24 --step-32 --step-44
--space-1 --space-2 --space-3 --space-4 --space-6 --space-8 --space-12
--radius-sm --radius-md --radius-lg --shadow-1 --shadow-2 --dur-1 --dur-2
```

The same names are redefined for dark in `[data-theme="dark"]` plus a `@media (prefers-color-scheme: dark)`
block for `:root:not([data-theme="light"])`. Beyond the token blocks the file holds only:
`*{box-sizing:border-box}`, a base `body` rule, `:focus-visible`, and `.tick-rule` (the measure-scale
motif). Layout styles live in a later phase, not here.
Fonts: IBM Plex Sans + IBM Plex Mono via Google Fonts `preconnect` links in `base.html` for F0
(self-hosted subset in `app/static/fonts/` is the F5 task).

## Database (F0 migration only)

Table `app_meta` (`key TEXT PRIMARY KEY`, `value TEXT NOT NULL`), plus an Alembic revision that
inserts `("schema_version","1")`. No other table in F0.

## File tree created in F0

```
raschlab-web/
  app/{__init__.py,main.py,config.py,db.py}
  app/templates/{base.html,gate.html}
  app/static/tokens.css
  alembic/{env.py,script.py.mako,versions/0001_init.py}
  alembic.ini
  {Dockerfile,requirements.txt,README.md,.gitignore,.env.example}
  DESIGN.md  INTERFACE.md
```

## Verification commands (a writer must run the cheap ones and paste raw output)

```bash
cd /root/projects/raschlab-web
.venv/bin/python -c "import ast,pathlib;[ast.parse(p.read_text()) for p in pathlib.Path('app').rglob('*.py')];print('AST OK')"
.venv/bin/python -c "from app.main import app;print(sorted(r.path for r in app.routes))"
.venv/bin/python -m alembic upgrade head --sql > /tmp/alembic_offline.sql && grep -c app_meta /tmp/alembic_offline.sql
```

## F2 routes

### HTTP routes

| Route | Method | Behaviour |
|---|---|---|
| `/datasets` | GET | Lists user datasets with upload form; returns HTML (`datasets.html`, 200) or redirect to `/login` (303). |
| `/datasets` | POST | Accepts multipart upload, validates and stages dataset; returns redirect to `/datasets/{id}` (303) or renders upload error (`datasets.html`, 200/429). |
| `/datasets/{id}` | GET | Displays preview and mapping form for staged datasets, or summary for ready datasets; returns HTML (`dataset_detail.html`, 200) or 404. |
| `/datasets/{id}/commit` | POST | Validates mapping, reparses stored raw data, marks status as ready; returns redirect to `/datasets/{id}` (303) or error page (`dataset_detail.html`, 422). |
| `/datasets/{id}/discard` | POST | Deletes dataset record from database; returns redirect to `/datasets` (303) or 404. |

### Multipart form fields and accepted extensions

| Field | Requirement | Accepted extensions | Description |
|---|---|---|---|
| `data` | Required | `.csv`, `.xlsx`, `.prn` | Primary measurement data file. |
| `con` | Optional | `.con` | Winsteps control file, required when data format is `.prn`. |

### Storage size caps (app/storage.py)

| Constant | Value | Description |
|---|---|---|
| `MAX_UPLOAD_BYTES` | `16 * 1024 * 1024` (16,777,216 bytes / 16 MiB) | Maximum per-file upload size cap. |
| `MAX_CELLS` | `1_000_000` (1,000,000 cells) | Maximum total matrix cell limit. |

### Datasets table columns (column names are FROZEN)

| Column (FROZEN) | Type | Meaning |
|---|---|---|
| `id` | INTEGER | Primary key identifier for the dataset (FROZEN). |
| `user_id` | INTEGER | Foreign key referencing users(id) with CASCADE deletion (FROZEN). |
| `filename` | TEXT | Original upload filename (FROZEN). |
| `kind` | TEXT | Ingest path category: delimited or winsteps (FROZEN). |
| `format` | TEXT | Ingest file format: csv, xlsx, or prn (FROZEN). |
| `status` | TEXT | Lifecycle stage: staged (preview) or ready (committed) (FROZEN). |
| `n_persons` | INTEGER | Total count of respondents or persons (rows) (FROZEN). |
| `n_items` | INTEGER | Total count of measurement items (columns) (FROZEN). |
| `item_labels_json` | TEXT | JSON array of item column labels (FROZEN). |
| `mapping_json` | TEXT | JSON object of token classification mapping or control parameters (FROZEN). |
| `summary_json` | TEXT | JSON object containing shape, preview rows, distinct tokens, and missing counts (FROZEN). |
| `raw_gzip` | BYTEA | Gzip-compressed raw uploaded file bytes with mtime=0 (FROZEN). |
| `raw_bytes` | BIGINT | Size in bytes of original uncompressed uploaded data (FROZEN). |
| `created_at` | BIGINT | Unix epoch timestamp in seconds when uploaded (FROZEN). |
| `committed_at` | BIGINT | Unix epoch timestamp in seconds when committed, nullable until committed (FROZEN). |

