# PLAN.md — F11: Excel export per table

**This file is the binding contract for the F11 build.** Phase 2 (writer) executes it literally; Arc verifies
every claim with measurements. Where this file and any other description disagree, this file wins. A writer that
thinks a step is wrong STOPS and says so in its report instead of improvising.

Executor key: **agy** = writer run (one file per run, background, prompt from a file via `--stdin`,
`--mode accept-edits --dangerously-skip-permissions --add-dir /root/projects/raschlab-web`). **Arc** = the frozen
contract docs, verification, the browser harness, the audit, the deploy handoff. A writer run never deploys.

Planner provenance: `planner/plans/2026-09-26-raschlab-export.md` (5/5 sections, session `20260926_140202_931bd4`),
curated here. Three of its claims were wrong or unfalsifiable and are corrected below; the corrections are
marked **[curated]**.

## Owner decisions (Dada, 26 Sep 2026 — quoted, do not re-open)

1. Content: **"Hanya tabel yang sedang tampil di layar itu."**
2. Placement: **"Halaman hasil + explorer + daftar Hasil Analisis (biar bisa unduh run lama tanpa buka)."**
3. Sheet shape: **"Verbatim seperti output engine (2 baris header, angka mesin) tapi sel angka ditulis sebagai
   number + number format rapi di Excel."**

## Non-negotiables (measured or decided, with the reason)

1. **The content type is a literal, and the planner's value was wrong.** Use exactly
   `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`. (`…vnd.openpyxl-officedocument…` is not a
   registered type and would make some browsers download with the wrong handler.) **[curated]**
2. **One XLSX per request, built synchronously in memory** with openpyxl write-only cells, returned as bytes.
   No queue, no worker, no background job, no stored artifact, no new table, no migration.
   Measured on this box with the real writer path (own process, `openpyxl 3.1.5`, openpyxl `write_only`):

   | rows x cols | cells | write time | peak RSS | file |
   |---|---|---|---|---|
   | 45.834 x 15 (real worst production table) | 687.540 | 10,3 s | 76,5 MiB | 2,29 MB |
   | 100.002 x 15 | 1.500.030 | 28,4 s | 122,7 MiB | 4,99 MB |

   Script: `/root/raschlab-ops/measure_export_xlsx.py`. Instance is 2 GiB with a 120 s request timeout, so the
   synchronous shape holds with ~2-4x headroom.
3. **Export caps, derived from that measurement, not guessed:** `EXPORT_MAX_ROWS = 1_048_000` (Excel's own sheet
   limit is 1.048.576, so a bigger file would be unopenable) and `EXPORT_MAX_CELLS = 2_500_000` (≈50 s and
   ≈200 MiB on the curve above). Above either cap the route answers **413** with a message naming the actual
   numbers, never a truncated file and never a 500. Raising a cap is an instance/memory decision (the same rule
   as `MAX_CELLS`), never a code-only change. **[curated]** — the planner had no cap at all.
4. **The numeric decision is delegated to the engine, never re-derived.** For the five engine tables: the column
   label is the cell's label in the LAST header row of the stored CSV; call
   `raschlab.report.number_format_for_header(label)` and then `raschlab.report.coerce_cell(value, fmt)`. A cell
   becomes a number only when the engine's own rule says so, and it carries the format the engine returns. Every
   other cell stays a string — that is what keeps `PERSON` and `ITEM` identifier columns text even when they are
   all digits (16-digit ids would lose precision as floats). `ringkasan` uses
   `raschlab.report.summary_value_format` per VALUE cell, exactly as the engine workbook does. `bandingkan` is
   the one derived sheet and gets explicit numeric columns (below).
   **Stop-and-report condition:** if any real identifier column resolves numeric under that rule, a writer stops
   and reports instead of patching around the engine.
5. **All rows, always. `q_item`, `q_person`, `page_item`, `page_person`, `page_option` and any explorer filter are
   ignored.** A file narrowed to the current search or page would be a silent truncation of data.
6. **`wright` exports `wright_map_measure.csv`** — the file the displayed map is built from
   (`app/explore.py` L380). `wright_map_frequency.csv` is rendered on no page, so it gets no control.
7. **`bandingkan` reuses the server-side call chain the view renders** (`build_compare_pairs`, `Decimal`,
   `ROUND_HALF_UP`, 2dp), so the file and the screen cannot disagree. Sheet rows = `compare_ctx.pairs` in order;
   exported columns are the five the table renders (nomor, butir, measure pertama, measure kedua, selisih) and the
   header row repeats the rendered labels verbatim, including the minus sign in "Selisih (kedua − pertama)".
8. **Rate limit** uses the existing `app/ratelimit.check_limit` helper: `30` per `3600` s per user with the key
   `export:{client_ip}:{user_id}`. A worst-case export is ~10 s of one vCPU, so an unlimited loop is a real cost.
   Refusal = **429** + `Retry-After` + a one-paragraph Indonesian page. **[curated]** — `app/ingest.py` already
   renders a whole page on its upload limit, but this response is a download and has no page of its own, so the
   body is a minimal inline HTML document built in `app/export.py`; **no new template file** (template names are
   frozen in `INTERFACE.md`).
9. **Route:** `GET /analyses/{id}/export?table=<key>` with keys `butir`, `opsi`, `responden`, `ringkasan`,
   `wright`, `bandingkan`; `from` and `to` are read only for `bandingkan`. Registered in `app/main.py` in exactly
   the pattern the other three routers use (`from app.export import router as export_router` +
   `app.include_router(export_router)`; `app/main.py` L48-51). **[curated]** the planner wrote only "mirror how
   `app.explore` is registered" without naming the import form, and the router object in `app/explore.py` is
   module-level `router = APIRouter()`.
