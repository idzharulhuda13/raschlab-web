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
| `MAX_CELLS` | `6_000_000` (6,000,000 cells) | Maximum total matrix cell limit. The instance was raised to 2 GiB (deploy_ui.sh) because memory, never time, sets this ceiling: for a 45.833-person matrix the measured peak RSS is 0,31 GiB at 0,69 M cells, 0,70 GiB at 2,29 M, 0,71 GiB at 2,52 M, 0,83 GiB at 2,98 M and 0,94 GiB at 3,90 M, while the engine needs 11 s at 3,9 M cells against a 120 s request timeout. 6 M lands near 1,4 GiB of 2 GiB. Raise the instance memory before raising this number; never tune the engine, whose numbers are frozen. |

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

## F4: Explorer (2026-09-25)

Interactive explorer for ONE finished analysis (one analysis = one explorer page), plus a comparison panel that may span two analyses. Read-only: no route in this section writes anything.

### Design read and dials (FROZEN)

Reading this as: an analysis explorer for a psychometrician reviewing one finished run, in a warm instrument language with one measured accent, dial **ENERGY 3 / RHYTHM 3 / MOTION 2** (DESIGN.md).

- Each panel has exactly one focal point: the Wright chart with its readout (Peta Wright), the item table (Butir), the person table (Partisipan), the statistic grid (Ringkasan), the delta chart (Bandingkan). The active tab is the page's single primary-styled element and nothing else may compete with it.
- Composition varies by panel on purpose (RHYTHM 3): a full-width chart beside a readout rail, a search row above a paginated table, a figure grid above the verbatim summary table, and a two-select control strip above the delta chart. No two panels repeat the same internal layout.
- Motion (MOTION 2): hover, focus and state changes use the 120ms duration token, and every transition and animation is paired inside the `prefers-reduced-motion: reduce` block in `app.css`.
- The person histogram carries a count scale: three numeric labels (maximum, half of the maximum, and zero) drawn in the muted token left of the plot area, right-aligned, with no gridlines and no new class or id. Bar heights are readable without hovering; hovering still exposes the exact count through the SVG title.
- The tab strip shares the `.band` container geometry (`width: 100%`, `max-width: var(--shell-max)`, centred, `padding-inline: var(--space-6)`), so the first tab lines up with the page heading rather than with the viewport edge.
- The misfit toggle is a 20x20 control coloured with `accent-color: var(--accent)` inside a row at least 44px tall, with its label linked by `for` and a 2px accent focus ring. The misfit item ticks always carry `.is-misfit`; the toggle adds and removes `.is-misfit-highlight`.

### HTTP routes (F4)

| Route | Method | Behaviour |
|---|---|---|
| `/analyses/{id}/explore` | GET | Closed gate → 404; unauthenticated → 404; non-owner of the analysis or of its dataset → 404; unknown analysis id → 404; analysis status `queued`, `running`, or `failed` → 303 to `/analyses/{id}`; status `done` → 200 rendering `explore.html`. When the `fragment` query parameter is present, the same guards apply but the response body is `explore/fragment.html` alone (panel HTML: no `<html>`, no `<head>`, no tablist). |

### Query parameters (column names and values are FROZEN)

| Parameter | Values | Behaviour |
|---|---|---|
| `view` | `wright`, `butir`, `partisipan`, `ringkasan`, `bandingkan` | Selects the active panel. Absent → `wright`. Unknown → `wright`. |
| `fragment` | `butir`, `partisipan`, `ringkasan`, `bandingkan` | Absent → full page. Present → panel fragment only. `wright` or any unknown value → 404 (the Wright panel is always server-rendered with its payload). |
| `q_item` | free text | Case-insensitive substring over the item table's ENTRY and ITEM label. Absent/empty → no filter. |
| `q_person` | free text | Case-insensitive substring over the person table's identifier and entry columns. Absent/empty → no filter. |
| `page_item` | positive integer | Item table page, default 1, via the existing `paginate()` / `RENDER_PAGE` contract. |
| `page_person` | positive integer | Person table page, default 1, same helper. |
| `from`, `to` | analysis ids | If EITHER is present BOTH are required; must be distinct; both `status = done`; both owned by the caller. **Datasets MAY differ** (owner decision, 25 Sep 2026: cross-dataset comparison is allowed). Any violation (missing, nonexistent, foreign, not-done, equal) → 404. Absent → the compare panel renders its selection prompt. |

