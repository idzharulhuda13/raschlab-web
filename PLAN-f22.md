# PLAN F22 — the optional-input picker becomes ONE control with a search popup

Repo `/root/projects/raschlab-web`. Supersedes the F21 picker UI (the POST contract stays; only the way the
selection is made changes). Anti-slop mode: DURING — apply the rules while writing, do not decorate.

## Why (measured, 6 Oct 2026)

- The settings page renders **every** item row server-side (one checkbox + one number input per item) and
  `settings-picker.js` builds **every** participant row on load (the render-budget fixture is 12,000 persons).
  DOM grows with the dataset, so the page gets slow and the first paint pays for rows nobody looks at.
- Each optional input exists twice on the page (an upload field and a picker list). Two competing controls for
  one decision, which is why the page reads badly.
- Target: the settings page shows **three one-line rows**. Every lookup happens in one popup that never holds more
  than 5 result rows in the DOM, whatever the dataset size.

## Contract

### 1. New route: `GET /datasets/{id}/picker`

```
GET /datasets/{id}/picker?kind=persons|items&q=&offset=0
200 {"kind":"persons","total":300,"offset":0,"limit":5,"has_more":true,
     "items":[{"pos":1,"label":"P0001"},{"pos":2,"label":"P0002"}]}
```

- `limit` is **server-side fixed at 5** (do not accept it from the client; if you add a cap constant, clamp to 20).
- Auth and visibility exactly like `GET /datasets/{id}/analysis-settings`: gate closed, anonymous, or not-owner →
  the same 303/404 that route produces. Ownership check against `dataset.user_id`.
- Rate limit: same helper and call shape as the other routes in this file (`check_limit(client_ip(request), ...)`).
- `kind` anything else → 400 with Indonesian copy in the voice of the neighbouring messages.
- `q`: case-insensitive substring against the label; digits also match the position (exact `str(pos)` match ranks
  first). Empty `q` → the first `limit` rows in position order. `offset` past the end → empty `items`, `has_more`
  false.
- Source of truth: `effective_person_labels` / `effective_item_labels` in `app/analysis.py` (the stored matrix).
  No re-parse, no matrix write, no new table, no migration.
- The response must never carry more than `limit` items, and never PII beyond the label the page already shows.

### 2. DOM: three rows, one dialog

Each optional input becomes one row. Nothing else lives on the page for it:

```html
<div class="pick-field" data-kind="persons">
  <span class="field-label" id="pick-persons-label">Daftar hapus peserta</span>
  <span class="pick-summary" data-summary="persons">Belum ada</span>
  <button type="button" class="btn btn--quiet pick-open" data-kind="persons"
          aria-haspopup="dialog" aria-labelledby="pick-persons-label">Pilih peserta</button>
</div>
```

- The three rows are `persons`, `items` (daftar hapus butir), and `anchors` (jangkar butir).
- The **file input for each list moves inside the dialog** it belongs to. The dialog lives inside the single
  `<form>` in the page, so its controls are still successful controls when the form is submitted. Do NOT set
  `disabled` on a file input to hide it (a disabled control is not submitted).
- One reusable `<dialog id="picker-dialog">` serves all three kinds. Ids in play: `#picker-dialog`,
  `#picker-title`, `#picker-search`, `#picker-results`, `#picker-more`, `#picker-status`, `#picker-chosen`,
  `#picker-file`. `#pd-picker`, `#pd-picker-data` and `#pd-filter` go away.
- Hidden carrier inputs stay inside the form and keep the POST contract **byte for byte**: `pd_pick`, `id_pick`,
  `anchor_pos` + `anchor_value`. The form still posts multipart, still to `/datasets/{id}/analyze`, and the server
  still validates before the rate limit. Do not touch `app/analysis.py`'s picker helpers.
- On a 422 re-render the server renders the carriers from `submitted`; the JS reads them on load and re-seeds the
  chips and the summary, so the F21 restore behaviour survives the new UI.

### 3. Behaviour

- **Open**: click a row's button → `showModal()`, focus `#picker-search`, load the first 5. Closing returns focus to
  the button that opened it.
- **Search**: debounce 150 ms, `AbortController` so a stale response cannot overwrite a newer one. Empty box shows
  the first 5.
