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
## F2.5 — UI redesign, frozen names (24 Sep 2026)

Design authority is `DESIGN.md` (rewritten: light "Instrumen" + dark "Sinematik", dials ENERGY 3 /
RHYTHM 3 / MOTION 2). These names are final; a writer must not invent alternatives.

### Static files (names frozen)

| File | Holds |
|---|---|
| `app/static/tokens.css` | Tokens only: the light block in `:root`, the dark block in `[data-theme="dark"]`, plus `@media (prefers-color-scheme: dark)` for `:root:not([data-theme="light"])`. No layout, no components. |
| `app/static/app.css` | All layout and components (shell, bands, buttons, inputs, chips, tables, dropzone, capacity band, motion + `prefers-reduced-motion` fallbacks). |
| `app/static/app.js` | Vanilla JS only, no dependencies: theme toggle, table sorting, dropzone drag-over/file-name display. Must be loaded with `defer`. |
| `app/static/favicon.svg` | Existing mark; keep. A `/favicon.ico` route is **not** added (browsers fall back to the svg link). |

**No `<style>` block inside any template.** All CSS lives in the two files above.

### Theme mechanism (frozen)

- The active theme is the `data-theme` attribute on `<html>`, values `light` or `dark`.
- Persisted in a **cookie named `rl_theme`** (values `light` / `dark`; absent = follow the OS).
- The toggle button lives in the app bar, has a text label, `aria-label` naming the target theme, and is
  keyboard operable. Both themes must be fully verified (no mode may break layout, contrast or fonts).

### CSS custom property names (frozen)

```
--paper --surface --surface-2 --ink --muted --line --control --accent --accent-soft
--fit --warn --misfit
--font-ui --font-mono
--step-12 --step-14 --step-16 --step-18 --step-22 --step-28 --step-40 --step-56
--space-1 --space-2 --space-3 --space-4 --space-6 --space-8 --space-12 --space-16 --space-24
--radius-sm --radius-md --radius-lg --shadow-1 --shadow-2 --dur-1 --dur-2 --dur-3
--band-h --shell-max
```

Retired names (must not appear anywhere): `--raised`, `--rule`, `--scale`, `--step-13`,
`--step-20`, `--step-24`, `--step-32`, `--step-44`, `--space-24` as a raw pixel value, `.tick-rule`.
The motif is class `band-scale` (a labelled measured band with real numbers).

### Template blocks (frozen)

- `base.html` blocks: `title`, `head`, `content`, `footer`, plus a new `appbar_actions` (extra buttons in
  the app bar, right of the theme toggle). `base.html` renders the app bar and links the three static
  files itself.
- `gate.html` keeps the exact sentence `Aplikasi ini belum dibuka untuk umum.` (verification greps it).
- `datasets.html` must contain both limit numbers verbatim: `16 MB` and `8.000.000 sel`.

### Storage caps (updated — the pair must agree)

| Constant | Value |
|---|---|
| `MAX_UPLOAD_BYTES` | `16 * 1024 * 1024` (unchanged) |
| `MAX_CELLS` | `8_000_000` (was `1_000_000`; the old value bound at ~1,9 MB, making the byte cap decorative — see `DESIGN.md` for the measured cost table) |

### Verification commands (F2.5 additions)

```bash
# token names present and retired names gone
grep -c 'band-scale' app/static/tokens.css app/static/app.css
grep -rn 'tick-rule\|--rule\|--raised\|--scale' app/templates app/static || echo "retired names: none"

# the two limit numbers reach the rendered page (constants -> copy)
.venv/bin/python -m pytest -q tests/test_ui_contract.py

# no debug routes outside dev
APP_ENV=prod .venv/bin/python -c "from app.main import app; print([r.path for r in app.routes if 'docs' in r.path or 'openapi' in r.path.lower()])"
```

## F3: Engine execution, result storage, and presentation

### Storage size caps (updated)

| Constant | Value | Description |
|---|---|---|
| `MAX_UPLOAD_BYTES` | `16 * 1024 * 1024` (16 MiB) | Maximum per-file upload size cap (unchanged). |
| `MAX_CELLS` | `2_000_000` (2,000,000 cells) | Maximum total matrix cell limit (was 8,000,000; lowered so 214 MB engine peak fits 512 MiB instance at concurrency 1). |

### HTTP routes (F3)

| Route | Method | Behaviour |
|---|---|---|
| `/datasets/{id}/analyze` | POST | Triggers Rasch analysis on a ready dataset. Closed gate redirects to `/` (303); unauthenticated redirects to `/login` (303); non-owner returns 404; dataset status not ready redirects to `/datasets/{id}` (303); rate-limited to 12 per hour per IP/user (429 with `Retry-After`); double-submit guard redirects to active running analysis (303) if started within `STALE_RUN_S` (900 s); synchronous thread execution runs engine; on `AnalysisError` before analysis record creation, renders `dataset_detail.html` (422) with Indonesian error message; on success, redirects to `/analyses/{id}` (303). |
| `/analyses/{id}` | GET | Displays analysis view or progress state. Closed gate or unauthenticated returns 404; non-owner returns 404; stale running or queued analyses older than `STALE_RUN_S` (900 s) flip to `failed` status with retry option; renders `analysis.html` (200) for running (in-progress notice), failed (error alert with retry form), and done (four output tables, respondent recap, metadata) states. |