### Comparison semantics (FROZEN)

- Pairing keys, in this order: (1) the item table's **LABEL** column (index 13) when BOTH sides carry at least one non-empty label; (2) otherwise the **ENTRY** position, but only when both sides have the same number of items (the revision case: the same instrument re-analysed, labels absent from the export); (3) otherwise nothing is paired: `pairs` is empty, `matched` is 0, and `empty_reason` explains that the two files carry neither labels nor equal item counts.
- ENTRY is a per-dataset row number, so it is never used as a key while labels exist on both sides, and never used when the item counts differ. The panel always discloses the key actually used (`key_used` is `label` or `entry`); no pair is ever created silently.
- Delta = `Decimal(to_measure) - Decimal(from_measure)`, quantized to 2 decimals with `ROUND_HALF_UP`, rendered as a signed string (`+0.25`, `-0.10`, `0.00`). It is the only derived number in the feature; every other number is CSV-verbatim.
- The panel reports `matched`, `unmatched_from`, and `unmatched_to` counts of the key actually used (labels, or ENTRY positions). Partial overlap is normal and is never an error.
- The panel always carries the disclosure sentence (see copy below): a delta between two different datasets is only interpretable when both calibrations share linking items (anchors); otherwise the difference mixes two scales.

### Source columns (FROZEN: the payload mirrors the stored files)

`wright_map_measure.csv`: row 0 header, row 1 second header, data from row 2. Columns: 0 `MEASURE`, 1 `NR_PERSON`, 2 `PERSON_HIST`, 3 `NR_ITEM`, 4 `ITEMS`, 5 `ITEM_HIST`, 6 `PERSON_ENTRIES`, 7 `ITEM_ENTRIES`. A bin is projected as `[col0, col1, col3, col7]`.

`item_table_15.1.csv`: rows 0-1 headers, data from row 2, ENTRY 1..N. Columns: 0 `ENTRY`, 1 `SCORE`, 2 `COUNT`, 3 `MEASURE`, 4 `S.E.`, 5 `INFIT MNSQ`, 6 `INFIT ZSTD`, 7 `OUTFIT MNSQ`, 8 `OUTFIT ZSTD`, 9 `PTMEASUR-AL CORR.`, 10 `EXP.`, 11 `EXACT OBS%`, 12 `EXACT EXPECTED%`, 13 `ITEM` label. An item row is projected as `[0, 13, 3, 4, 5, 6, 7, 8, 9, 11]`.

### View context keys built by `app/explore.py` (FROZEN)

`active_view`, `render_view`, `views`, `payload_json` (JSON string; omitted when the Wright data cannot be read), `wright_error` (`str | None`), `rekap`, `item_ctx`, `person_ctx`, `summary_headers`, `summary_rows`, `sum_headers`, `sum_data`, `compare_ctx` (`options`, `from_id`, `to_id`, `statement`, `means`, `matched`, `unmatched_from`, `unmatched_to`, `key_used`, `caveat`, `empty_reason`), `params`.

### JSON payloads (FROZEN)

`#explorer-data`, embedded as `<script type="application/json" id="explorer-data">{{ payload_json | safe }}</script>` with `</` escaped to `<\/`:

```
{"schema":1,
 "bins":[["MEASURE","NR_PERSON","NR_ITEM","ITEM_ENTRIES"], ...],
 "items":[[ENTRY,"LABEL","MEASURE","S.E.","INFIT MNSQ","INFIT ZSTD","OUTFIT MNSQ","OUTFIT ZSTD","PTMEA CORR.","EXACT OBS%"], ...]}
```