10. **Zero new CSS or template classes; no JS change; no CSS change; no pagination change; no DB change.** Every
    class a writer inserts already exists in `app/templates/**` today (`action-bar`, `btn`, `btn--secondary`,
    `text-link`), so the class-count pins in `tests/test_ui_contract.py` (145 used / 159 defined) must NOT move.
    If a control cannot be placed with existing classes, that run STOPS and reports; it never edits the pin.
11. **Copy** is Indonesian: visible text `Unduh Excel` everywhere, plus a mandatory `aria-label` that names the
    table, because five identical controls on one page are unusable with a screen reader. No em dash.
12. **Docs are frozen before code, by Arc, in this session** (`INTERFACE.md` F11 + `DESIGN.md` F11). Doc edits are
    not logic and do not consume a writer run; the planner's runs 1-2 are therefore dropped. **[curated]**

## The route contract

```
GET /analyses/{id}/export?table=butir|opsi|responden|ringkasan|wright|bandingkan[&from=<id>&to=<id>]
```

Guard order is part of the contract:

| # | condition | answer |
|---|---|---|
| 1 | `_gate_closed()` | 404 `PAGE_NOT_FOUND_MSG` |
| 2 | `_current_user(request, db) is None` | 404 `PAGE_NOT_FOUND_MSG` |
| 3 | analysis missing or `analysis.user_id != user.id` | 404 `ANALYSIS_NOT_FOUND_MSG` |
| 4 | dataset missing or not owned | 404 `DATASET_NOT_FOUND_MSG` |
| 5 | `analysis.status != "done"` | 303 `/analyses/{id}` |
| 6 | unknown `table` key | 404 `EXPORT_TABLE_NOT_FOUND_MSG` |
| 7 | rate limit exceeded | 429 + `Retry-After` |
| 8 | table above `EXPORT_MAX_ROWS` / `EXPORT_MAX_CELLS` | 413 + message with the actual numbers |
| 9 | stored file absent or empty | 404 `EXPORT_TABLE_NOT_FOUND_MSG` |
| 10 | otherwise | 200, attachment headers |

The stale-run status flip in `get_explore` (L319-327) is deliberately NOT copied: a download must not mutate
state. `bandingkan` resolves `from`/`to` under the same ownership and `done` rules as the single tables.

Table key → stored file → sheet title:

| key | `analysis_files.filename` | sheet title | header rows |
|---|---|---|---|
| `butir` | `item_table_15.1.csv` | `butir` | 2 |
| `opsi` | `option_table_15.3.csv` | `opsi` | 2 |
| `responden` | `person_table.csv` | `responden` | 2 |
| `ringkasan` | `summary_table.csv` | `ringkasan` | 1 (+ the blank spacer row) |
| `wright` | `wright_map_measure.csv` | `wright` | 2 |
| `bandingkan` | derived from two `item_table_15.1.csv` | `bandingkan` | 1 |

Response headers on success:

```
Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
Content-Disposition: attachment; filename="raschlab-{id}-{table}.xlsx"; filename*=UTF-8''raschlab-{id}-{table}.xlsx
Cache-Control: no-store
```

## Control inventory (frozen)

| page | anchors | keys |
|---|---|---|
| `/analyses/{id}` | after `<h2>Rekap Responden</h2>` / after `<h2>Tabel Butir (15.1)</h2>` / after `<h2>Tabel Opsi dan Distraktor (15.3)</h2>` / after `<h2>Tabel Responden</h2>` | `ringkasan`, `butir`, `opsi`, `responden` |
| `/analyses/{id}/explore` view `wright` | inside `#panel-wright`, after `<p id="wright-meta">…</p>`, before `<div id="wright-scale">` | `wright` |
| `/analyses/{id}/explore` view `butir` | top of `explore/fragment.html`, one `render_view` chain | `butir` |
| `/analyses/{id}/explore` view `partisipan` | same chain | `responden` |
| `/analyses/{id}/explore` view `ringkasan` | same chain | `ringkasan` |
| `/analyses/{id}/explore` view `bandingkan` | same chain, only when `compare_ctx.from_id` and `compare_ctx.to_id` are set | `bandingkan` + `from`/`to` |
| `/analyses` | desktop table: new `Unduh Excel` column; mobile `file-cards`: same links in the card's action row | per row `butir`, `opsi`, `responden`, `ringkasan` |

Markup shape (three lines, existing classes only):

```html
<div class="action-bar">
  <a class="btn btn--secondary" href="/analyses/{{ analysis.id }}/export?table=KEY" aria-label="ARIA">Unduh Excel</a>
</div>
```

**[curated]** the planner gave the list page a single control exporting `ringkasan` "because a 45.834-row butir
file would be a hostile surprise". Rejected: the owner asked to download an old run **without opening it**, and
narrowing that to the summary would hide the run's main result. The list page therefore carries the same four
keys as the result page, and the route's cap message is what protects the size case.

## Constraints (the ladder travels with the task)

