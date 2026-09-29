# F14 — Kebersihan Data on the analysis page (frozen contract, 29 Sep 2026)

## Why

The engine (raschlab `8acd8c9`) now writes a `STATUS` column on the respondent table and on the item
table, plus `COUNTS` rows in the summary. Before that the page silently hid which rows were dropped, so a
reader could not tell a clean run from a run whose delete list hit the wrong people. This feature states,
on the analysis page, what was kept and what was removed, and it refuses to invent numbers for analyses
run before the column existed.

## Scope of F14

IN: the analysis page band and its tests.
OUT (do not touch): the settings screen and any upload of a delete list (`pdfile`/`idfile`), the explorer's
Bandingkan filter, the engine pin in `requirements.txt`, `app/static/*.css`, `DESIGN.md`, `INTERFACE.md`.

## Frozen contract (Arc authored, do not rename)

### 1. Context key `clean_audit` from `app/analyze.py` (already implemented by Arc)

`context["clean_audit"]` is a dict, or `None` when the run predates the `STATUS` column. The template must
render the honest note in that case, never zeros.

| key | meaning |
|---|---|
| `dipakai` | rows whose `STATUS` is `kept` |
| `dihapus` | `deleted` |
| `kurang` | `lacking` |
| `ekstrem_bawah` | `extreme_min` |
| `ekstrem_atas` | `extreme_max` |
| `ekstrem` | `ekstrem_bawah + ekstrem_atas` |
| `total` | all rows in the table (2.381 in the owner's Verbal run) |
| `butir_dihapus` | `COUNTS ITEM DELETED` from the summary, 0 when absent |
| `pct_dipakai`, `pct_dihapus`, `pct_ekstrem` | strings, one decimal, **comma** separator (`84,7`) |
| `x_dipakai`, `w_dipakai`, `x_dihapus`, `w_dihapus`, `x_ekstrem`, `w_ekstrem` | floats, geometry of the band in a `0 0 560 76` viewBox, already proportional to `total` |

### 2. Placement in `app/templates/analysis.html`

Inside the `{% elif status == 'done' %}` branch, **immediately after** the `{% endif %}` that closes the
unanchored alert (the one whose copy starts `Hasil Tanpa Jangkar (Unanchored)`) and **before** the
`{% if n_item > 0 %}` block that renders `Butir Bermasalah`. Exact section id: `kebersihan`.

### 3. Copy (these strings, verbatim; no em dash anywhere)

Heading: `Kebersihan Data`

Band caption, one line: `Komposisi {total} baris yang dibaca mesin.` (numbers through `| id_num`)

Chips, in this order, reusing the existing classes and glyphs:
- `.chip .chip--fit` glyph `OK`, text `{dipakai} dipakai`
- `.chip .chip--misfit` glyph `!`, text `{dihapus} dihapus`
- `.chip .chip--warn` glyph `!`, text `{ekstrem} ekstrem`

Alert: `.alert .alert--warn` with `role="status"` when `dihapus > 0 or ekstrem > 0`, otherwise
`.alert .alert--fit`. Body text, exactly:
`{dihapus} baris dihapus lewat daftar hapus dan {ekstrem} baris dikecualikan sebagai ekstrem ({ekstrem_bawah} bawah, {ekstrem_atas} atas). {butir_dihapus} butir dibuang sebelum penilaian.`

Honest note when `clean_audit is None`, inside `.alert .alert--info` with `role="status"`:
`Analisis ini dijalankan sebelum mesin mencatat kolom status, jadi rincian baris yang dipakai dan dibuang belum ada. Jalankan ulang analisis untuk melihatnya.`

Closing link (only when the explorer is reachable): `<a class="btn btn--secondary" href="/analyses/{{ analysis.id }}/explore?view=bandingkan">Bandingkan dengan versi arsip</a>`

### 4. The measured band (the identity motif, DESIGN.md "pita ukur")

Inline `<svg>` in the template, `viewBox="0 0 560 100"`, `role="img"`, and an `aria-label` naming the three
numbers in words. Built ONLY from context values and tokens:

**AMENDED by Arc after the first render (29 Sep 2026):** the box is `0 0 560 100`, not `560 76`. With height
76 the percentage line under the second segment (`y=80`) fell outside the box and was clipped, and the SVG
text inherited the page's 16px, which overflowed the narrow segments. Every `<text>` therefore carries
`font-size="11"` in user units, the two labels of the rightmost (narrowest) segment anchor to `x=548` with
`text-anchor="end"` so they cannot spill past the band's right edge, and the left end label reads `0` while
the right one reads `{total} baris`.

- one hairline baseline at `y=40` from `x=10` to `x=550`, `stroke="var(--line)"`
- three `rect` segments at `y=24`, height `12`, using the context x/w pairs, filled
  `var(--accent)` (dipakai), `var(--misfit)` (dihapus), `var(--warn)` (ekstrem)
- under each segment, two lines of text centred on the segment: the count + word, then the percentage.
  Use `fill="var(--ink)"` for the count and `fill="var(--muted)"` for the percentage; the narrow segments
  alternate their label rows (`y=52`, `y=68`, `y=52`) so labels never collide.
- `x=10` anchor `0` and `x=550` anchor `end` carrying `{total} baris`, both `fill="var(--muted)"`.
- The band must be drawn from the values: a segment whose width attribute is not derived from the context
  is a defect, and so is a track with no `rect` at all.

### 5. Rules the writer must hold

- **No new CSS class and no new CSS rule.** Reuse `band`, `chip`, `chip--fit`, `chip--warn`,
  `chip--misfit`, `chip-glyph`, `chip-row`, `alert`, `alert--fit`, `alert--info`, `alert--warn`, `mono`,
  `btn`, `btn--secondary`. Colour only through `var(--token)` attributes; never a hex literal.
- Numerals through the existing `id_num` filter; percentages come from the context as strings.
- No em dash (`—`) in any string added by this change.
- Every number on the band is data. No placeholder, no sample count, no rounding invented in the template.
- The band renders only when `status == 'done'`; an analysis still running or failed must not show it.
- Mobile: the band is one full-width SVG inside the band section, no fixed pixel height on the container,
  no horizontal overflow at 390px.

## Files this run writes

1. `app/templates/analysis.html` (insert the section as specified; about 45 lines added)
2. `tests/test_cleanliness_band.py` (new; 5 tests)
3. `tests/test_ui_contract.py` **only if** the writer adds a class, and then only the pin counts

## VERIFY (expected output written down)

```
.venv/bin/python -m pytest tests -q
# expect: 233 passed   (228 existing + 5 new)
```

and the new file's own line:

```
.venv/bin/python -m pytest tests/test_cleanliness_band.py -q
# expect: 5 passed
```

The five tests:

1. a completed analysis whose respondent table carries `STATUS` renders `Kebersihan Data` and the exact
   counts of the fixture rows (chip text `… dipakai`, `… dihapus`, `… ekstrem`), and the band's `rect`
   widths equal the context geometry
2. the same analysis renders no `—`
3. a result whose respondent table lacks the `STATUS` header renders the honest note and no chips
4. an analysis with `status == 'running'` renders neither the band nor the note
5. the band's `aria-label` carries the three counts as words

If a test fails because the source is wrong, STOP and report the mismatch. Never make a test pass by
weakening an assertion, and never edit `app/analyze.py` (Arc owns it) or the engine.