All values are strings exactly as stored in the CSVs; `ENTRY` is the only integer. `ITEM_ENTRIES` is a space-separated list of ENTRY numbers; the client resolves each to its item row.

`#cmp-data`, embedded inside the compare panel as `<script type="application/json" id="cmp-data">`:

```
{"schema":1,"from_id":[int],"to_id":[int],"from_label":"...","to_label":"...",
 "pairs":[[ENTRY,"LABEL","mFrom","mTo","deltaStr"], ...]}
```

### Frozen element ids (FROZEN)

`tablist`, `tab-wright`, `tab-butir`, `tab-partisipan`, `tab-ringkasan`, `tab-bandingkan`, `panel-wright`, `panel-butir`, `panel-partisipan`, `panel-ringkasan`, `panel-bandingkan`, `explorer-data`, `explorer-error`, `explorer-error-reason`, `explorer-fetch-error`, `wright-scale`, `wright-readout`, `wright-meta`, `wright-misfit-toggle`, `butir-search`, `butir-count`, `butir-empty`, `partisipan-search`, `partisipan-count`, `partisipan-empty`, `summary-counts`, `summary-note`, `cmp-from`, `cmp-to`, `cmp-statement`, `cmp-caveat`, `cmp-counts`, `cmp-means`, `cmp-chart`, `cmp-tbody`, `cmp-delta-only`, `cmp-empty`, `cmp-data`.

`explorer-fetch-error` is injected by JavaScript at runtime and therefore does not appear in any template source.

### Frozen class names (FROZEN)

- Templates: `tabs`, `tab`, `explorer-panel`, `chart-scroll`, `readout`, `search-bar`, `compare-strip`, `header-actions`.
- JavaScript/CSS only (never in a template): `wright-item-tick`, `tick-mark`, `focus-ring`, `label-leader`, `delta-row`.
- Wright item label layout (frozen; a change here is a contract change, not a style tweak):
  - `LABEL_BOX_W = 38`, `LABEL_PITCH = 46`, `ITEM_TOP = 54`, `LABEL_ROWS_MAX = 12` (viewBox units).
    The pitch is wider than a box, so two label boxes can never overlap however tightly the item
    measures cluster. A full column spills to the nearest column with room instead of running down.
  - The canvas height derives from the tallest column after placement, so the strip never clips.
  - A label may sit off the item's own x only while its box still covers that x (offset <= half a
    box). Past that the group carries a `label-leader` line from the box edge to `data-bin-x` on the
    group. `data-bin-x` is the item's own bin centre in viewBox units; the invariant is checked by
    `scripts/verify_explorer.py` (E29).
  - The `Batas misfit 1,50` legend sits at the top-right of the plot (y 32/36), never inside the
    item strip. Gridlines sit at the count levels behind the bars.
- State classes: `is-active`, `is-loaded`, `is-misfit`, `is-misfit-highlight`, `is-prominent`, `is-muted`.

Rule: a class used in a template must be in this list or already defined in `app/static/app.css`; the exhaustive class and template counts are pinned by `tests/test_ui_contract.py`.

### JavaScript contracts (FROZEN)