```text
LADDER — before writing any code, stop at the first rung that holds:
1. Does this need to exist?      -> no: skip it (YAGNI), say so in one line.
2. Already in this codebase?     -> reuse the helper/util/pattern that already lives here. Look before writing.
3. Stdlib does it?               -> use it.
4. Native platform feature?      -> use it (input type=date over a picker lib, CSS over JS, DB constraint over app code).
5. Already-installed dependency? -> use it. Never add a new one for what a few lines can do.
6. Can it be one line?           -> one line.
7. Only then: the minimum code that works.

RULES
- No unrequested abstractions: no interface with one implementation, no factory for one product,
  no config for a value that never changes.
- No boilerplate, no scaffolding "for later".
- Deletion over addition. Boring over clever. Fewest files possible.
- Shortest working diff wins — but only after understanding the problem.
- Two stdlib options the same size -> take the edge-case-correct one. Less code, not a flimsier algorithm.
- Mark a deliberate short-cut that has a real ceiling (global lock, O(n^2) scan, naive heuristic) with a
  `ponytail:` comment naming the ceiling and the upgrade path.

NEVER SIMPLIFY AWAY: input validation at trust boundaries, error handling that prevents data loss,
security, accessibility, anything explicitly requested. Real hardware needs its calibration knob.
NEVER LAZY ABOUT UNDERSTANDING: read the code the change touches, trace the real flow end to end, then
climb. Bug fix = root cause, not symptom.
LEAVE ONE RUNNABLE CHECK: non-trivial logic leaves one small runnable check behind. Trivial one-liners need no test.
```

## EDIT LIST (one writer run per file, this order)

**Class-count pin statement.** No run owns a `tests/test_ui_contract.py` edit: F11 adds zero classes and drops
zero classes. Every template run proves it by running that test file and pasting the raw result.

### R1 — `app/export.py` (NEW, part 1: constants + builder) — owner: agy

- Literal constants:
  - `TABLE_KEYS = {"butir": "item_table_15.1.csv", "opsi": "option_table_15.3.csv", "responden": "person_table.csv", "ringkasan": "summary_table.csv", "wright": "wright_map_measure.csv"}`
  - `HEADER_ROWS = {"butir": 2, "opsi": 2, "responden": 2, "ringkasan": 1, "wright": 2, "bandingkan": 1}`
  - `SHEET_TITLES = {"butir": "butir", "opsi": "opsi", "responden": "responden", "ringkasan": "ringkasan", "wright": "wright", "bandingkan": "bandingkan"}`
  - `COMPARE_HEADER = ["Nomor", "Butir", "Measure analisis pertama", "Measure analisis kedua", "Selisih (kedua − pertama)"]`
  - `COMPARE_NUMERIC = {0: "int", 2: "float", 3: "float", 4: "float"}`
  - `SUMMARY_NUMERIC = {2: "summary"}` and `TABLE_NUMERIC = {"ringkasan": SUMMARY_NUMERIC, "wright": WRIGHT_NUMERIC}` — the dictionary is the single source of truth for the per-table rule, used by the route (`numeric = TABLE_NUMERIC.get(table)`) and by the cell parity test, so a new per-table rule cannot be exercised by one and missed by the other. **[curated 26 Sep 2026: the wright rule landed in the module while the test still passed `numeric=None`, so the test kept failing against a fixed module.]**
  - `EXPORT_MAX_ROWS = 1_048_000`, `EXPORT_MAX_CELLS = 2_500_000`
  - `EXPORT_RATE_LIMIT = 30`, `EXPORT_RATE_WINDOW_S = 3600`
  - `EXPORT_TABLE_NOT_FOUND_MSG = "Tabel unduhan tidak tersedia untuk analisis ini."`
  - `EXPORT_RATE_MSG = "Batas unduhan Excel tercapai (30 unduhan per jam). Silakan coba lagi nanti."`
- `def build_xlsx(sheet_title: str, rows: list[list[str]], header_rows: int, numeric: dict[int, str] | None = None) -> bytes`
  - `wb = openpyxl.Workbook(write_only=True)`, `ws = wb.create_sheet(title=sheet_title)`, `labels = rows[header_rows - 1] if rows and header_rows >= 1 else []`
  - per cell: `value = "" if raw is None else str(raw)`; **only** `r_idx < header_rows` short-circuits (header rows are verbatim, never coerced). A blank DATA cell still resolves its format, exactly like the engine: `coerce_cell("", fmt)` returns `(None, fmt)`, so a blank cell in a numeric column keeps `0` / `0.00`, and its value becomes `None` (never `""`) before the cell is created. **[curated 26 Sep 2026: the cell parity test caught the platform writing `General` where the engine writes `0`; skipping blank data cells before resolving the format was the cause.]**
  - the format map is keyed on the **second** header row's labels (`NUMBER`, `MEASURE`, ...); `ENTRY` is a first-row label and is not a numeric column. **[curated 26 Sep 2026: a test that expected `ENTRY` to be an int was reading the wrong header row.]**
  - `numeric is None` → engine rule: `fmt = number_format_for_header(label)`, then coerce **only when `fmt` is not None**: `if fmt is not None: value, fmt = coerce_cell(value, fmt)`. That guard is the engine's own (`fill_sheet` does `if fmt is None: continue`), and it is load-bearing: `coerce_cell` converts any numeric-looking string even when the format is `None`, so calling it unguarded turns the identifier `007` into `7` and a 16-digit id into a float that loses precision. **[curated 26 Sep 2026: the first writer run shipped the unguarded call and Arc caught both symptoms on the real fixture.]**
  - otherwise `mode = numeric.get(c_idx)` (an unknown mode falls through to the header-name rule, and so does `numeric is None`): `"summary"` → `fmt = summary_value_format(value)`; `"int"` → `fmt = "0"`; `"float"` → `fmt = "0.00"`; then `value, fmt = coerce_cell(value, fmt)`; `"raw"` → `value, _ = coerce_cell(value, "0.00" if "." in value else "0")` with the format left unset, i.e. a real number in a General-formatted cell
  - `WRIGHT_NUMERIC = {0: "raw", 1: "raw", 3: "raw"}` is passed for the `wright` key, because the engine's wright sheet has **no second-row labels** on MEASURE / NR_PERSON / NR_ITEM: `fill_sheet` leaves those cells alone, so they stay real numbers with `General`. Reading them from CSV text without this rule ships numbers as text and Excel cannot calculate or sort them. **[curated 26 Sep 2026: the cell parity test failed on `[wright] '1.75' != 1.75`; the histogram columns (2, 4, 5) stay text, and the labelled columns 6-7 keep the header-name rule, both matching the engine.]**
  - set `cell.number_format = fmt` only when `fmt` is truthy; `ws.freeze_panes = f"A{header_rows + 1}"`; `wb.save(io.BytesIO())`; return the bytes
  - imports: `openpyxl`, `from openpyxl.cell import WriteOnlyCell`, `from raschlab.report import number_format_for_header, coerce_cell, summary_value_format`
