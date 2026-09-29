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