- `window.RaschExplorerCharts.drawWright(container, payload)`, `.drawDelta(container, cmpData)`, `.writeReadout(container, itemRow)`.
- `window.RaschExplorer.boot()`: idempotent, runs on `DOMContentLoaded`, no-op when `#explorer-data` is absent. It appends the misfit count segment (frozen copy, counted from the embedded payload's items) to the server-rendered `#wright-meta` line; the server-rendered part alone stays meaningful without JavaScript.
- `window.RaschExplorer.formatIdNum(s)`: JavaScript mirror of the Jinja `id_num` filter. The Python rule is: a value whose text fully matches `[+-]?\d+(\.\d+)?` gets its integer part grouped with `.` and its decimal separator turned into `,`, with the stored decimal digits preserved exactly (so `73.5` renders `73,5` and `9.90` renders `9,90`); every other string passes through untouched, and `None` renders empty. Note the one boundary the mirror cannot cross: a JavaScript `Number` that had trailing zeros in its source text loses them (`0.0` becomes `0`), because JS numbers carry no scale. Every number this explorer renders comes from a stored CSV string or from an integer count, so no rendered value is affected; do not "fix" this by padding decimals, that would break the verbatim rule. Every client-rendered number passes through it.
- Fetch rule: `explorer.js` may fetch ONLY same-origin `/analyses/<id>/explore?fragment=...&view=...` HTML. Never JSON, never another path.
- Sort contract: `data-explorer-table` on `<table>`, `.th-sort` buttons, `data-sort="number|text"`, `aria-sort` starting at `none`, `<tr data-order="N">` holding the engine order used to restore it.
- Bands rewritten from a fragment must preserve: `view`, `q_item` / `q_person`, `page_item` / `page_person`.

### Copy strings (FROZEN, exact)

`Jelajahi hasil` · tab labels `Peta Wright`, `Butir`, `Partisipan`, `Ringkasan`, `Bandingkan` · `Fokus pada butir di peta untuk melihat rincian.` · `Sorot butir misfit (INFIT MNSQ ≥ 1,50)` · `Memuat data...` · `Tidak ada baris yang cocok dengan pencarian.` · `Hapus pencarian` · `Belum ada analisis lain yang sudah selesai untuk dibandingkan. Jalankan analisis pada berkas ini atau berkas lain untuk membandingkan.` · `Pilih dua analisis untuk dibandingkan.` · `Selisih lintas berkas hanya bermakna bila kedua analisis memakai butir penghubung (anchor) yang sama.` · `Cocok: <n> butir. Hanya di analisis pertama: <n>. Hanya di analisis kedua: <n>.` · `Dipasangkan berdasarkan label butir.` · `Dipasangkan berdasarkan nomor butir (kedua berkas tidak memuat label butir).` · `Butir tidak dapat dipasangkan: berkas tanpa label butir hanya dapat dibandingkan bila jumlah butirnya sama.` · `Membandingkan Analisis #<id> (<YYYY-MM-DD HH:MM>) dengan Analisis #<id> (<YYYY-MM-DD HH:MM>).` · `Tampilkan hanya perubahan ≥ 0,30 (ambang tampilan, bukan uji statistik).` · `Data peta Wright tidak dapat dibaca untuk analisis ini.` · meta line `Partisipan: <n> · Butir: <n> · Dikecualikan (skor sempurna/nol): <n>` · `Butir misfit (INFIT MNSQ ≥ 1,50): <n>.` · `Gagal memuat data. Muat ulang halaman dan coba lagi.` · noscript: `Halaman penjelajah ini membutuhkan JavaScript. Buka halaman hasil analisis untuk melihat tabel lengkap.` plus a link back to `/analyses/{id}`.

Fragment-only copy (also frozen, exact): `Cari butir` · `Cari partisipan` · `Cari` · `Menampilkan <n> dari <n> butir.` · `Menampilkan <n> dari <n> responden.` · `Memuat estimasi measure, S.E., dan statistik kecocokan untuk <n> butir sesuai urutan bawaan mesin.` · `Memuat estimasi ability measure, S.E., dan statistik kecocokan untuk <n> responden sesuai urutan misfit.` · `Sortir hanya berlaku pada halaman yang terlihat.` · `Memuat statistik agregat dari mesin untuk keseluruhan proses analisis.` · `Angka partisipan di tabel ini mencakup skor sempurna dan nol; peta Wright hanya memakai partisipan non-ekstrem.` · `Analisis pertama` · `Analisis kedua` · compare table headers `Butir`, `Measure analisis pertama`, `Measure analisis kedua`, `Selisih` · compare option format `Analisis #<id> · <dataset filename> · <YYYY-MM-DD HH:MM>` · `Rata-rata measure butir: <a> (analisis pertama) vs <b> (analisis kedua).` · pager labels `Sebelumnya` / `Selanjutnya` · the compare trigger reuses the tab label `Bandingkan`.

Chart copy (also frozen, exact): `skala logit` · `Partisipan` · `Butir soal (tingkat kesulitan)` · `Histogram sebaran partisipan` · `Batas misfit 1,50` · `Grafik selisih butir` · readout labels `Measure`, `S.E.`, `INFIT MNSQ`, `INFIT ZSTD`, `OUTFIT MNSQ`, `OUTFIT ZSTD`, `Korelasi butir-total`, `Kesesuaian jawaban`, `Infit tinggi (MNSQ ≥ 1,50)` · item title format `Butir <entry> <label>` (the label part omitted when the stored label is empty). `Partisipan` is the axis label of the count scale (it sits above the three count labels and names what they count), not a second title for the chart.

### Rendering rules (FROZEN)

No `<style>` block and no `style="..."` attribute in any explorer template; all styling lives in `app.css`. No raw hex colour outside `tokens.css`. No external URL beyond `base.html`'s pre-existing font links. No em dash in copy. The active tab is the page's single primary-styled element. No information carried by colour alone: misfit also changes weight and appears in counts, prominence also changes weight. Empty, error, and loading states are rendered text, never a hidden placeholder.

### Verification (F4)

- `python3 -c` key grep over this file → `INTERFACE OK` (keys: `/analyses/{id}/explore`, `fragment=`, `explorer-data`, `cmp-data`, `explorer-charts.js`, `RaschExplorer`, `q_item`, `q_person`, `explore/fragment.html`, `render_view`, `data-explorer-table`, `Jelajahi hasil`, `184`).
- `tests/test_explorer_routes.py` (21 tests) plus the pre-existing suite → `149 passed`.
- `python3 scripts/verify_explorer.py` → 184 browser checks in 11 groups, `184/184 PASS`, `rc=0`; budgets: `loadEventEnd ≤ 400 ms`, first `butir` activation ≤ 150 ms, cached re-activation ≤ 50 ms, 147-row sort ≤ 100 ms, search round-trip ≤ 250 ms, zero long tasks > 100 ms, initial HTML ≤ 120,000 B, embedded payload ≤ 60,000 B.

## F5 — Identity columns, answer keys, and render budgets (25 Sep 2026, frozen)

Why: a 45.832 x 15 upload (identity column named `username`, an answer-key row named
`kunci`) rendered the mapping page as a 33 MiB response because every distinct cell value
became a token. The platform rejected it as "Response size was too large" (HTTP 500). The
names below are frozen; the budgets are hard requirements for any future feature.

### Parser contract (`app/parsers.py`)

- `PERSON_LABEL_HEADERS` is the frozen set of column-0 headers that name the person column.
  It includes `username`, `user`, `user_id`, `uname`, `login`, `akun`, `peserta_id`,
  `id_peserta`, `nomor`, `nomor_peserta`, `no_peserta`, `nopes`, `kode_peserta`, `nis`,
  `nisn`, `nip`, `kandidat`, `testee`, `uid`, `subject`, `subject_id`, `respondent_id`,
  `person_id`, `sample`, `sampel`. A column-0 header outside this set is read as an item
  column (and then the guard below rejects it when it cannot hold answer codes).
- `KEY_ROW_LABELS` = `{kunci, kunci_jawaban, kunci_jawaban_benar, jawaban, key, answer_key,
  answerkey}`. A row whose first cell normalises into this set, with **every** item cell
  filled, is the answer key: `ParsedDataset.key` holds those cells and the row is **not**
  added to `person_labels`. A person genuinely named `kunci` with a blank cell stays a person.
- `DEFAULT_MISSING_TOKENS` = `{"", "na", "n/a", "x", ".", "-"}`. The engine accepts only
  A-E, so `X` can never be a response letter and is missing by default.
- `MAX_DISTINCT_TOKENS_PER_ITEM = 64` and `UNIQUE_COLUMN_RATIO = 0.5`.
  `implausible_item_columns(parsed)` returns `(label, distinct, rows)` for item columns whose
  distinct values exceed the cap and are at least half of the row count: those are identity
  columns that were not recognised. The upload refuses such a file with a written reason
  instead of building an unrenderable page.
- `ParsedDataset` gained the optional field `key: list[str] | None`.

### Scoring (`app/analysis.py`)

- `build_matrix_gzip(..., key: str | None = None)`. With a key of length `n_items`, the
  response letters travel through unchanged and `KEY1` carries the key, so the same letter
  can be correct for one item and wrong for another. Without a key the existing token-mapping
  path is byte-identical to before (that path emits `KEY1 = "A" * n_items`).
- `_is_missing_token(token, mapping)` is the single definition of "no response": blank,
  declared `missing` in the mapping, or a default missing token.

### Form field and pages (`app/ingest.py`, `app/templates/dataset_detail.html`)

- The delimited commit form has an optional `key` field (frozen name `key`, same name as the
  Winsteps form). It is prefilled from a detected key row. Length must equal `dataset.n_items`;
  when it is present the per-token classification selects are not `required`.
- `TOKEN_RENDER_CAP = 64`: the mapping page renders at most this many token rows. A stored
  summary with more tokens renders a notice and **blocks** confirmation with a re-upload
  instruction; it never renders an unbounded list.
- Frozen copy: `Kunci Jawaban Terdeteksi`, `Kolom Butir Tidak Terbaca Sebagai Kode Jawaban`,
  `Isi kunci jawaban sepanjang tepat N karakter`, `Unggah ulang berkas dengan nama kolom
  identitas yang dikenali (mis. id, username, peserta), atau hapus kolom identitas itu.`

### Render and run budgets (measured on the largest real dataset, 45.832 x 15)

- Any HTML response rendered for one dataset or analysis: **< 2 MB** (`tests/test_render_budget.py`
  enforces this on a 12.000 x 15 fixture, and the frozen cap is checked for the dataset,
  analysis, and all explorer views).
- The person table stays **server-side paginated** (`RENDER_PAGE = 500`); the token table is
  capped by `TOKEN_RENDER_CAP`.
- Upload (parse + summary + store) of a 1,7 MB / 45.833-row CSV: **1,1 s** (budget 20 s).
- Engine run for 45.832 x 15 in-process: **8,4 s**, peak RSS **0,3 GiB** of the 1 GiB instance;
  Cloud Run request timeout is 120 s, so the engine keeps a 14x time margin. Do not move the
  engine run off the request path without also revisiting the UI polling contract.
- Measured pages at 45.832 persons: dataset page 64 ms / 20 KB, analysis page 199 ms / 816 KB,
  explorer wright 90 ms / 8 KB, butir 102 ms / 30 KB, partisipan 105 ms / 619 KB, ringkasan
  71 ms / 44 KB.

### F5 caps follow-up (25 Sep 2026)

- `MAX_CELLS = 2_500_000`. A matrix over the cap is refused with a message that carries the
  file's own size: `Berkas memuat <N> sel, melebihi batas maksimal <cap> sel.` The parser
  projects the whole file (`rows * n_items` from the raw line count) rather than reporting the
  partial count at the moment the cap tripped.
- `app/templates/datasets.html` renders every occurrence of the limit and the capacity
  percentage from the `max_cells` context value. A literal limit in that template is a defect:
  the page would advertise a number the upload route does not enforce.
- `MAX_CELLS = 6_000_000` with the instance at 2 GiB. The result page grows with items per row,
  not only rows: 500 person rows cost 816 KB at 15 items and 1,27 MB at 85 items, which is why
  the per-page budget is 2 MB. Data cleaning is not a substitute for this ceiling: a file whose
  cells are real responses cannot be shrunk without dropping respondents or items, and that
  changes the calibration.