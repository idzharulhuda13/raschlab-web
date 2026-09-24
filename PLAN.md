# PLAN.md — F3: run the engine, store the results, render them

**This file is the binding contract for the F3 build.** Phase 2 (writer) executes it literally; Arc verifies
every claim with measurements. Where this file and any other description disagree, this file wins. Nothing in
this plan may be substituted by "a better idea" mid-run: if the writer thinks a step is wrong, it stops and
says so in its report instead of improvising.

Executor key: **agy** = writer run (`--stdin`, 1–2 files per run, `--add-dir /root/projects/raschlab-web`).
**Arc** = install, migrate, deploy, audit. A writer run never runs `alembic upgrade` and never deploys.

## Non-negotiables (measured or decided, not preferences)

1. **Cap is 2 000 000 cells** (was 8 000 000). Reason: 2 M is 5.8x the largest real dataset (342 216 cells),
   enough for 5 000 respondents x 400 items. Every user-facing string that says 8.000.000 must say 2.000.000,
   and `MAX_CELLS` must be `2_000_000`.
2. **Cloud Run stays at 512 MiB, with `--concurrency 1`.** Measured engine peaks: 1 M cells 0.8 s / 134 MB,
   2 M cells 0.9 s / 214 MB, 3 M 1.4 s / 299 MB, 8 M 4.7 s / 744 MB. At the 2 M cap the engine needs 214 MB,
   so one run per instance fits in 512 MiB; two must never share an instance.
3. **Peak memory = max(parse, engine), never their sum.** The engine needs only a `.prn` + `.CON` on disk.
   Decoded bytes, the response matrix and any parser structures must be released before `run_analyze` is
   called. Keep the matrix as `numpy.uint8` while building; do not hold two Python copies of the matrix.
4. **Byte-identity is structural, not aspirational.** The platform calls the engine in-process, with input
   files written exactly as the CLI writes them, and stores the engine's own output bytes (read as `bytes`,
   gzipped with `mtime=0`, never decoded and re-serialized). Localization happens only in the Jinja `id_num`
   filter at render time.
5. **Engine pinned** to `8e8ac678c792d9ecef20cb7efd5ee27cc841af4a` via a git dependency; never vendored,
   never reimplemented.
6. **Fail closed.** An incomplete or unmappable dataset produces an Indonesian error message and no analysis
   row; there is never a silent default.
7. **Scope fence.** F3 = run + store + render 4 tables + person account. F4 (list/rename/delete/download),
   F5 (Wright map render + downloads), payments and auth work are OUT.
8. **UI inherits the frozen design contract** (`DESIGN.md`, `INTERFACE.md`): existing tokens, existing classes,
   no new fonts/colors/gradients, no `<style>` blocks, no inline `style=`, no em dash, Indonesian copy.
9. **Every data view has empty, loading and error states.**

## Phase A — cap copy, dependency, schema

1. **[agy E0] Lower the cap, everywhere it is said.** Three files:
   - `app/storage.py`: `MAX_CELLS: int = 2_000_000` and update the comment above it so it states the new ceiling
     and why (measured engine peak 214 MB at 2 M cells fits a 512 MiB instance; 16 MB/upload unchanged).
   - `app/ingest.py`: the `_format_error` message string that still says "1.000.000 sel" must say
     "2.000.000 sel" (it is stale today: it disagrees with the constant it describes).
   - `app/templates/datasets.html`: all four user-visible occurrences of "8.000.000" (the limit list item and
     the two capacity bands, each with its `aria-label` and its `.band-scale-value`) must say "2.000.000".
   Verify: `grep -rn '2_000_000' app/storage.py` = 1 hit; `grep -rn '8.000.000\|8_000_000' app/ templates/` =
   zero hits; `grep -c '2.000.000' app/templates/datasets.html` = 4; `.venv/bin/python -m pytest -q
   tests/test_ui_contract.py` stays green.
2. **[agy E1] Engine pin.** `requirements.txt` gains exactly one line:
   `raschlab @ git+https://github.com/idzharulhuda13/raschlab@8e8ac678c792d9ecef20cb7efd5ee27cc841af4a`.
   `Dockerfile` gains a git install step (`python:3.12-slim` has no git, and the pip git-URL install needs it)
   before the existing pip install line, as one `RUN apt-get update && apt-get install -y --no-install-recommends
   git && rm -rf /var/lib/apt/lists/*`.
   Verify: `grep -c 'raschlab @ git+' requirements.txt` = 1; `grep -n 'apt-get install' Dockerfile` prints one line.
