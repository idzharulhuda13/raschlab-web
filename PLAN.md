# PLAN — RaschLab Web, F2 "Ingest"

Provenance: brief `/root/.hermes/profiles/personal-assistant/cache/scratch/brief_f2_ingest.md` →
planner role run `xiaomi/mimo-v2.6-flash` via commandcode, session `20260924_080336_5ae3ef`
(`/root/.hermes/profiles/planner/plans/2026-09-24-f2-ingest.attempt2.md`; attempt 1 died on a provider
mid-stream drop at 07:58 and was killed) → curated here by Arc 24 Sep 2026.
Repo state at planning time: `/root/projects/raschlab-web`, `main`, HEAD `3df86c0`, deployed live on
Cloud Run (revision `00006-p4r`, gate open) + Neon Postgres.

Executor key: **agy** = writer run (1-2 edits, `--stdin`), **Arc** = verify/commit/render/deploy.
Phase 2 (any agy run) starts only after this file exists. A writer run never runs `alembic upgrade`.

## Decisions (question → choice → one-line reason)

- **D1 Storage backend: gzip'd raw bytes in a Postgres `bytea` column, behind `app/storage.py`.** Reason: no
  persistent disk exists, a dataset delete is one SQL DELETE (F4 stays transactional), Neon free (0.5 GB) holds
  ~30 worst-case 16 MiB files and real TBS files are ~0.5-1 MB. GCS is a later swap: keep every raw-byte
  read/write inside `storage.py`; a GCS impl then replaces that module and adds a `storage_key` column in its own
  migration, routes never change.
- **D2 CSV/XLSX parsing lives in the platform (`app/parsers.py`), not the engine.** Reason: the engine is
  parity-verified and frozen; adding an input reader re-opens a verified artifact and drags input concerns into a
  CLI whose contract is `.CON` + `.prn`. Drift is controlled by NOT duplicating scoring: the adapter emits only
  `(labels, rows)`-shaped data plus a control dict, classification rules live once in the platform's mapping
  module, and a skip-if-absent test cross-checks our `.CON` reader against engine `parse_control`.
- **D3 F2 takes NO engine dependency; the packaging decision is deferred to F3.** F2's "done when" never runs
  estimation. F3 recommendation to carry to Dada: vendor at a pinned SHA (`vendor/raschlab/`; engine is frozen so
  vendoring cannot rot silently) because making the parity engine public is a product-visibility call only Dada can
  make, and build tokens add Cloud Build auth surface for no F2 benefit. **FLAGGED FOR DADA before F3**, not now.
- **D4 Two ingest paths, not four.** Path A = one wide table file (CSV or XLSX, same code path after
  XLSX-first-sheet → rows). Path B = Winsteps pair (`.CON` + fixed-width `.prn`). CUT: `.CON` + delimited data
  (the engine itself cannot read it), legacy `.xls`, multi-sheet selection, anchor/person-delete files (F3+).