- `def message_page(text: str, status_code: int, extra_headers: dict[str, str] | None = None) -> Response` returning a minimal HTML document (`<!doctype html>`, `lang="id"`, `<meta charset="utf-8">`, one `<p>` with the Indonesian text, one `<a href="/analyses">` back link) — no styling, no template file.
- **SELF-VERIFY (paste raw output):**
  `.venv/bin/python -c "import io, openpyxl, app.export as e; b=e.build_xlsx('t',[['ENTRY','MEASURE','PERSON'],['NUMBER','MEASURE','PERSON'],['1','-1.25','007'],['2','0.50','3251501001500027']],2); ws=openpyxl.load_workbook(io.BytesIO(b)).active; print([(c.value, type(c.value).__name__, c.number_format) for c in ws[3]])"` → `[(1,'int','0'), (-1.25,'float','0.00'), ('007','str','General')]`
  and `.venv/bin/python -m pytest -q` → 186 passed.

### R2 — `app/export.py` (same file, part 2: route) — owner: agy

- `router = APIRouter()`; `@router.get("/analyses/{id}/export")`; `def export_table(id: int, request: Request, table: str | None = None, db: Session = Depends(get_session)) -> Response` — `table` is declared as an **optional** query parameter so the API schema lists it while a missing key still reaches our own 404 (a required declaration would make FastAPI answer 422). **[added 26 Sep 2026 after the review pass.]**
- guard order exactly as the contract table; message constants imported from `app.explore` / `app.auth` (grep for where `PAGE_NOT_FOUND_MSG`, `ANALYSIS_NOT_FOUND_MSG`, `DATASET_NOT_FOUND_MSG`, `_gate_closed`, `_current_user` are defined before importing).
- rows for the five stored keys: `load_tables(analysis)` from `app.analysis`, take `TABLE_KEYS[key]`; `[]` or all-empty rows → 404 `EXPORT_TABLE_NOT_FOUND_MSG`.
- `bandingkan`: resolve both analyses (same owner + `done` rules), `build_compare_pairs` from `app.explore` on the two `item_table_15.1.csv` row lists, rows = `[COMPARE_HEADER] + [[p[0], p[1], p[2], p[3], p[4]] for p in res["pairs"]]`, `numeric = COMPARE_NUMERIC`. When the pair list is empty, still export the header row (an empty comparison is a real answer) — but the view only shows the control when both ids are set.
- caps check before building: `rows_count = len(rows)`, `cells = sum(len(r) for r in rows)`; over a cap → `message_page(f"Tabel ini memuat {rows_count} baris dan {cells} sel, melebihi batas unduhan Excel ({EXPORT_MAX_ROWS} baris / {EXPORT_MAX_CELLS} sel).", 413)`.
- rate limit before loading rows: `check_limit(f"export:{client_ip(request)}:{user.id}", EXPORT_RATE_LIMIT, EXPORT_RATE_WINDOW_S)`; refusal → `message_page(EXPORT_RATE_MSG, 429, {"Retry-After": str(retry_after)})`.
- success → `Response(content=build_xlsx(...), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={...})` with the two headers from the contract.
- **SELF-VERIFY:** `.venv/bin/python -c "from app.main import app; print(sorted(p for p in app.openapi()['paths'] if 'export' in p))"` (route list comes from `app.openapi()`, never from a hand-rolled scan of `app.routes`) and `.venv/bin/python -m pytest -q` → 186 passed.

### R3 — `app/main.py` — owner: agy

- `from app.export import router as export_router` next to the other three router imports, and
  `app.include_router(export_router)` after `app.include_router(explore_router)`.
- **SELF-VERIFY:** `.venv/bin/python -c "from app.main import app; print(sorted(getattr(r,'path','') for r in app.routes if 'export' in getattr(r,'path','')))"` → `['/analyses/{id}/export']`, and `.venv/bin/python -m pytest -q` → 186 passed.

### R4 — `tests/test_export.py` (NEW) — owner: agy

Eight tests, names literal:

