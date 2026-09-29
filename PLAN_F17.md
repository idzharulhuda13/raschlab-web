# F17 — keep both runs, mark one Dipakai and the rest Arsip (frozen contract, 29 Sep 2026)

## Why

The owner decided: both versions stay stored, one is marked as the version in use (`Dipakai`) and the rest
are `Arsip`. Today nothing records that choice, so a reader comparing two similar runs of the same dataset
cannot tell which one the numbers should be quoted from. The marking has to be explicit, not inferred from
which run happens to be newest or which one carries a delete list.

## 1. Scope of THIS run (A of two)

Files this run may write, and nothing else: `app/models.py`,
`alembic/versions/0005_analysis_primary.py` (new), `app/analysis.py`, `app/analyze.py`,
`tests/test_mark_primary.py` (new). Run B does the display (chips, the button, the compare labels, the list
page) once this core is green and verified.

## 2. Model and migration

- `Analysis` gains `primary_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)`. NULL means
  archive. It records WHEN the run was marked, which is also how the pages order ties.
- New migration `alembic/versions/0005_analysis_primary.py`: `revision = "0005"`, `down_revision = "0004"`,
  written in the same style as `0004_analysis.py` (raw `op.execute`, Postgres dialect):
  `ALTER TABLE analyses ADD COLUMN primary_at BIGINT;`
- At most ONE analysis per dataset is marked. The invariant is kept by the write path in one transaction,
  not by a constraint, because the store must stay portable: the tests build the schema from the models on
  SQLite while production is Postgres.

## 3. Domain helpers (app/analysis.py)

- `mark_analysis(db, analysis, marked: bool) -> None`
  - `marked=True`: clears `primary_at` on every other analysis of the same `dataset_id` (including rows that
    are not done), then sets `analysis.primary_at` to `now_epoch()` if it is not already set, and commits
    once. Calling it on an already marked analysis changes nothing and does not raise.
  - `marked=False`: sets `analysis.primary_at = None` and commits once. Siblings are never touched.
- `marked_analysis_id(db, dataset_id: int) -> int | None`
  - the id of the marked analysis for that dataset, or None. Defensive: if more than one row is marked,
    return the newest by `primary_at` then `id`, and never raise.

## 4. Route (app/analyze.py)

- `POST /analyses/{id}/mark`, plain `def`, form field `primary` (values `"1"` and `"0"`; any other value is
  treated as `"0"`, because the form always sends one of the two).
- Gate closed -> 303 to `/`. No session -> 303 to `/login`. Any user who is not the analysis owner, or an
  analysis that does not exist -> 404 `Analisis tidak ditemukan.` (same message the module already uses).
- On success: 303 to `/analyses/{id}`. No message query parameter is needed.

## 5. Run B scope (frozen here so both runs agree)

- Analysis page header: when the run is marked, a `chip chip--accent` reading `Dipakai`; when it is not
  marked but another run of the same dataset is, a `chip chip--warn` reading `Arsip`; when no run of that
  dataset is marked, no chip at all. Plus one form button (a real POST to the route above) whose label is
  `Tandai sebagai versi dipakai` or `Batalkan tanda dipakai`.
- Analyses list: the same chip on each row, driven by one query of marked ids.
- Compare view: each option in both selects gains ` · Dipakai` or ` · Arsip` as a suffix when its dataset
  has a marked run. The `empty_reason` and the pairing logic do not change.

## 6. VERIFY (run A)

    cd /root/projects/raschlab-web && .venv/bin/python -m pytest tests -q      # BEFORE: note baseline (253)
    cd /root/projects/raschlab-web && .venv/bin/python -m pytest tests -q      # AFTER: EXPECTED baseline + 6
    cd /root/projects/raschlab-web && .venv/bin/python -m pytest tests/test_mark_primary.py -q
    cd /root/projects/raschlab-web && .venv/bin/python -m alembic upgrade head --sql | tail -5

The last command runs the migration offline (no database needed) and must print the `0005` ALTER TABLE
statement; a migration that only works with a live database has not been checked.