- **Never more than 5 rows** in `#picker-results`. `#picker-more` (“Muat 5 lagi”) appends the next 5 (offset += 5)
  and hides when `has_more` is false. `#picker-status` says where the user is ("5 dari 300").
- **Select**: each result row is a checkbox row that toggles the position into the selection.
- **Chosen**: `#picker-chosen` lists one chip per selected position, each with a remove control, and the row summary
  updates ("3 dipilih" / "Belum ada").
- **Anchors**: a result row can be marked "jadikan jangkar"; marked rows join the chosen list **with a number input
  for the value**. Only marked rows get a value carrier — this is the whole point of the third row.
- **Close**: Escape (native), the close button, or a backdrop click. Closing never submits.
- Empty result text names the cause and the next action ("Tidak ada yang cocok dengan 'x'. Coba kata lain atau
  kosongkan kotak cari."), never a bare “No data”.

## Traps — read before writing (each one has bitten this repo)

1. **44px controls**: reuse the existing wrapper class `.field--toggle` for any checkbox row. A checkbox in a
   generic field class measured **37x13px** and failed the rendered-page gate in all four passes.
2. **Tokens only** in CSS; a raw `96px` literal fails `tests/test_ui_contract.py`. No `style=` attribute anywhere,
   no em dash character, no `transition`/`animation` on the dialog, no keyframes.
3. **httpx in tests**: repeated form fields must be posted as `data={"pd_pick": ["3", "7"]}` (dict of lists). A list
   of tuples (`data=[("pd_pick","3"), ...]`) delivers **nothing** in this version and makes a working route look
   broken.
4. **Class-count pins** in `tests/test_ui_contract.py` (used 220 / defined 232). Every class you add must be counted
   and reflected there; a class you delete must be removed from the pin. Measure, do not guess.
5. **Done pages**: `GET /analyses/{id}` 303s to `/analyses/{id}/explore` once the run finishes; the numbers live in
   the `#explorer-data` JSON payload, not in text nodes.
6. Do not reformat, rename, or "tidy" anything outside the file you are told to touch. One writer at a time.

## Files

- `app/analyze.py` — the new route (R1).
- `app/templates/analysis_settings.html` — three rows + dialog shell + carriers (R2).
- `app/static/settings-picker.js` — rewrite (R3, R4).
- `app/static/app.css` — dialog, row, chip, result-row styles from tokens (R5).
- `tests/test_picker_search.py` (new, R1), `tests/test_settings_picker.py` (R2: the assertions coupled to the old
  markup), `tests/test_settings_picker_js.py` (R3, R4: browser), `tests/test_ui_contract.py` (R5: pins).
- `DESIGN.md` (R5: the dialog under “Components and their states”, and the focus contract under “Accessibility
  contract”), `INTERFACE.md` (R5: an F22 section replacing the F21 DOM description).

## Slices — one writer at a time, verify then commit per slice

| Run | Scope | VERIFY |
|---|---|---|
| R1 | the picker route + `tests/test_picker_search.py` | `pytest -q tests/test_picker_search.py` |
| R2 | template rows + dialog shell + carriers + coupled test updates | `pytest -q tests/test_settings_picker.py tests/test_analysis_settings.py tests/test_anchor_route.py tests/test_f9_ux.py` |
| R3 | JS: open/close, search, ≤5 rows, load more, chips, carrier sync, restore | `pytest -q tests/test_settings_picker_js.py tests/test_settings_picker.py` |
| R4 | anchors flow (mark + value + carriers) end to end | `pytest -q tests/test_settings_picker_js.py tests/test_settings_picker.py tests/test_anchor_route.py` |
| R5 | CSS + a11y + class pins + DESIGN.md + INTERFACE.md | `pytest -q tests/test_ui_contract.py tests/test_f9_ux.py` and the full suite |

Arc then verifies: full suite, the rendered-page probe on the new page (390/1440 × light/dark), a browser
click-through (open → search → select → submit), and a live check against the deployed revision.

## Out of scope

- Any change to the POST contract, the engine, the schema, or the upload precedence rules.
- Pagination of the analysis result tables (a separate concern).
- A corrupt stored matrix still yields blank labels; that is a tracked follow-up, not part of this run.