1. `test_cell_parity_with_engine_workbook` — for each of `butir`, `opsi`, `responden`, `ringkasan`, `wright`: build our sheet with `build_xlsx` on the SAME rows the fixture produced, build the engine reference with `raschlab.report.write_workbook` over the same rows into a tmp dir, then compare cell by cell: `value`, `type()`, `number_format`.
2. `test_all_rows_not_the_500_row_page` — a fixture with more than 500 rows; `ws.max_row == len(csv_rows)`.
3. `test_guard_matrix` (parametrized) — anonymous 404; gate closed 404; other user's analysis 404; `status="running"` 303; `table=bogus` 404; stored file missing 404.
4. `test_identifier_columns_stay_text` — `PERSON`/`ITEM` label columns with `007` and a 16-digit id stay `str`; a `MEASURE` cell is `float` with `"0.00"`.
5. `test_response_headers` — content type, both `filename=` and `filename*=UTF-8''`, `Cache-Control: no-store`.
6. `test_bandingkan_matches_compare_pairs` — export rows equal `build_compare_pairs(...)["pairs"]` for two done analyses, and the header row equals `COMPARE_HEADER`.
7. `test_export_caps_and_rate_limit` — a monkeypatched table over `EXPORT_MAX_CELLS` → 413 whose body carries the numbers; the 31st call in the window → 429 with `Retry-After`.
8. `test_export_row_cap` — the same over `EXPORT_MAX_ROWS`: 413 whose body carries the real row and cell counts, the body is not a workbook, and the same request answers 200 again once the cap is raised. **[added 26 Sep 2026 after the review pass: the first version only exercised the cell cap.]**
- **SELF-VERIFY:** `.venv/bin/python -m pytest -q tests/test_export.py` green, then full `.venv/bin/python -m pytest -q` with the new count pasted raw.

### R5 — `app/templates/analysis.html` — owner: agy

- Four insertions, immediately after the heading line: `<h2>Rekap Responden</h2>` (L106, key `ringkasan`, aria `Unduh Excel rekap ringkasan`), `<h2>Tabel Butir (15.1)</h2>` (L140, `butir`, `Unduh Excel tabel butir`), `<h2>Tabel Opsi dan Distraktor (15.3)</h2>` (L197, `opsi`, `Unduh Excel tabel opsi dan distraktor`), `<h2>Tabel Responden</h2>` (L254, `responden`, `Unduh Excel tabel responden`).
- Markup exactly the three-line shape above, `href="/analyses/{{ analysis.id }}/export?table=KEY"`.
- **SELF-VERIFY:** `grep -c 'export?table=' app/templates/analysis.html` → 4; `grep -c 'aria-label="Unduh Excel' app/templates/analysis.html` → 4; `.venv/bin/python -m pytest -q tests/test_ui_contract.py` green; `git diff -- app/templates/analysis.html | grep -c '—'` → 0.

### R6 — `app/templates/explore.html` — owner: agy

- One insertion inside `#panel-wright`, after the `<p id="wright-meta">…</p>` line and before `<div id="wright-scale">`: key `wright`, aria `Unduh Excel data peta Wright`.
- **SELF-VERIFY:** `grep -c 'export?table=wright' app/templates/explore.html` → 1; ui-contract pytest green; em-dash diff count → 0.

### R7 — `app/templates/explore/fragment.html` — owner: agy

- One `{% if render_view == … %}` chain at the TOP of the file, emitting at most one control: `butir` → `table=butir`; `partisipan` → `table=responden`; `ringkasan` → `table=ringkasan`; `bandingkan` → only when `compare_ctx is defined and compare_ctx.from_id and compare_ctx.to_id`, href `/analyses/{{ analysis.id }}/export?table=bandingkan&from={{ compare_ctx.from_id }}&to={{ compare_ctx.to_id }}`.
- **SELF-VERIFY:** `grep -o 'export?table=' app/templates/explore/fragment.html | wc -l` → 4; ui-contract pytest green; em-dash diff count → 0.

### R8 — `app/templates/analyses.html` — owner: agy

- Desktop table: new `<th scope="col">Unduh Excel</th>` as the last column, and in the row loop a matching `<td>` carrying four `<a class="text-link">` links (`Butir`, `Opsi`, `Responden`, `Ringkasan`) with aria-labels naming the table and the run id.
- Mobile `file-cards`: the same four links inside the card's existing `<div class="action-bar">`.
- **SELF-VERIFY:** `grep -c 'export?table=' app/templates/analyses.html` → 8 (four in each of the two layouts); ui-contract pytest green; `git diff -- app/templates | grep -c '—'` → 0.

### R9 — `scripts/verify_explorer.py` — owner: agy

- Ten new checks (4 on `/analyses/{id}`, 5 on the explorer views, 1 on `/analyses` first row): each clicks the control, captures the downloaded bytes, opens them with `openpyxl`, and compares the sheet's cells against the values rendered in that page's DOM (paginated tables compare their rendered rows as an ordered subset; the Rekap section compares each visible value against the `VALUE` column), plus the three response headers.
- `EXPECTED_TOTAL` moves from 195 to 205 on purpose; if the checks are split differently, move the constant to the real number and report it.
- **SELF-VERIFY:** `.venv/bin/python scripts/verify_explorer.py` → 205/205 with the tail pasted raw.

## ASSUMPTIONS (verified by Arc at curation time, not inherited)