- **D5 Value mapping + missing rule.** Canonical cell classes: `correct` / `incorrect` / `missing`. Path A
  defaults: missing = tokens `{"", "na", "n/a"}` (case-insensitive, matches pandas default NA so the proof is
  honest); if remaining tokens are exactly `{0,1}` preselect `1=correct, 0=incorrect`. Path B defaults from
  control: `key = KEY1`, `codes = CODES` (default `ABCDE`); cell = missing iff char not in codes (mirrors engine
  `score()`), correct iff `char == key[j]`. The user overrides everything in the preview. **Commit is blocked while
  any distinct token is unassigned** — that block IS the missing-value sanity gate, and it makes wrong-key /
  wrong-missing-token (the documented #1 source of wrong results) impossible to commit silently. The rule is one
  pure function used by preview, commit and tests, so it cannot drift from itself.
- **D6 Preview: raw bytes stored at upload, matrix never stored.** On POST: parse in-request under caps (16 MiB/file,
  1,000,000 cells, openpyxl `read_only` with row abort), write `datasets` row `status='staged'` + gzip raw +
  `summary_json` (shape, item labels, distinct tokens+counts, per-item missing), redirect to `GET /datasets/{id}`.
  Preview shows first 10 rows × first 12 columns (inner scroll container, "+N" notes), token inventory with mapping
  selects, per-item missing table for items with missing > 0 plus totals, warnings (all-missing item, all-missing
  person count, unassigned tokens). Commit re-parses stored raw with the final mapping and flips `status='ready'`.
  Storing only raw keeps Neon small and keeps the stored artifact the single source of truth.
- **D7 Missing-count proof that can fail: two independent layers, exact equality.** (1) Golden constants hardcoded
  in the test (derived combinatorially, independent of any parser): CSV per-item missing
  `[11,10,10,10,11,10,10,10,10,11,10,10,10,11,11,10,10,10,11,11,10,10,10,11,11,10,10,10,11,11,10,10,10,11,10,10,10,10,11,10]`
  (sum 413); `.prn` per-item missing `[3,3,2,3,2,3,2,3,3,2,3,2,3,2,3,3,2,3,2,3]` (sum 52). (2) Cross-check against
  pandas computed a different way (`read_csv` NA counts; `read_fwf` with explicit colspecs for `.prn`). Both
  assertions are `==` on full length-40 / length-20 lists plus shape asserts (300x40, 60x20); a one-cell parser
  shift fails both. pandas goes in `requirements-dev.txt` only.

## PLAN

1. **[agy R1] Schema.** Edit `app/models.py`: append `Dataset` in house style (int PK, epoch-second `BigInteger`
   timestamps, explicit nullable, indexed FK). Create `alembic/versions/0003_ingest.py` (revises `0002`, raw-SQL
   style like `0002_auth.py`, downgrade restores `schema_version='2'`). Table `datasets`: `id SERIAL PK`,
   `user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE`, `filename TEXT NOT NULL`,
   `kind TEXT NOT NULL` (`delimited|winsteps`), `format TEXT NOT NULL` (`csv|xlsx|prn`), `status TEXT NOT NULL`
   (`staged|ready`), `n_persons INTEGER NOT NULL`, `n_items INTEGER NOT NULL`, `item_labels_json TEXT NOT NULL`,
   `mapping_json TEXT NOT NULL`, `summary_json TEXT NOT NULL`, `raw_gzip BYTEA NOT NULL`, `raw_bytes BIGINT NOT NULL`,
   `created_at BIGINT NOT NULL`, `committed_at BIGINT NULL`; `CREATE INDEX ix_datasets_user_id ON datasets (user_id)`;
   `UPDATE app_meta ... '3'`. Verify: `alembic heads | grep 0003` + offline SQL `grep -c 'CREATE TABLE datasets'` = 1.
2. **[agy R2] Storage + dep.** Create `app/storage.py` (~50 lines): `MAX_UPLOAD_BYTES = 16*1024*1024`,
   `MAX_CELLS = 1_000_000`, `compress(raw) -> bytes` (gzip, `mtime=0`), `decompress(blob) -> bytes`, both raising a
   named error over the cap. Edit `requirements.txt`: add `openpyxl>=3.1`. Verify: gzip round-trip one-liner.
3. **[agy R3] Parsers.** Create `app/parsers.py` (~280 lines), pure functions, no FastAPI imports:
   `parse_delimited(raw: bytes)` (utf-8-sig, delimiter sniff among `,;\t` by first-line majority, header = item
   labels, col 0 = person label iff header lowercased in `{id,nama,name,no,respondent,person}`, drop all-empty rows,
   enforce `MAX_CELLS` while building), `parse_xlsx(raw: bytes)` (openpyxl `read_only`, first sheet, integral floats
   → int strings, `None` → `""`, row/cell abort), `parse_control(raw: bytes)` (read keys
   `ITEM1 NI NAMLEN KEY1 CODES DATA` from `&INST..&END`, `;` comments, `KEY1` stays string, `len(KEY1)==NI`
   enforced), `parse_prn(raw, control)` (mirror engine `reader.py`: `labels = line[0:namlen]`,
   `row = line[item1-1 : item1-1+ni].ljust(ni)`), `classify(...)` per D5, `missing_per_item(...)`,
   `distinct_tokens(...)`, `validate_mapping(...)` returning the unassigned-token list. Verify: `ast.parse` + import.
4. **[agy R4] Fixtures.** Create `tests/fixtures/make_samples.py` (~70 lines) writing `sample_300x40.csv`,
   `sample_winsteps.CON`, `sample_winsteps.prn` per the exact formulas below; run it once; commit all four. CSV:
   header `id,I01..I40`; row r (0-based), item col c (0..39); id = `P{r+1:04d}`; missing iff `(7*r + 13*c) % 29 == 0`,
   token `"NA"` if r even else `""`; else `"1" if (r + 2*c) % 5 else "0"`; comma, LF, utf-8. PRN: 60 rows,
   `NAMLEN=8`, `ITEM1=11`, `NI=20`, `KEY1=ABABABABABABABABABAB`, `CODES=AB`; label `P{r+1:04d}` ljust 8, filler 2
   spaces, items at index `10+c`; missing iff `(11*r + 5*c) % 23 == 0`, char `" "` if r even else `"X"`; else
   `"A" if (r + c) % 2 == 0 else "B"`. CON carries those keys plus `DATA = sample_winsteps.prn` and `NAME1 = 1`.
   Verify: `wc -l` 301 / `grep -c '&'` 2.
5. **[agy R5] Parse + proof tests.** Create `tests/test_ingest_parse.py` (~170 lines): golden asserts (D7 lists,
   exact `==`), pandas asserts (`read_csv(f, dtype=str)` default NA, drop col 0, `.isna().sum()` == ours == golden;
   `read_fwf(path, colspecs=[(10+c, 11+c) for c in range(20)], header=None)` then per column
   `~fillna('').astype(str).str.strip().isin(list('AB'))` == ours == golden), semicolon-sniff unit case, `KEY1`-length
   rejection, over-cap rejection, unassigned-token rejection, and a skip-if-absent cross-check of `parse_control`
   against `/root/projects/raschlab` `raschlab.control.parse_control` on the fixture CON. Verify:
   `pytest tests/test_ingest_parse.py -q`.
6. **[agy R6] Known debt: ratelimit-alone fix.** `tests/conftest.py` passes a MODULE to `TestClient` when the file
   runs alone: line 10 `from app.main import app` binds the FastAPI instance, then line 15 `import app.auth` rebinds
   the same global name to the `app` PACKAGE, and line 51 `TestClient(app, ...)` gets the package.
   **Measured 24 Sep 2026:** alone → `2 failed, 1 passed` with `TypeError` raised inside
   `starlette/testclient.py:78`; full suite → `29 passed`. (Why the full suite still passes is not fully explained;
   the fix removes the ambiguity in both modes and R6 must verify both.) Two literal swaps: line 10 → 
   `from app.main import app as fastapi_app`; line 51 → `return TestClient(fastapi_app, base_url="https://testserver")`.
   Leave `app.db` / `app.auth` references as-is (they correctly resolve to the package). Edit `requirements-dev.txt`:
   add `pandas>=2.2`. Verify: `pytest tests/test_ratelimit.py -q` (3 passed alone) then full `pytest -q`.

**--- Batch 1 ends (data layer). Batch 2 below is the second batch. ---**

7. **[agy R7] Router.** Create `app/ingest.py` (~220 lines, `APIRouter`, mirrors `auth.py` gate/session/
   `check_limit("upload:"+ip+":"+uid, 20, 3600)` patterns, imports `_current_user` from `app.auth` directly — zero
   edits to `auth.py`). Routes: `GET /datasets` (list + upload form + empty state), `POST /datasets` (multipart
   fields `data` required, `con` optional; ext dispatch per D4; on parse error re-render with Indonesian error, no
   row written), `GET /datasets/{id}` (owner check else 404; staged = preview + mapping form fields `t{i}` hidden /
   `m{i}` select for wide, `key`/`codes`/`extra_missing` for prn; ready = read-only summary),
   `POST /datasets/{id}/commit` (validate per D5, 422-page on unassigned), `POST /datasets/{id}/discard` (one
   DELETE). Edit `app/main.py`: one line `app.include_router(ingest_router)` after the auth include. Verify: route
   list contains all five `/datasets` paths.
8. **[agy R8] Templates.** Create `app/templates/datasets.html` (~180 lines) and
   `app/templates/dataset_detail.html` (~260 lines): extend `base.html`, page CSS in the `{% block head %}`
   `<style>` pattern from `account.html`, tokens only (no raw hex), Indonesian copy, status chip
   (`staged`/`ready`), empty state, upload error state, inner-scroll preview table, per-item missing table with
   all-missing flags, unassigned-token warning, 44px tap targets, 390px no horizontal overflow, no em dash. Follow
   `DESIGN.md` (`data-dashboard`, dial ENERGY 2 / RHYTHM 3 / MOTION 2), do not restyle tokens or base. Verify: Jinja
   compiles both templates.
9. **[agy R9] Route tests.** Create `tests/test_ingest_routes.py` (~150 lines): helper inserts a verified `User` +
   `SessionRow` (`new_token`/`hash_token`/`now_epoch`) and sets cookie `raschlab_sid` (no email flow). Asserts:
   gate-closed redirect; anon redirect to `/login`; upload fixture → 303 → detail shows `300`/`40` and golden missing
   sum `413`; gzip round-trip (`decompress(row.raw_gzip) == original bytes`); commit blocked with unassigned token,
   `status` stays `staged`; commit with full mapping → `ready`, `committed_at` set; winsteps pair upload → 303 →
   shows `60`/`20`; discard → row gone; second user gets 404; oversize upload → error page, zero rows. Verify:
   `pytest tests/test_ingest_routes.py -q`.
10. **[agy R10] Docs + link.** Append an `## F2 routes` section to `INTERFACE.md` (the five routes, form field
    names, size caps, `datasets` columns — frozen henceforth). Edit `app/templates/account.html`: replace the literal
    paragraph `<p class="account-empty-text">Belum ada data yang diunggah. Fitur upload menyusul.</p>` with
    `<p class="account-empty-text">Kelola berkas data pengukuran di halaman <a href="/datasets">Berkas Pengukuran</a>.</p>`.
    Verify: `grep -c '/datasets'` ≥ 1 on both files.
11. **[Arc] Full gate + manual curl check.**
    ```bash
    cd /root/projects/raschlab-web && .venv/bin/python -m pytest -q
    .venv/bin/python -m pytest tests/test_ratelimit.py -q
    rm -f /tmp/f2.db
    env DATABASE_URL=sqlite:////tmp/f2.db .venv/bin/python -c "from app.db import get_engine; from app.models import Base; Base.metadata.create_all(get_engine()); print('schema ok')"
    env DATABASE_URL=sqlite:////tmp/f2.db .venv/bin/python -c "from app.db import SessionLocal; from app.models import User; from app.security import hash_password, now_epoch; s=SessionLocal(); s.add(User(email='f2@local.test', email_normalized='f2@local.test', password_hash=hash_password('katasandi-f2-minimal'), created_at=now_epoch(), verified_at=now_epoch())); s.commit(); print('user ok')"
    env DATABASE_URL=sqlite:////tmp/f2.db GATE_OPEN=true APP_ENV=dev .venv/bin/uvicorn app.main:app --port 8891 &
    curl -s -c /tmp/f2jar -X POST localhost:8891/login -d 'email=f2@local.test&password=katasandi-f2-minimal' -o /dev/null -w '%{http_code}\n'   # expect 303
    curl -s -b /tmp/f2jar -F data=@tests/fixtures/sample_300x40.csv localhost:8891/datasets -o /dev/null -w '%{http_code}\n'   # expect 303
    curl -s -b /tmp/f2jar localhost:8891/datasets | grep -c sample_300x40   # expect >=1
    curl -s -b /tmp/f2jar -F data=@tests/fixtures/sample_winsteps.prn -F con=@tests/fixtures/sample_winsteps.CON localhost:8891/datasets -o /dev/null -w '%{http_code}\n'   # expect 303
    ```
    Then Arc renders both pages (screenshot + vision), runs the Hallmark audit gate and the independent `hermes chat`
    review pass before reporting done; kills the uvicorn by PID.
12. **[Arc, not agy] Migration + deploy.** `gcloud secrets versions access latest --secret=raschlab-database-url`
    into `DATABASE_URL`, then `.venv/bin/python -m alembic upgrade head` against Neon; redeploy Cloud Run; verify
    `/health/db` from the internet. Deploying is Arc's Phase-3 step, never part of a writer run.

## EDIT LIST

Batch 1 (data layer; one agy run per row, prompt via `--stdin`,
`--add-dir /root/projects/raschlab-web --mode accept-edits --dangerously-skip-permissions`):

- **R1** — `app/models.py` (edit, +~30 lines: `Dataset`) + `alembic/versions/0003_ingest.py` (new, ~80 lines).
- **R2** — `app/storage.py` (new, ~50 lines) + `requirements.txt` (edit, +1 line `openpyxl>=3.1`).
- **R3** — `app/parsers.py` (new, ~280 lines) — alone, it is the intricate file.
- **R4** — `tests/fixtures/make_samples.py` (new, ~70 lines) + generated `sample_300x40.csv` (~48 KB),
  `sample_winsteps.CON` (~0.3 KB), `sample_winsteps.prn` (~4 KB).
- **R5** — `tests/test_ingest_parse.py` (new, ~170 lines).
- **R6** — `tests/conftest.py` (edit, exactly 2 literal swaps) + `requirements-dev.txt` (edit, +1 line `pandas>=2.2`).

Batch 2 (routes/UI/docs):

- **R7** — `app/ingest.py` (new, ~220 lines) + `app/main.py` (edit, +1 line).
- **R8** — `app/templates/datasets.html` (new) + `app/templates/dataset_detail.html` (new).
- **R9** — `tests/test_ingest_routes.py` (new, ~150 lines).
- **R10** — `INTERFACE.md` (append F2 section) + `app/templates/account.html` (edit, one literal paragraph swap).

## ASSUMPTIONS

1. "Ingest without error" = upload succeeds and preview renders; commit additionally requires D5 validation. The
   PRD proof (missing-count equality) is a test-level claim, satisfied by R5.
2. pandas is a dev-only, local, free dependency; no paid service is added anywhere (constraint 3 holds).
3. `.CON` parsing in F2 is a minimal platform reader of the six needed keys, cross-checked against the engine by a
   skip-if-absent test; this is format reading, not scoring. Engine packaging is deferred to F3 (D3).
4. Path cut per D4: no `.CON`+delimited, no `.xls`, first xlsx sheet only, utf-8-sig or explicit error.
5. Wide-file shape rule: header row = item labels; col 0 = person label only for the named header set, else row
   numbers `P0001...`. Deterministic and testable, no heuristic guessing.
6. Login already requires a verified email (F1), so ingestion is behind verification by inheritance.
7. `alembic upgrade head` never runs in a writer run; tests use `Base.metadata.create_all` (existing conftest
   pattern). Prod migration is Arc's step with the Neon DSN.
8. Thin part of the brief: exact Indonesian UI copy and the preview table's visual composition are decided here
   (D6, states per `DESIGN.md`) and go through the Hallmark/review gate before Dada sees them.

## RISKS

1. **Engine `score()` hardcodes `ABCDE` while path B reads `CODES` from `.CON`.** A dataset with non-A-E codes
   ingests correctly in F2 but will score as all-missing in F3. Mitigation: F2 stores `codes` in `mapping_json` and
   the preview warns when codes fall outside `A-E`; F3 must implement CODES/MISSCORE.
2. **Neon 0.5 GB ceiling, no cleanup in F2.** Abandoned `staged` rows accumulate until F4 delete/lifecycle exists.
   Mitigation: 16 MiB cap bounds worst case; discard route exists; F4 owns a staged-row TTL.
3. **512 MiB RAM vs expansion (xlsx zip-bomb, wide CSV).** Mitigation: `MAX_UPLOAD_BYTES` + `MAX_CELLS` + openpyxl
   `read_only` with early abort, all enforced before any list is fully built; a test covers the over-cap path.
4. **Conftest fix touches the shared fixture used by all 29 F1 tests.** Mitigation: R6 verifies both modes before
   anything else builds on it.
5. **pandas `read_fwf` whitespace handling may differ from expectation.** Mitigation: golden constants gate
   independently; if pandas behaves oddly the fix is confined to the test's normalization line.
6. **SQLite vs Postgres SQL drift.** Mitigation: raw-SQL migration follows `0002_auth.py` precedent; model uses
   `LargeBinary`/`TEXT` which map cleanly on both; offline SQL emission is grep-verified.

## ROLLBACK

`git revert` the F2 commit range in `/root/projects/raschlab-web`, then run
`.venv/bin/python -m alembic downgrade 0002` against the target DB (the `0003` downgrade drops `datasets` and
restores `schema_version='2'`; nothing in 0001/0002 is modified by F2, so F1 comes back as it was).

## Curation notes (Arc, 24 Sep 2026)

- Dada closed option 3 on the gate: `GATE_OPEN=true` permanently (revision `00006-p4r`). F2 must not undo it; the
  gate-closed branches in R7/R9 are tested by monkeypatching `settings.gate_open`, not by changing the deployment.
- **Domain is PARKED by Dada** ("nanti aja domain kalau platformnya udah ready end to end") — not a blocker for F2.
- Engine repo visibility (D3) stays open until F3; nothing in Batch 1 or 2 depends on it.
- Verified by Arc before locking: conftest failure mode (alone `2 failed, 1 passed` vs full `29 passed`), migration
  head is `0002`, `app_meta.schema_version = '2'`, gate route behaviour in both flag states.
