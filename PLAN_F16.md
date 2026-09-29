# F16 — attach a delete list to a run from the settings screen (frozen contract, 29 Sep 2026)

## Why

`PARAMS_DEFAULT` carries `"pdfile": None` (`app/analysis.py:71`) and the in-process engine call accepts
`pdfile_path` and `idfile_path` (`run_analyze`, raschlab `8acd8c9`), but no screen asks for either, so the
only way to run a cleaned analysis is a terminal. The owner must be able to produce the clean version from
the web, and the run must record which list it used, because F14 shows what got dropped and the reader must
be able to see what dropped it.

## 1. Scope of THIS run (A of two)

Files this run may write: `app/analysis.py`, `tests/test_delete_list_inputs.py` (new). Nothing else. Run B
(the two templates + `app/analyze.py` + the page showing the record) follows once A is green, so A must not
invent template changes and must not touch `app/analyze.py`.

## 2. Frozen interface

- `PARAMS_DEFAULT` gains `"idfile": None` next to `"pdfile": None`.
- `parse_delete_list(filename: str, content: bytes) -> dict`
  - Accepts extensions `.txt`, `.csv`, `.dat` (any case). Rejects anything else with
    `AnalysisError("Daftar hapus harus berupa berkas teks (.txt, .csv, atau .dat).")`.
  - Rejects content over `DELETE_LIST_MAX_BYTES = 2 * 1024 * 1024` with
    `AnalysisError("Daftar hapus terlalu besar (maksimal 2 MB).")`.
  - Rejects content that is not one of utf-8, utf-8-sig, latin-1 (tried in that order) with
    `AnalysisError("Daftar hapus harus berupa teks biasa, bukan berkas biner.")`.
  - Rejects content with no non-empty line, after `strip()`, with
    `AnalysisError("Daftar hapus kosong.")`.
  - Returns `{"name": str, "text": str, "rows": int, "sha256": str, "bytes": int}` where `rows` counts
    non-empty stripped lines, `sha256` is the hex digest of the ORIGINAL bytes, `bytes` is `len(content)`,
    and `name` is the basename with any directory part removed and length capped at 120 characters.
- `run_for_dataset(db, dataset, params=None, delete_lists=None) -> Analysis` — the new fourth argument is
  optional and defaults to `None`. `delete_lists` is a dict keyed by `"pdfile"` and `"idfile"`, each value a
  dict as returned by `parse_delete_list`.
  - Each supplied list is written into the run's temporary directory as `pdfile_input.TXT` /
    `idfile_input.TXT` and passed to the engine as `pdfile_path=` / `idfile_path=`. A list that is not
    supplied passes `None`, which is the current behaviour.
  - On success, each supplied list is ALSO stored as an `AnalysisFile` row on the analysis, with
    `filename="input_pdfile.TXT"` / `"input_idfile.TXT"`, gzipped with `mtime=0.0` like the output rows, and
    the same `sha256` field the output rows carry. `OUTPUT_FILES` and the existing output rows are
    untouched: these are extra rows.
  - `params_json` records what was used in place of the raw text: for each supplied list,
    `merged["pdfile"]` / `merged["idfile"]` becomes `{"name", "sha256", "rows", "bytes"}` (no `text`), and
    stays `None` when nothing was supplied. The stored JSON must never contain the list's text.
- A failed run keeps today's behaviour: `AnalysisError` propagates, `analysis.status` becomes `"failed"`.
  A stored input row must not be written for a run that failed.

## 3. Rules

- Validation happens BEFORE the engine is called. An invalid upload must never reach `run_analyze` and must
  never leave a half-written analysis behind.
- The list text never gets logged, never enters an error message, and never enters `params_json`.
- Indonesian copy, straight quotes, no em dash. Existing copy and code style untouched.
- If a test fails because the source is wrong, report it with raw output; never weaken an assertion.

## 4. VERIFY

    cd /root/projects/raschlab-web && .venv/bin/python -m pytest tests -q        # BEFORE: note the baseline
    cd /root/projects/raschlab-web && .venv/bin/python -m pytest tests -q        # AFTER: baseline + 6
    cd /root/projects/raschlab-web && .venv/bin/python -m pytest tests/test_delete_list_inputs.py -q

The six tests, all driving `run_for_dataset` with a small in-memory dataset and monkeypatching
`app.analysis.run_analyze` so no real engine run is needed:

1. a valid list reaches the engine as `pdfile_path` pointing at a file whose bytes equal the uploaded text,
   and the engine receives `None` for `idfile_path` when only one list was supplied;
2. the run's `params_json` carries `{"name", "sha256", "rows", "bytes"}` for the supplied list and no `text`
   key anywhere in the serialised JSON;
3. an `AnalysisFile` row named `input_pdfile.TXT` exists for that analysis and gunzips back to the exact
   uploaded bytes, while `OUTPUT_FILES` output rows still exist unchanged;
4. `.exe` is refused with the extension message and the engine is never called;
5. an empty list is refused with the empty-list message and the engine is never called;
6. a list of 2 MB + 1 byte is refused with the size message.

Also report `git diff --stat` for the two paths and the raw pytest output of all three commands.


## 5. Amendment by Arc after run A (29 Sep 2026)

Run A reported three dead branches in section 2, all confirmed by reading the code:

1. The encoding order `utf-8, utf-8-sig, latin-1` made `utf-8-sig` unreachable, so a list saved with a BOM
   kept a stray U+FEFF on its first line. Order is now `utf-8-sig` first (identical for BOM-less utf-8).
2. Because latin-1 decodes every byte sequence, the binary branch could never fire and a `.txt` upload of
   binary data was accepted as a list. `_looks_binary(text)` now refuses a NUL byte or a run of control
   characters no numbering list contains.
3. `parse_delete_list` returned the sha of the ORIGINAL bytes while `run_for_dataset` wrote a re-encoded
   copy, so a latin-1 list stored a row whose sha did not match. The return dict now also carries
   `content` (the original bytes) and the writer writes those, so the audit row, its sha and `params_json`
   all describe the same bytes.

Three tests cover the three fixes. Suite after: 247 passed.


## 6. Run B scope (frozen, 29 Sep 2026)

Run A is committed (`412e98d`) and verified against the owner's real 206-row list: the engine deletes the
same 205 people as the archived clean run, the audit row round-trips to the same bytes, and no text reaches
`params_json`. Run B puts the upload on the screen and makes a run say which list it used.

Files this run may write, and nothing else: `app/analyze.py`, `app/templates/analysis_settings.html`,
`app/templates/analysis.html`, `tests/test_delete_list_settings.py` (new).

### 6.1 Route (app/analyze.py, `post_dataset_analyze` at line 221)

- Two new optional upload parameters with FastAPI's `File`: `pdfile: UploadFile | None = File(None)` and
  `idfile: UploadFile | None = File(None)`. The handler stays a plain `def` and reads bytes through
  `upload.file.read()`, matching the module's existing synchronous style.
- An upload counts as supplied only when it has a filename after `strip()`. An empty file input (filename
  `""`) is treated as absent, which is what a browser sends when the user picks nothing.
- Each supplied upload goes through `parse_delete_list(upload.filename, blob)` BEFORE the rate limit and
  before the engine. On `AnalysisError` the handler re-renders `analysis_settings.html` with status 422 and
  the same context shape it already uses for a bad threshold, so the message lands in the same error block.
- On success it calls `run_for_dataset(db, dataset, params, delete_lists=<only the supplied ones>)`.
- `params_json` recording and the audit row are already run A's job: do not duplicate any of it here.

### 6.2 Settings form (app/templates/analysis_settings.html)

- The form gains `enctype="multipart/form-data"`; without it the browser posts only the filename and the
  upload silently arrives empty.
- After the Desimal field, two `field` blocks in the file's existing style, each a `label`, an
  `input type="file"` with `accept=".txt,.csv,.dat"`, and a `field-hint`:
  - `Daftar hapus peserta (opsional)` with hint `Nomor baris peserta yang dikeluarkan sebelum penilaian, dalam format daftar hapus mesin. Maksimal 2 MB. Isi berkasnya tidak disimpan di pengaturan; yang dicatat hanya nama, jumlah baris, dan sidik jarinya.`
  - `Daftar hapus butir (opsional)` with the same hint, first word `butir`.
- No new CSS class and no new colour: reuse `field`, `field-label`, `field-input`, `field-hint`.

### 6.3 The run says what it used (app/analyze.py context + app/templates/analysis.html)

- The analysis page context gains `delete_lists`: a list of `{"label", "name", "rows", "sha256_short"}`
  for each of `pdfile` / `idfile` recorded in the run's `params_json`, read defensively (a legacy
  `params_json` without these keys, or with `None`, yields an empty list; a malformed entry is skipped, never
  raised). `label` is `Daftar hapus peserta` / `Daftar hapus butir`, `sha256_short` is the first 8 hex
  characters of the recorded sha, uppercase.
- `analysis.html` renders them in the existing metadata grid next to Versi Mesin / Waktu Eksekusi / Mode /
  Desimal, one row per list, as plain label and value text reusing the grid's existing classes. Nothing is
  rendered when `delete_lists` is empty: no empty row, no placeholder.
- Number formatting follows the page: `rows` goes through the existing `id_num` filter.

### 6.4 VERIFY (run B)

    cd /root/projects/raschlab-web && .venv/bin/python -m pytest tests -q     # BEFORE: note baseline (expect 247)
    cd /root/projects/raschlab-web && .venv/bin/python -m pytest tests -q     # AFTER: EXPECTED baseline + 6
    cd /root/projects/raschlab-web && .venv/bin/python -m pytest tests/test_delete_list_settings.py -q

Six tests in `tests/test_delete_list_settings.py`, monkeypatching `app.analysis.run_analyze` so no real
engine run happens:

1. a POST with a three-line `.txt` as `pdfile` returns 303, and the created analysis has
   `params_json["pdfile"]` `{name, sha256, rows, bytes}` with `rows == 3` and `text` absent;
2. the same POST leaves `params_json["idfile"]` as `None`;
3. a POST with `x.exe` returns 422, the response body carries the extension sentence, and no new Analysis
   row exists for that dataset;
4. a POST with both inputs empty records `pdfile` and `idfile` as `None` and still creates the analysis;
5. `GET /analyses/{id}` for a run whose `params_json` carries a pdfile shows the list's name, its row count
   through `id_num`, and its 8-character uppercase sha prefix;
6. the same GET for a run with no list shows none of those strings.