### Database schema additions (column names are FROZEN)

#### Datasets table modification (FROZEN)

| Column (FROZEN) | Type | Meaning |
|---|---|---|
| `matrix_gzip` | BYTEA | Gzip-compressed deterministic JSON container (`v=1`, `namlen`, `key`, `codes`, `prn`) with mtime=0, built at commit or lazily backfilled on analysis (FROZEN). |

#### Analyses table columns (column names are FROZEN)

| Column (FROZEN) | Type | Meaning |
|---|---|---|
| `id` | INTEGER | Primary key identifier for the analysis run (SERIAL, FROZEN). |
| `user_id` | INTEGER | Foreign key referencing users(id) with CASCADE deletion, indexed (`ix_analyses_user_id`) (FROZEN). |
| `dataset_id` | INTEGER | Foreign key referencing datasets(id) with CASCADE deletion, indexed (`ix_analyses_dataset_id`) (FROZEN). |
| `status` | TEXT | Analysis execution state: `queued`, `running`, `done`, or `failed` (FROZEN). |
| `params_json` | TEXT | JSON object of analysis parameters (`mode`, `digits`, `lconv`, `person_order`, `anchors`, `pdfile`) (FROZEN). |
| `engine_ref` | TEXT | Git commit hash reference of the pinned raschlab engine (FROZEN). |
| `error` | TEXT | Indonesian error message string if analysis execution failed, nullable (FROZEN). |
| `elapsed_ms` | INTEGER | Total engine execution time in milliseconds, nullable (FROZEN). |
| `created_at` | BIGINT | Unix epoch timestamp in seconds when the analysis was queued (FROZEN). |
| `started_at` | BIGINT | Unix epoch timestamp in seconds when engine processing began, nullable (FROZEN). |
| `finished_at` | BIGINT | Unix epoch timestamp in seconds when execution finished or failed, nullable (FROZEN). |
| `expires_at` | BIGINT | Unix epoch timestamp in seconds for data retention cleanup (`created_at` + 180 days), indexed (`ix_analyses_expires_at`) (FROZEN). |
| `notice_sent_at` | BIGINT | Unix epoch timestamp in seconds when expiry warning email was sent, nullable (FROZEN). |

#### Analysis files table columns (column names are FROZEN)

| Column (FROZEN) | Type | Meaning |
|---|---|---|
| `id` | INTEGER | Primary key identifier for the stored file (SERIAL, FROZEN). |
| `analysis_id` | INTEGER | Foreign key referencing analyses(id) with CASCADE deletion, indexed (`ix_analysis_files_analysis_id`) (FROZEN). |
| `filename` | TEXT | Engine output filename (`item_table_15.1.csv`, etc.) (FROZEN). |
| `content_gzip` | BYTEA | Gzip-compressed raw engine output bytes with mtime=0 (FROZEN). |
| `sha256` | TEXT | SHA-256 hex digest of the uncompressed output bytes (FROZEN). |
| `bytes` | BIGINT | Size in bytes of the uncompressed output content (FROZEN). |

Table constraints: `UNIQUE (analysis_id, filename)`.

### Output files (`OUTPUT_FILES`)

The engine produces six authoritative output files stored verbatim as deterministic gzip bytes:

```python
OUTPUT_FILES = (
    "item_table_15.1.csv",
    "option_table_15.3.csv",
    "person_table.csv",
    "summary_table.csv",
    "wright_map_measure.csv",
    "wright_map_frequency.csv",
)
```

### CSS component additions

- `.pager`: Navigation flex container for paginated table navigation (`<nav class="pager">`). Displays flex row, wrapping, right-aligned, with gap `var(--space-3)` and top margin `var(--space-4)`. Contains previous/next secondary button controls and mono page position text.

### Jinja filter rule (`id_num`)

- `id_num(value) -> str`: String transformation filter for Indonesian numeric formatting without parsing to float.
- Rules:
  - Non-numeric strings (e.g. respondent IDs like `P0001`, headers, status labels) are passed through unmodified.
  - Plain integer numbers: thousands grouped with period `.` (`1234 -> 1.234`).
  - Decimal numbers: integer portion grouped with period `.`, decimal portion joined with comma `,` (`0.65 -> 0,65`, `-1.23 -> -1,23`, `1000000.5 -> 1.000.000,5`).
- Application:
  - All numeric cells in analysis tables pass through `{{ cell | id_num }}` at render time.
  - Raw identifier and count columns bypass `id_num` and render untouched: item table col 13; person table cols 13 and 14; option table col 11; summary table cols 0 and 1.

### Retention lifecycle constants

- `RETENTION_DAYS = 180`: Analysis records and their output files expire 180 days after creation.
- `NOTICE_DAYS = 14`: Warning notification email is dispatched 14 days before expiration for completed analyses where `notice_sent_at` is null.
- `STALE_RUN_S = 900`: Active runs exceeding 900 seconds (15 minutes) are marked failed upon inspection or prevent redundant duplicate execution within the window.
- Background retention worker runs 30 seconds after application startup and sweeps every 6 hours: purges expired analyses and dispatches pending notice emails.



