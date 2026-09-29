# F15 — the S.E. filter on the Bandingkan view (frozen contract, 29 Sep 2026)

## Why

The compare view already ships a toggle whose own label admits it is cosmetic: "Tampilkan hanya
perubahan ≥ 0,30 (ambang tampilan, bukan uji statistik)". A reader who wants to know whether the two
versions actually differ cannot answer it from a fixed 0,30 cut, because an item's noise floor is its own
standard error: the owner's Verbal run has S.E. between 0,05 and 0,31 logit depending on the item. The
contract here replaces that with the real comparison: keep the items whose measure moved MORE than their
own S.E., decided in the handler so the state survives a reload, a share, and the export.

## Scope

IN: `app/explore.py`, `app/templates/explore/fragment.html`, `app/export.py`, new test file.
OUT (do not touch): the client-side 0,30 display toggle and its JS (`explorer-charts.js`, `explorer.js`),
the export sheet's column contract ("pairs" keep their 5 fields), the engine, `PLAN_F14.md`,
`app/analyze.py`, any other template, `requirements.txt`.

## Frozen contract

### 1. Query parameter

`over_se` — present (any value, the template posts `1`) means "only items whose |delta| > their S.E.".
Absent means unfiltered. The existing compare form gains the checkbox so the state round-trips in the URL.

### 2. `build_compare_pairs` (app/explore.py)

Signature and the 5-field `pairs` rows are UNCHANGED, because the export sheet is frozen. The function
gains one extra return key:

- `"se"`: `list[float | None]`, aligned index-for-index with `pairs`, carrying the S.E. of the SECOND
  table's row for that item (`None` when the cell is missing or unparseable).
- `"over_se"`: `list[bool]`, aligned the same way: `True` when `se` is not None and
  `abs(m_to - m_from) > se`. A `None` S.E. is never `True` (unknown is not a finding).

Read the S.E. from the existing two-row header: `item_rows[1]` holds the name (the engine writes
`MODEL` on the first row and `S.E.` on the second, same column). Resolve the index once per table and
return `None` for every row when the column is absent.

### 3. `app/explore.py` handler, compare branch

- Read `over_se = request.query_params.get("over_se") is not None`.
- Build `pairs`, `se`, `over_se` from one call to `build_compare_pairs`.
- `kept = [i for i, flag in enumerate(cmp_result["over_se"]) if flag]` when `over_se` is on, else all indices.
- The template context `compare_ctx` gains exactly these keys:
  - `"over_se_only"`: bool
  - `"n_pairs_total"`: int (unfiltered count)
  - `"n_over_se"`: int (count of `True`)
  - `"pairs"`: the FILTERED list (so the table renders the filtered set server-side)
  - `"cmp_data_json"`: the chart payload, whose `"pairs"` array is filtered the same way, plus a new
    top-level `"over_se_only"` boolean. Everything else in that payload keeps its shape
    (`schema`, `from_id`, `to_id`, `from_label`, `to_label`).
- When `compare_ctx` is built for the "nothing selected" branch, all four new keys must exist too
  (`over_se_only = False`, both counts `0`, `pairs = []`), so the template never hits an undefined name.

### 4. Template (app/templates/explore/fragment.html)

Inside the EXISTING `<form class="compare-strip" ...>` block, immediately BEFORE the
`<div class="action-bar">` that holds the `Tampilkan Perbandingan` button, insert:

```html
<div class="field field--toggle">
  <input type="checkbox" id="cmp-over-se" name="over_se" value="1"{% if compare_ctx.over_se_only %} checked{% endif %}>
  <label class="field-label" for="cmp-over-se">Hanya butir yang bergeser lebih dari S.E. butir itu.</label>
</div>
```

Immediately AFTER the closing `</form>` of that compare strip and BEFORE the existing
`<p id="cmp-statement">`, insert one live line:

```html
<p id="cmp-over-se-count" aria-live="polite">{% if compare_ctx.over_se_only %}Menampilkan {{ compare_ctx.n_over_se | id_num }} dari {{ compare_ctx.n_pairs_total | id_num }} butir, yang bergeser lebih dari S.E.-nya.{% else %}Menampilkan {{ compare_ctx.n_pairs_total | id_num }} butir.{% endif %}</p>
```

The existing `#cmp-empty` block gains the filtered empty state: when `compare_ctx.over_se_only` and
`compare_ctx.pairs` is empty, its text is exactly
`Tidak ada butir yang bergeser lebih dari S.E.-nya. Matikan filter untuk melihat semua butir.`

Do NOT remove the 0,30 display toggle; it answers a different question and its JS stays as it is.

### 5. Export (app/export.py)

`_compare_rows` filters the same way when `request.query_params.get("over_se") is not None`: build the
pairs once, then keep only the rows whose aligned `over_se` flag is `True`. The sheet keeps exactly its
current columns, header row and order: `pairs` rows are still the 5 fields, unfiltered shape unchanged
when the parameter is absent.

## Rules the writer must hold

- No new CSS class: reuse `field`, `field--toggle`, `field-label`, `action-bar`, `btn`, `btn--primary`,
  `empty`, `empty-text`, `table-scroll`, `data-table`, `mono`, `num-col`.
- No em dash in any added copy. Numbers through `| id_num`; percentages and S.E. values come from the data.
- The S.E. is data, never a constant: a hardcoded 0,30 in the comparison path is the defect this contract
  exists to remove, so the filter must read the column.
- Unknown stays unknown: an item without an S.E. is never reported as moved.

## Files this run writes

1. `app/explore.py` (the return keys + the handler's compare branch)
2. `app/templates/explore/fragment.html` (the form toggle, the live count line, the filtered empty state)
3. `app/export.py` (`_compare_rows`)
4. `tests/test_compare_over_se.py` (new, 5 tests)

## VERIFY

Run the suite twice and report both raw outputs:

```
.venv/bin/python -m pytest tests -q                 # BEFORE your edits: note the baseline count
.venv/bin/python -m pytest tests -q                 # AFTER: EXPECTED baseline + 5 passed
.venv/bin/python -m pytest tests/test_compare_over_se.py -q   # EXPECTED: 5 passed
```

The five tests:

1. with a fixture where two items move 0,10 and one moves 0,40 while every S.E. is 0,15, the unfiltered
   view shows all three rows and the filtered view (`over_se=1`) shows exactly one
2. the live count line reads `Menampilkan 1 dari 3 butir, yang bergeser lebih dari S.E.-nya.` when the
   filter is on and `Menampilkan 3 butir.` when it is off
3. an item whose S.E. cell is empty is never counted as moved
4. the export with `&over_se=1` returns the reduced row set and its header row is byte-identical to the
   unfiltered export's header row (the column contract did not move)
5. no em dash in the compare fragment's rendered output

If a test fails because the source is wrong, STOP and report the mismatch with raw output. Never weaken an
assertion to make it pass, and never edit the frozen export column contract.