3. **[Arc] Install locally.** `uv pip install -r requirements.txt`, then
   `.venv/bin/python -c "import raschlab, numpy; print('engine ok', numpy.__version__)"`. Must precede every
   later verify that imports `app.main`.
4. **[agy E2] Migration** `alembic/versions/0004_analysis.py`, revises `"0003"`, raw `op.execute` SQL in the
   style of `0003_ingest.py`:
   - `ALTER TABLE datasets ADD COLUMN matrix_gzip BYTEA;` (nullable, so existing rows stay valid)
   - `CREATE TABLE analyses` with `id SERIAL PRIMARY KEY`, `user_id INTEGER NOT NULL REFERENCES users(id) ON
     DELETE CASCADE`, `dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE`, `status TEXT NOT
     NULL`, `params_json TEXT NOT NULL`, `engine_ref TEXT NOT NULL`, `error TEXT`, `elapsed_ms INTEGER`,
     `created_at BIGINT NOT NULL`, `started_at BIGINT`, `finished_at BIGINT`, `expires_at BIGINT NOT NULL`,
     `notice_sent_at BIGINT`; indexes `ix_analyses_user_id`, `ix_analyses_dataset_id`, `ix_analyses_expires_at`.
   - `CREATE TABLE analysis_files` with `id SERIAL PRIMARY KEY`, `analysis_id INTEGER NOT NULL REFERENCES
     analyses(id) ON DELETE CASCADE`, `filename TEXT NOT NULL`, `content_gzip BYTEA NOT NULL`, `sha256 TEXT NOT
     NULL`, `bytes BIGINT NOT NULL`, `UNIQUE (analysis_id, filename)`; index `ix_analysis_files_analysis_id`.
   - `UPDATE app_meta SET value='4' WHERE key='schema_version'`.
   - Downgrade: drop both tables, drop `datasets.matrix_gzip`, set `schema_version` back to `'3'`. Users and
     datasets rows are never touched.
   Verify: `.venv/bin/python -m alembic heads` shows `0004 (head)`; offline SQL
   (`.venv/bin/python -m alembic upgrade head --sql > /tmp/0004.sql`) contains exactly one `CREATE TABLE
   analyses` and one `matrix_gzip`.
5. **[agy E3] ORM** in `app/models.py`: import `UniqueConstraint`; add `Analysis` and `AnalysisFile` with exactly
   the columns above (`Mapped`/`mapped_column`, `LargeBinary` for `content_gzip`, `UniqueConstraint("analysis_id",
   "filename")` in `__table_args__`); add `Dataset.matrix_gzip: Mapped[Optional[bytes]] = mapped_column(LargeBinary,
   nullable=True)`. Do not touch `app/db.py` (`pool_pre_ping=True`, `pool_recycle=300` must stay).
   Verify: sqlite smoke — `rm -f /tmp/f3.db && DATABASE_URL=sqlite:////tmp/f3.db .venv/bin/python -c "from
   app.db import get_engine; from app.models import Base; Base.metadata.create_all(get_engine());
   print(sorted(Base.metadata.tables))"` lists `analyses` and `analysis_files`.

## Phase B — the engine bridge