1. `analysis.html` is 312 lines with THREE `<table class="data-table">` blocks (Butir L139-194, Opsi L196-251, Responden L253-308) plus a "Rekap Responden" definition list (L105-137). The Ringkasan control therefore sits on the Rekap section and exports the full `summary_table.csv`; the harness compares that one against the `VALUE` column. The planner's ASSUMPTION 1 guessed this and got the line anchors close but not exact.
2. `analysis.html` already renders alerts from `?msg=` (L21-26) and uses `.action-bar` (L40) and `.btn btn--secondary` (L100) — the classes the new controls reuse.
3. `app/explore.py` defines `VIEWS = ("wright", "butir", "partisipan", "ringkasan", "bandingkan")`, `FRAGMENT_VIEWS` without `wright`, and reads `view`, `fragment`, `q_item`, `q_person`, `page_item`, `page_person`, `from`, `to` (L332-350). `wright_map_measure.csv` is loaded at L380 and drives `build_wright_payload`.
4. `build_compare_pairs(item_rows_from, item_rows_to)` returns `{"pairs", "matched", "unmatched_from", "unmatched_to", "key_used", "empty_reason"}`; each pair is a 5-list `[entry, label, measure_from, measure_to, delta]` with the delta rendered by `Decimal` + `ROUND_HALF_UP` (L155-280). The rendered header is `Butir` (colspan 2), `Measure analisis pertama`, `Measure analisis kedua`, `Selisih (kedua − pertama)`.
5. `wright_map_measure.csv` and `wright_map_frequency.csv` carry TWO header rows for the engine's workbook (`MEASURE_HEADER_ROW_1/2`, `FREQ_HEADER_ROW_1/2`), and their second row has empty labels except `PERSON_ENTRIES`/`ITEM_ENTRIES`, which are not in the engine's numeric table — so wright data cells stay text in the engine's own workbook too, and parity holds by construction.
6. `summary_table.csv` is `SECTION,STATISTIC,VALUE` + one blank row; the engine workbook formats the VALUE column with `summary_value_format`.
7. `app/ratelimit.py` exposes `check_limit(key, limit, window_s) -> (allowed, retry_after)` and `client_ip(request)`; `app/ingest.py` L225-239 is the usage pattern.
8. `app/main.py` L9-12 imports routers and L48-51 calls `app.include_router(...)`; the `App(FastAPI)` subclass unwraps `original_router`, so both `app.routes` and `app.openapi()["paths"]` are trustworthy route sources here.
9. `openpyxl 3.1.5` is already a dependency; the engine package is pinned at `c41c396` and its `report` module imports cleanly inside the web venv (verified by running `number_format_for_header`/`coerce_cell` on this box).

## RISKS

1. `explorer.js` drives pager links and may intercept `<a>` clicks inside panels, hijacking an export link. The harness (R9) actually downloads on all five views, so this is detected, not assumed away. A fix in JS is out of scope → stop and escalate.
2. The 30/hour limit can trip a second harness run inside the same hour (10 downloads per run). Tests monkeypatch the limiter; the harness must not be starved — if it is, the harness resets the counter through a documented hook rather than raising the owner's limit.
3. Engine conventions could differ from ASSUMPTIONS 5-6 for wright/summary; the parity test is the arbiter and it is written before the templates.
4. `bandingkan` could drift from the screen if the fragment renders a client-side filter; the harness compares cells against the DOM for that view, so drift fails loudly.
5. A writer adding a class moves the ui-contract pins; caught by that run's own verify step, remedy is a revert of that run, never a pin edit.
6. Placement: a right-aligned `.action-bar` button directly under a table heading is the app's existing action convention (F9 aligned every primary action to x=1256), but if the audit finds the rhythm wrong the fix is a spacing change in `app.css`, which is out of this contract and needs its own round.

## ROLLBACK

`cd /root/projects/raschlab-web && git revert --no-edit <F11 commits>` if pushed, otherwise
`git reset --hard 4c6da59`. Nothing else to undo: no migration, no stored artifact, no env or secret change.
If F11 is already live, Dada re-points Cloud Run at the previous revision (revision-level rollback, one command).

## F11b — unduhan sisi frekuensi (Dada, 26 Sep 2026: "bikin aja gas")

**WHY.** `wright_map_frequency.csv` is written by the engine on every run and rendered by no page, so it was the one
stored table that could not leave the web at all. Dada's answer on 26 Sep 2026 to "Mau kutambahin kontrol untuk sisi
frekuensi?" was **"bikin aja gas"**, so the wright panel now carries two controls instead of one.

**Non-negotiables (measured, do not re-derive):**

1. Key `frekuensi` -> `wright_map_frequency.csv`, **2 header rows**, sheet title `frekuensi`.
2. **Type rule, and the only deliberate deviation from the engine in this whole feature.** The engine's OWN workbook
   writes every cell of its `wright_frequency` sheet as TEXT with format `General` (measured by handing the real
   `wright_map_frequency.csv` from `/root/raschlab-runs/kuantitatif/` to `raschlab.report.write_workbook`: R3C1 is
   `'2.5'/str`, R4C10 is `'83'/str`). The cause is the engine's own lookup: the format comes from the label in the
   LAST header row, that row is empty for columns 1-8, and `PERSON_ENTRIES`/`ITEM_ENTRIES` are not in
   `raschlab.report.NUMBER_FORMATS`. Shipping that verbatim would give Dada counts he cannot sum, which is the whole
   reason this feature exists. So `FREQ_NUMERIC = {0: "float", 1: "int", 2: "int", 5: "int"}` types `MEASURE`,
   `NR_PERSON`, `NR_PERSON_PRESENT`, `NR_ITEM`; `ITEMS`, `PERSON_HIST`, `PERSON_FREQ_HIST`, `ITEM_HIST`,
   `PERSON_ENTRIES`, `ITEM_ENTRIES` stay TEXT (an entry cell holds several numbers, e.g. `924 1237`). **Values still
   equal the stored value exactly**; only type and format move, and the test must enforce both halves.