Six tests in `tests/test_mark_primary.py`:

1. marking sets `primary_at` on that analysis and clears it on a previously marked sibling of the SAME
   dataset;
2. marking never touches an analysis of another dataset;
3. unmarking clears that analysis and leaves its siblings' `primary_at` untouched;
4. `mark_analysis` on an already marked analysis is idempotent: the value is unchanged and no error is
   raised;
5. `marked_analysis_id` returns the marked id, None when the dataset has none, and the newest by
   `primary_at` when a legacy row somehow has two;
6. the route refuses what it must: an anonymous POST redirects to `/login`, and a POST by a different user
   returns 404, both without changing any `primary_at`.


## 7. Run B scope, frozen in detail (30 Sep 2026)

Files this run may write, and nothing else: `app/analyze.py`, `app/explore.py`,
`app/templates/analysis.html`, `app/templates/analyses.html`, `app/templates/explore/fragment.html`,
`tests/test_mark_display.py` (new). Run A is committed (`405a8dc`): the column, the migration, the helpers
`mark_analysis` / `marked_analysis_id` and `POST /analyses/{id}/mark` all exist and are tested. Do not
re-implement any of them.

### 7.1 Shared helpers (app/analyze.py)

- `_marked_ids(db, user_id: int) -> dict[int, int]` mapping `dataset_id -> marked analysis id` for that
  user's datasets. One query, no N+1, never raises.
- Analysis page context gains `mark_state`: the string `"dipakai"` when this analysis is the marked one,
  `"arsip"` when another analysis of the SAME dataset is marked, and `"belum"` when no analysis of that
  dataset is marked. Also expose `can_mark` = True for the owner.

### 7.2 Analysis page (app/templates/analysis.html)

In the header band, next to the existing status chip:

- `mark_state == "dipakai"`: `<span class="chip chip--accent">Dipakai</span>`
- `mark_state == "arsip"`: `<span class="chip chip--warn">Arsip</span>`
- `"belum"`: nothing at all, not even an empty chip row.
- A form button in the header's action area, `method="post"` to `/analyses/{{ analysis.id }}/mark`, class
  `btn btn--secondary`, containing a hidden input `primary` whose value is `1` when not marked and `0` when
  marked. Label: `Tandai sebagai versi dipakai` / `Batalkan tanda dipakai`. No JavaScript.

### 7.3 Analyses list (app/templates/analyses.html)

Each row shows the same chip when the row's analysis is marked (`Dipakai`), or `Arsip` when another analysis
of that same dataset is marked, and nothing when none is. Use the map from 7.1: one query for the page.

### 7.4 Compare view (app/explore.py + app/templates/explore/fragment.html)

- Each entry of `compare_ctx["options"]` gains `mark_label`: `"Dipakai"`, `"Arsip"`, or `""`.
- Both selects render the suffix ` · Dipakai` / ` · Arsip` after the existing label text when
  `mark_label` is non-empty. Nothing else about those selects changes, and the pairing logic, the S.E.
  filter and the export stay exactly as they are.

### 7.5 VERIFY (run B)

    cd /root/projects/raschlab-web && .venv/bin/python -m pytest tests -q     # BEFORE: note baseline (261)
    cd /root/projects/raschlab-web && .venv/bin/python -m pytest tests -q     # AFTER: EXPECTED baseline + 6
    cd /root/projects/raschlab-web && .venv/bin/python -m pytest tests/test_mark_display.py -q

Six tests in `tests/test_mark_display.py`:

1. the analysis page of a marked run renders the `Dipakai` chip and a button whose hidden `primary` is `0`;
2. the analysis page of an unmarked run whose sibling is marked renders `Arsip` and a hidden `primary` of `1`;
3. the analysis page of a run whose dataset has no mark renders neither chip word;
4. the analyses list page marks exactly the marked row and gives the sibling's row the `Arsip` chip;
5. the compare view's options carry ` · Dipakai` on the marked run and ` · Arsip` on its sibling;
6. the three pages stay free of an em dash.