6. **[agy E4] Create `app/analysis.py`** (the intricate file: alone in its run). Exact names:
   - Constants: `ENGINE_REF = "8e8ac67"`, `RETENTION_DAYS = 180`, `NOTICE_DAYS = 14`, `STALE_RUN_S = 900`,
     `RENDER_PAGE = 500`, `OUTPUT_FILES = ("item_table_15.1.csv", "option_table_15.3.csv", "person_table.csv",
     "summary_table.csv", "wright_map_measure.csv", "wright_map_frequency.csv")`, and
     `PARAMS_DEFAULT = {"mode": "compat", "digits": 2, "lconv": None, "person_order": "misfit", "anchors": None,
     "pdfile": None}` (anchors/pdfile keys reserved for F4, always null in F3).
   - `class AnalysisError(Exception)` whose `str()` is the Indonesian, user-facing message.
   - `id_num(value) -> str`: string transform only, never parsing to float. Pass through anything that is not a
     plain number; otherwise group the integer part with `.` and join decimals with `,`
     (`0.65 -> 0,65`, `-1.23 -> -1,23`, `1234 -> 1.234`, `1000000.5 -> 1.000.000,5`, `P0001 -> P0001`).
   - `build_matrix_gzip(kind, person_labels, item_labels, rows, mapping, control) -> bytes` — the single
     validation+encoding site, used both at commit and at legacy backfill:
     * delimited: classify every token with `app/parsers.py::classify`; raise `AnalysisError("Ada token yang
       belum dipetakan: ...")` when unassigned; map the distinct incorrect tokens, sorted, to letters `B, C, D, E`
       (raise if more than four); every cell becomes `A` (correct), its letter (incorrect) or a space (missing);
       `key = "A" * n_items`; `codes = "A" + letters`; raise if there is no non-missing cell.
     * winsteps: require `set(codes) <= set("ABCDE")` else raise `AnalysisError("Kode respon ... di luar huruf
       A-E; mesin hanya menerima A-E.")`; require `len(key) == n_items` and every `key[j] in codes`; each cell
       keeps its character when it is in `codes` and not in the extra-missing set, otherwise becomes a space
       (this makes engine-valid identical to platform-valid, because the engine's `score()` accepts only A-E).
     * both: empty person label -> `f"P{i+1:04d}"`; `namlen = max(1, max(len(l) for l in labels))`;
       `item1 = namlen + 1`; each prn line is `label.ljust(namlen) + row`, no truncation. The stored container is
       `gzip.compress(json.dumps({"v":1,"namlen":namlen,"key":key,"codes":codes,"prn":text}).encode(), mtime=0.0)`
       so the bytes are deterministic.
   - `write_inputs(tmp_dir, dataset, matrix_gzip) -> (con_path, prn_path)`: decode the container, write
     `data.prn` (prn text + trailing newline), `items.lbl` (exactly `dataset.n_items` lines, newlines inside
     labels replaced by spaces) and `analyze.CON` whose body is literally `&INST`, `NAME1 = 1`, `NAMLEN = ...`,
     `ITEM1 = ...`, `NI = ...`, `KEY1 = ...`, `CODES = ...`, `DATA = data.prn`, `ILABEL = items.lbl`, `&END`.
     Relative filenames only, so the CON bytes do not depend on the directory; return the absolute paths.
   - `ensure_matrix(db, dataset) -> bytes`: return `dataset.matrix_gzip` when present, else the legacy backfill:
     decompress `raw_gzip`, parse once with the existing parser, `build_matrix_gzip`, persist to
     `datasets.matrix_gzip`, commit. This is the only path that re-parses a workbook, and only for datasets that
     predate F3.
   - `run_for_dataset(db, dataset) -> Analysis`: (1) `ensure_matrix`; (2) insert the row with `status="queued"`,
     `params_json=json.dumps(PARAMS_DEFAULT)`, `engine_ref=ENGINE_REF`, `created_at`, `expires_at` = created +
     180 days; commit; (3) flip to `status="running"` with `started_at`; commit; (4) inside one
     `with tempfile.TemporaryDirectory(prefix="raschlab_") as td:` write the inputs, release the matrix
     container reference, then call `run_analyze(con_path=..., data_path=..., out_dir=td, mode="compat",
     out_format="csv", digits=2, lconv=None, person_order="misfit")` (module-level
     `from raschlab.cli import run_analyze`), capturing stdout/stderr into a buffer; catch `SystemExit` and
     `Exception` and raise `AnalysisError("Analisis gagal dijalankan mesin: " + <last stderr line, max 1000
     chars>)`; (5) read all six output files as raw `bytes`, `gzip.compress(b, mtime=0)`, compute
     `sha256` and `bytes`; (6) in ONE transaction insert the six `AnalysisFile` rows and set
     `status="done"`, `finished_at`, `elapsed_ms`; on any failure after step 2 roll back the files, set
     `status="failed"`, `error`, `finished_at`, commit, and return that row.
   - `load_tables(analysis) -> dict[str, list[list[str]]]` (decompress + `csv.reader`, all six),
     `latest_done_analysis(db, dataset_id)`, `paginate(rows, page)`,
     `retention_sweep(db, now) -> dict`: delete rows with `expires_at <= now` (any status); for `status='done'`
     rows with `notice_sent_at IS NULL` whose expiry is within 14 days, send the Indonesian notice through the
     existing email helper (`from app import auth` then `auth.send_email(...)`, a module-attribute call so the
     existing test capture patch applies) and set `notice_sent_at`; on send failure leave it NULL to retry.
   Verify: `.venv/bin/python -c "import ast; ast.parse(open('app/analysis.py').read()); import app.analysis;
   print('ok')"`.
7. **[agy E5] Edit `app/ingest.py`**, four literal hunks in order (if the writer no-ops, split into two runs):
   - H1: after the ratelimit import, add `from app.analysis import AnalysisError, build_matrix_gzip,
     latest_done_analysis`.
   - H2: in `get_dataset`, build the context into a local first, add
     `context["latest_analysis"] = latest_done_analysis(db, dataset.id)`, then return with `context=context`.
   - H3 (delimited commit branch): build the matrix in a `try/except AnalysisError` that renders the same 422
     page the unassigned-token block already renders, then set `dataset.matrix_gzip = matrix_gzip` after the
     mapping and `committed_at` are set.
   - H4 (winsteps commit branch): the same pattern with `kind="winsteps"` and `control=control`, setting
     `dataset.matrix_gzip` before that branch's commit.
   Verify: `python -c "import ast; ast.parse(open('app/ingest.py').read()); print('ok')"` and
   `.venv/bin/python -m pytest -q tests/test_ingest_routes.py` stays green.

## Phase C — routes

8. **[agy E6] Create `app/analyze.py` + edit `app/main.py` (2 files).**
   - `app/analyze.py`: an `APIRouter`; register `templates.env.filters["id_num"] = id_num` on the same
     `templates` object the ingest routes use; a lifespan task that runs the retention sweep after 30 s and then
     every 6 hours, entirely inside `try/except` + `logger.exception`.
     * `POST /datasets/{id}/analyze` — closed gate -> 303 `/`; anonymous -> 303 `/login`; not owner -> 404; dataset
       not `ready` -> 303 to the detail page; rate limit `analyze:{client_ip}:{user_id}` 12 per hour -> 429 with
       `Retry-After`; an existing `running` row for the same dataset younger than `STALE_RUN_S` -> 303 to it
       (double-submit guard); `AnalysisError` before the row exists -> 422 on `dataset_detail.html` with the
       message; success -> 303 `/analyses/{analysis.id}`. This route is a sync `def` so the CPU-bound engine runs
       in the threadpool and never blocks the event loop.
     * `GET /analyses/{id}` — gate/owner 404; a `queued`/`running` row older than `STALE_RUN_S` is flipped to
       `failed` with `"Analisis terhenti saat berjalan. Jalankan ulang."`; renders `analysis.html` in three
       states: running (loading), failed (Indonesian error + retry form posting to the analyze route), done
       (full render).
   - `app/main.py`: import and `app.include_router(...)` after the ingest router.
   Verify: `.venv/bin/python -c "from app.main import app; print(sorted(r.path for r in app.routes))"` lists
   both new paths.

## Phase D — UI

9. **[agy E7] Append one block to `app/static/app.css`**: `.pager` (flex row, wrapping, right-aligned, top
   margin from existing space tokens) and nothing else; no new animation. `.pager` is the only new class.
   Verify: `grep -c '^\.pager{' app/static/app.css` = 1 and `pytest -q tests/test_ui_contract.py` green.
10. **[agy E8] Create `app/templates/analysis.html` + edit `tests/test_ui_contract.py` (2 files).** Template
    extends `base.html`, Indonesian copy, only existing classes, no `<style>`, no `style=`, no em dash. Structure:
    header band (back link to `/datasets/{id}`, filename as `h1`, status chip, the retention line "Hasil analisis
    disimpan selama 180 hari.", definition rows for engine ref, elapsed time, person-table order
    "Urutan tabel responden: misfit (outfit MNSQ menurun)", mode and digits) -> a "Rekap Responden" band whose
    values come only from the stored `summary_table.csv` (`PERSON COUNT`, `COUNTS EXTREME EXCLUDED`,
    `COUNTS EXTREME_MIN`, `COUNTS EXTREME_MAX`, `COUNTS LACKING`, `COUNTS DELETED`) plus `dataset.n_persons` ->
    four table bands: "Tabel Butir (15.1)", "Tabel Opsi dan Distraktor (15.3)", "Tabel Responden", "Tabel
    Ringkasan". Each table: scroll wrapper + existing table classes + caption, two-row header rendered verbatim
    (empty row-1 cells as `<th></th>`), every cell through `{{ cell | id_num }}` EXCEPT the raw columns (item col
    13; person cols 13 and 14; option col 11; summary cols 0 and 1) which render untouched. No sorting controls:
    the engine's order is authoritative. Item/person/option tables paginate 500 rows with
    `?page_item=&page_person=&page_option=` links (each href carrying the other two current values) and a
    `<nav class="pager">` with previous/next secondary buttons plus a mono line "Halaman x dari y (n baris)"; the
    summary table is not paginated. States: running shows the empty-state text "Analisis sedang diproses...";
    failed shows the existing misfit alert with the Indonesian error and a retry form
    (`data-loading="Memproses analisis..."`, primary button "Jalankan Ulang"). In `tests/test_ui_contract.py`
    change the template count assertion from `== 9` to `== 10`.
    Verify: `.venv/bin/python -m pytest -q tests/test_ui_contract.py` green (this proves the class inventory, the
    template count, the absence of style blocks and the retired names).
11. **[agy E9] Edit `app/templates/dataset_detail.html`**: insert one new section immediately before the actions
    band, rendered only when `status == 'ready'`: a form posting to `/datasets/{{ dataset.id }}/analyze` with
    `data-loading="Memproses analisis..."` and a primary button "Jalankan Analisis Rasch"; below it, when
    `latest_analysis` is present, a secondary link "Lihat hasil analisis terakhir" plus a status chip, otherwise
    the empty-state line "Belum ada analisis untuk berkas ini.".
    Verify: `.venv/bin/python -m pytest -q tests/test_ingest_routes.py tests/test_ui_contract.py` green.

## Phase E — the proofs (the acceptance test is the deliverable)

12. **[agy E10] Create `tests/test_analysis_unit.py`**: delimited encoding cases (correct/incorrect/missing
    mapping, deterministic letter assignment, `codes == "ABC"` for two incorrect tokens); fail-closed cases
    (unassigned token, five distinct incorrect tokens, winsteps codes outside A-E, `key[j] not in codes`, empty
    matrix); winsteps blanking; container roundtrip and gzip determinism (two calls produce identical bytes);
    prn roundtrip through the engine's own `raschlab.reader.read_matrix`; `write_inputs` producing a CON that
    `raschlab.control.parse_control` accepts with `NI == len(KEY1)` and an `items.lbl` line count equal to
    `n_items`; `id_num` against the case list; `paginate` clamping; `retention_sweep` on a sqlite session
    (expired row deleted, near-expiry row gets `notice_sent_at` through the captured email helper).
    Verify: `.venv/bin/python -m pytest -q tests/test_analysis_unit.py`.
13. **[agy E11] Create `tests/test_analysis_routes.py`**, reusing the authenticated-user helper pattern from
    `tests/test_ingest_routes.py`: upload + commit `tests/fixtures/sample_300x40.csv` -> POST analyze -> 303 ->
    GET the result page 200 containing "Tabel Butir (15.1)", the order label, an Indonesian decimal comma inside
    a rendered measure cell and `id_num`-formatted thousands; DB assertions (`status == "done"`, `elapsed_ms > 0`,
    six `analysis_files` rows, decompressed bytes start with the engine's header, `sha256` recomputes,
    `expires_at - created_at == 180 days`); isolation (user B gets 404 for both the read and the run);
    failure state (a monkeypatched `run_analyze` raising `SystemExit(2)` -> `status == "failed"`, zero files, page
    shows the misfit alert and the Indonesian message); loading state (a manually inserted `running` row);
    stale row older than 900 s flipped to `failed`; the `latest_analysis` link on the dataset detail page; and
    the legacy backfill (set `matrix_gzip=None`, analyze, matrix repopulated).
    Verify: `.venv/bin/python -m pytest -q tests/test_analysis_routes.py`.
14. **[agy E12] Create `tests/test_byte_identity.py`** (the acceptance comparator as a test): drive the full HTTP
    flow on `tests/fixtures/sample_300x40.csv`, then independently re-derive the inputs with
    `build_matrix_gzip` + `write_inputs` into `tmp_path` and run the CLI
    (`sys.executable -m raschlab analyze --con ... --data ... --out ... --format csv`, `check=True`); assert for
    all six output files that `gzip.decompress(platform_bytes) == cli_bytes` byte-for-byte and that the sha256
    values match. No skipif: the engine is a hard dependency.
    Verify: `.venv/bin/python -m pytest -q tests/test_byte_identity.py`.
15. **[agy E13] Create `scripts/compare_cli_platform.py`**: a standalone comparator for the verifier (sets
    `DATABASE_URL` to a temp sqlite and the gate env before importing `app.main`, creates the schema, inserts a
    verified user + session directly, drives upload -> commit -> analyze through `TestClient`), then the same CLI
    comparison; prints one line per file with both sha256 values and MATCH/MISMATCH, and finally
    `ALL 6 FILES BYTE-IDENTICAL` (exit 0) or a non-zero exit.
    Verify: `.venv/bin/python scripts/compare_cli_platform.py` exits 0 and prints that line.
16. **[agy E14] Edit `INTERFACE.md`**: append an F3 section with the two routes and their behaviours, the
    `analyses` / `analysis_files` / `datasets.matrix_gzip` column tables (marked FROZEN), `OUTPUT_FILES`, the
    `.pager` class, the `id_num` filter rule, the retention constants, and the new 2 000 000 cap.
    Verify: `grep -c '## F3' INTERFACE.md` = 1.

## Phase F — Arc only (never agy)

17. Full gate: `.venv/bin/python -m pytest -q` (all existing tests plus the new ones, zero failures) and
    `.venv/bin/python scripts/compare_cli_platform.py` (raw output pasted into the report).
18. Migrate Neon: read the DSN from Secret Manager, `DATABASE_URL=... .venv/bin/python -m alembic upgrade head`,
    confirm `alembic current` shows `0004`.
19. Deploy: same source-based invocation as revision `raschlab-web-00010-w29`, with
    `--memory 512Mi --concurrency 1 --timeout 120`. Verify with
    `gcloud run services describe raschlab-web --region asia-southeast1 --format='value(spec.template.spec.containers[0].resources.limits.memory,spec.template.spec.containerConcurrency)'`.
20. Live walkthrough on the deployed revision: login -> upload `sample_300x40.csv` -> commit -> analyze -> open the
    result page. Record HTTP status, the visible Indonesian headers, `/health` commit, absence of tracebacks, and
    the live peak memory from Cloud Run metrics for the run request. Then run the Hallmark audit gate (per the
    house wiring in the antislop skill) before reporting F3 done. If the instance is OOM-killed at the 2 M cap,
    the fallback lever is `--memory 1Gi` (re-measure; do not guess).

## EDIT LIST (one agy run per row unless noted)

| Run | Files | Verify |
|---|---|---|
| E0 | `app/storage.py`, `app/ingest.py`, `app/templates/datasets.html` | cap greps + `test_ui_contract.py` |
| E1 | `requirements.txt`, `Dockerfile` | the two greps |
| E2 | `alembic/versions/0004_analysis.py` | `alembic heads`, offline SQL greps |
| E3 | `app/models.py` | sqlite `create_all` smoke |
| E4 | `app/analysis.py` | ast + import |
| E5 | `app/ingest.py` | `test_ingest_routes.py` |
| E6 | `app/analyze.py`, `app/main.py` | route list print |
| E7 | `app/static/app.css` | `.pager` grep + contract test |
| E8 | `app/templates/analysis.html`, `tests/test_ui_contract.py` | `test_ui_contract.py` |
| E9 | `app/templates/dataset_detail.html` | ingest + contract tests |
| E10 | `tests/test_analysis_unit.py` | its own test run |
| E11 | `tests/test_analysis_routes.py` | its own test run |
| E12 | `tests/test_byte_identity.py` | its own test run |
| E13 | `scripts/compare_cli_platform.py` | run it, exit 0 |
| E14 | `INTERFACE.md` | the grep |

## ASSUMPTIONS

1. Advanced engine options (item anchors / person deletes) are **deferred, not shipped as form fields**:
   `params_json` carries `anchors: null, pdfile: null` so F4 can add fields with no migration.
2. Person-table order is fixed to the engine default (`misfit`) with no form control; it is displayed as text and
   stored in `params_json`.
3. The parsed-matrix artifact is `datasets.matrix_gzip` = deterministic gzip of
   `{"v":1,"namlen","key","codes","prn"}`, built at commit time (when the mapping becomes final). The upload path
   is untouched; pre-F3 datasets are backfilled lazily on first analysis.
4. Results are stored as the engine's own CSV bytes for all six outputs (the two Wright-map files included, so F5
   never re-runs the engine). Rendering parses the four needed files per request. No xlsx output is generated.