3. Two controls in the wright panel: `Unduh measure` (`table=wright`) and `Unduh frekuensi` (`table=frekuensi`), both
   `.btn .btn--secondary` inside the existing `.action-bar`, both with a mandatory `aria-label` naming the side.
   The frozen label `Unduh Excel` cannot name two tables in one panel, so it is replaced **in that panel only**.
4. `scripts/verify_explorer.py`'s `build_wright_frequency_csv()` currently returns a TWO-COLUMN toy
   (`MEASURE,FREQUENCY\n-3.50,5\n3.20,3\n`) while the engine's file has **10 columns and 2 header rows**. A check
   written against that toy would measure nothing, so the fixture is repaired to the real shape in the same run.

**EDIT LIST (one writer run per file, this order):**

### R12 — `app/export.py`
- `TABLE_KEYS` += `"frekuensi": "wright_map_frequency.csv"`; `HEADER_ROWS` += `"frekuensi": 2`; `SHEET_TITLES` += `"frekuensi": "frekuensi"`.
- New `FREQ_NUMERIC = {0: "float", 1: "int", 2: "int", 5: "int"}` and `TABLE_NUMERIC` += `"frekuensi": FREQ_NUMERIC`.
- Nothing else moves: guard order, caps, rate limit, response headers, and the `bandingkan` branch stay untouched.

### R13 — `app/templates/explore.html`
- In the wright panel's `.action-bar` (currently one control at line 61 with label `Unduh Excel` and
  `aria-label="Unduh Excel data peta Wright"`), relabel that control to `Unduh measure` with
  `aria-label="Unduh Excel peta Wright sisi measure"`, and add a second `.btn .btn--secondary` anchor to
  `/analyses/{{ analysis.id }}/export?table=frekuensi` labelled `Unduh frekuensi` with
  `aria-label="Unduh Excel peta Wright sisi frekuensi"`.
- No other page changes: the four result-page controls and the list-page links keep the label `Unduh Excel`.

### R14 — `tests/test_export.py`
- Extend `test_cell_parity_with_engine_workbook` to include key `frekuensi` -> engine sheet `wright_frequency`, with
  the two-half rule from Non-negotiable 2: every cell equals the RAW stored value (`str(our) == raw`), the four
  numeric columns are `int`/`float`, and every other column is `str`. The existing five keys keep the strict
  value+type+format comparison untouched.
- Add `test_export_frekuensi_route`: the route answers 200 with the XLSX media type, the sheet is named `frekuensi`,
  its row count equals the stored CSV's, and a mid-table count cell is `int` while its `ITEMS` cell in the same row is `str`.

### R15 — `scripts/verify_explorer.py`
- Repair `build_wright_frequency_csv()` to the engine's real shape: two header rows
  (`MEASURE,NR_PERSON,NR_PERSON_PRESENT,PERSON_HIST,PERSON_FREQ_HIST,NR_ITEM,ITEMS,ITEM_HIST,PERSON_ENTRIES,ITEM_ENTRIES`
  then eight empty fields and `PERSON_ENTRIES,ITEM_ENTRIES`), well-formed rows of exactly 10 fields, at least three
  data rows, one of them with several numbers in `PERSON_ENTRIES`.
- Add ONE check to `group_l_export`: the wright panel DOM offers exactly two export controls with the labels
  `Unduh measure` and `Unduh frekuensi`, and `table=frekuensi` answers 200 with a sheet named `frekuensi` whose row
  count equals the stored CSV's and whose `NR_PERSON` cell in the first data row is a number.
- `EXPECTED_TOTAL` 205 -> 206.

**ACCEPTANCE (measured, not asserted):** `pytest -q` green with the raw count pasted (baseline 194);
`scripts/verify_explorer.py` green at its new total with the raw line pasted; the two new controls 44 px with a
visible focus ring and contrast above 4.5:1 in both themes; no em dash.

## F12 — langkah Pengaturan sebelum analisis (Dada, 26 Sep 2026)

**Owner decisions (quoted, do not re-open).** Dada: *"oke pas unggah harusnya kan ada config, kalau misal mereka
engga punya config, mereka bisa configure sendiri. Tapi kalau bisa udah default semua, kalau emang ada yang mau
diganti baru bisa diganti, contoh threshold misfit 1.5, kalau butuh yang lebih teliti bisa jadi 1.2"*. Answered in a
clarify the same day: (1) the settings live as a **separate step before the analysis runs**, not a panel on the
upload page; (2) first-stage knobs are **misfit threshold + mode + digits**; (3) an uploaded `.CON` next to tabular
data has its **`KEY1`, `CODES`, `MISSCORE`** honoured, everything else default; (4) changing settings **creates a NEW
analysis** and existing analyses keep their own settings.

**Non-negotiables (measured, do not re-derive):**

1. **The threshold ends up in ONE place and only one.** Today `1.50` is hardcoded in FIVE spots: `app/analyze.py:42`
   (`MISFIT_THRESHOLD`, used at `:261`), `app/templates/analysis.html:99` (the band sentence), the frozen explorer
   copy `app/templates/explore.html:68` plus `INTERFACE.md:412/416`, `app/static/explorer-charts.js:119` and `:471`
   (the two comparisons) with `:123`, `:409`, `:426` as their copy, and `app/static/explorer.js:586` and `:593`.
   After F12 the single source is **`MISFIT_THRESHOLD_DEFAULT = 1.5` in `app/analysis.py`**, feeding
   `PARAMS_DEFAULT["misfit"]`; every other site reads the analysis's own stored value. Proof is a grep, not an opinion.