5. Downloads are not built in F3; byte-identity is proven against the stored bytes by the test and the script.
6. Delimited datasets are re-encoded to synthetic letters (the engine's prn alphabet is single-character A-E), so
   the option table's codes are synthetic for CSV/XLSX uploads while original tokens survive for Winsteps uploads.
7. Retention runs as an in-app sweep (startup + 30 s, then every 6 h) because Cloud Run has no external cron;
   worst-case deletion latency is one instance lifetime, always inside the 14-day notice window.
8. Analysis rate limit is 12 per hour per user/IP through the existing in-memory limiter.
9. HTML numbers use Indonesian formatting only through the `id_num` filter; column headers keep the engine's own
   (English, Winsteps-style) text so page and file agree, while all prose is Indonesian.
10. Render page size is 500 rows for item/person/option tables; the summary table is always full.
11. Engine determinism across processes is assumed on the strength of its own regression tests and re-proven on
    this box by the comparator.
12. The deploy invocation matches the one used for `raschlab-web-00010-w29`; the memory/concurrency flags are
    given explicitly above.

## RISKS

1. **Memory at the cap (rank 1).** 8 M cells measured 744 MB, which is why the cap is now 2 M (214 MB measured).
   With 512 MiB and `--concurrency 1`, one engine run per instance fits; the design must never hold two matrix
   copies (non-negotiable 3). Live peak memory is checked after deploy; the fallback lever is 1 GiB.
2. **Byte-identity drift (rank 2).** The stored bytes are the engine's own; localization exists only in `id_num`
   at render. Guarded by `test_byte_identity.py` + `scripts/compare_cli_platform.py`.
3. **Temp-file cleanup (rank 3).** Everything lives inside one `TemporaryDirectory` context; the engine's
   `SystemExit` is caught inside that context; the failure-path test proves no files and no `done` status.
4. **Per-user isolation (rank 4).** Both routes 404 for a foreign user, proved by tests on read and run.
5. **Partially written result (rank 5).** `queued -> running -> done|failed`; the six file rows and `done` commit
   in one transaction, so `done` implies six files; `running` rows older than 900 s flip to `failed`.
6. **Docker build breakage (rank 6).** The pinned git dependency needs git in the slim image; proved locally by
   `uv pip install` before any code imports it.
7. **Contract-test collision (rank 7).** The new template changes the `== 9` assertion and the new CSS class must
   pass the class inventory; `.pager` lands in E7 before the template in E8, and the contract test runs after each.
8. **Legacy datasets (rank 8).** The first analysis of a pre-F3 dataset re-parses its raw file once and persists
   the matrix afterwards.
9. **Retention on ephemeral instances (rank 9).** Sweep at startup and every 6 h; email failures retry on the next
   sweep because `notice_sent_at` stays NULL.
10. **Neon growth (rank 10).** Results are KB-scale, the matrix container is MB-scale, retention is 180 days, and
    datasets themselves are never auto-deleted.
11. **Winsteps datasets with codes outside A-E (rank 11).** Fails closed at commit with an Indonesian message; no
    silent wrong numbers.
12. **Concurrent double-runs (rank 12).** A young `running` row for the same dataset redirects to it instead of
    starting a second job.

## ROLLBACK

Code first, schema second; user data (users, datasets, raw uploads) is never dropped by either step.

1. Send traffic back to the known-good revision (old code simply ignores the new tables):
   `gcloud run services update-traffic raschlab-web --region asia-southeast1 --to-revisions=raschlab-web-00010-w29=100`
2. `git revert` the F3 commits, push, redeploy, and confirm `/health` before touching anything else.
3. Only if the migration itself must go:
   `DATABASE_URL=... .venv/bin/python -m alembic downgrade 0003` — drops `analyses`, `analysis_files` and
   `datasets.matrix_gzip` (derived, re-runnable analysis results only; `schema_version` returns to 3; users and
   datasets rows untouched). Restore the old cap copy by reverting commit E0.