2. **Validation, exactly:** misfit a float **0.5 to 5.0** (step 0.05, default **1.50**); `mode` one of
   **`compat` / `exact`** (the engine's `--mode` choices are exactly those two, default `compat`); `digits` an
   integer **1 to 4** (default 2). Invalid input renders the settings page at **422** with Indonesian copy. Never a
   500, never a silent fallback to the default.
3. **`.CON` directives ride in `Dataset.summary_json["control"]`**, the same shape the Winsteps path already
   stores (`app/ingest.py:334-335`), and `write_inputs()` (`app/analysis.py:301`) emits `KEY1`, `CODES` and
   `MISSCORE` from it into the generated `analyze.CON`. **No database migration.**
4. **No new CSS class.** The pins in `tests/test_ui_contract.py` (145 used / 159 defined) must not move, and all 23
   classes the settings screen needs already exist in `app.css` (verified). Page templates move **12 to 13** on
   purpose, pinned in the same test.
5. **Exports stay verbatim:** the threshold is a display rule and must not enter any XLSX sheet.
6. Old analyses keep their own `params_json`; the results page renders the settings that analysis actually ran with.
7. `scripts/verify_explorer.py:941` matches `Butir misfit \(INFIT MNSQ [≥>=]+ 1,50\)`, so the **default label must
   still read `1,50`** and the harness must stay green at its current total.

**Edit list (one writer run per group):** R17 `app/analysis.py` (constants, `parse_settings_form`, `run_for_dataset`,
`write_inputs` control) · R18 `app/analyze.py` + `analysis_settings.html` · R19 `dataset_detail.html` +
`analysis.html` · R20 `app/ingest.py` + `datasets.html` · R21 `app/explore.py` + `explore.html` ·
R22 `explorer-charts.js` + `explorer.js` · R23 `tests/test_analysis_settings.py` + `test_ui_contract.py` (12 -> 13).

**ACCEPTANCE (measured, not asserted):** `pytest -q` green with the count pasted (baseline **195**);
`scripts/verify_explorer.py` green at **206/206**; a route-level test per new form field; a test that uploads a
`.CON` with `MISSCORE` and asserts the generated `analyze.CON` carries it and that scoring changes; the
byte-identity test still green when no `.CON` is present; the grep proof from Non-negotiable 1; a test proving an
existing analysis's params are untouched by a new run; Hallmark audit of the new screen.

**OUT OF SCOPE:** exposing `anchors` / `pdfile` / `lconv` / `person_order`, saved presets per user, any migration,
any change to the engine repo.

**Review pass (26 Sep 2026, independent model, session `20260926_195114_9fdfd7`).** Reported 0 critical / 3 major /
4 minor. **Accepted and fixed:** a `KEY1` character outside `CODES`, and a nonsense `MISSCORE`, both previously reached
`analyze.CON` (they are now rejected by `validate_control_directives()` in `app/analysis.py`, the one place the rules
live, called by the upload route and by `write_inputs()`); and the test named for the `.CON` upload never uploaded
anything (`tests/test_analysis_settings.py` now posts a real `.con` beside a CSV and asserts the honoured directives
reach the generated file while `NAMELEN` does not). **Declined with a citation:** "`CODES` must be a subset of `ABCDE`"
and "`MISSCORE` must be numeric" — `raschlab/docs/format.md` defines `CODES` as the response alphabet (`01` for binary
data, `1234` for a rating scale) and states that a non-numeric `MISSCORE` is a character list whose characters count as
missing, so enforcing either rule would reject control files the engine accepts.

**Defect found while building this, not an F12 regression.** The results page resolved the misfit column with the
literal cell `INFIT MNSQ`, which the engine never writes: it writes `INFIT` and `MNSQ` on two header rows. Every real
analysis therefore rendered `n_item = 0` and no misfit section at all, while fixtures carrying the single cell kept the
suite and the explorer harness green. `_infit_mnsq_column()` now accepts both layouts, and a test drives both.

## ACCEPTANCE (measured, not asserted)

1. `python -m pytest -q` green with the count pasted raw (baseline 186).
2. Cell parity with the engine's own workbook, per sheet, compared automatically (values, types, number formats).
3. Exported rows equal stored CSV rows for a fixture above 500 rows — the 500-row page is never the export.
4. Guard matrix answers exactly as the contract table says.
5. Identifier columns stay text; numeric columns are numbers carrying the engine's format.
6. `scripts/verify_explorer.py` green with the new checks (`EXPECTED_TOTAL` moved on purpose).
7. Hallmark audit of the three touched pages: 0 critical; every new control keyboard reachable, ≥44 px, Indonesian, no em dash; both themes checked.
8. Live check after deploy: the three pages render the controls, one real download opens in openpyxl with the right sheet and row count, and `/health` reports the new commit.

## OUT OF SCOPE (explicit)

Whole-workbook multi-sheet export; CSV/ZIP download; "download every run"; e-mail or scheduled delivery;
chart/PNG/PDF export; share links; any change to the engine repo; any DB migration; any change to existing table
markup, pagination, or explorer JS/CSS.
