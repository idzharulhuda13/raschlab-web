# DESIGN.md — RaschLab web

Design contract for every UI artifact in this repo. Arc owns this file; a writer executes it and never
re-picks a direction, never mixes in a second palette, never opens a second direction skill.

- **Direction skill for writers: `data-dashboard`** (subject: a console that has to render dense
  measurement numbers legibly, read on warm paper surfaces).
- **The published artifact is the reference implementation.** The owner's verdict (25 Sep 2026):
  *"kenapa semua tampilannya berubah dari yang di artifact ya? padahal yang di artifact udah bagus
  banget"*, then, offered the scope: **the whole app follows the artifact** — display face, density
  and per-view composition. The artifact lives in `/root/projects/web-artifacts/rasch-explorer/`
  (`DESIGN.rasch-explorer.md`) and both contracts share one palette and one dial on purpose.
- **Process skills, always on: `design-tokens`, `a11y-audit`, `output-enforcement`.**
- **antislop mode: DURING**, closed by the Hallmark audit gate before anything is reported as done.
- Human-facing copy: Indonesian (casual-professional). Code, identifiers, comments: English.

## Design Read

Reading this as: an item-analysis workbench for teachers, assessment teams and psychometricians, in a
**warm instrument language with one measured accent**, dial **ENERGY 3 / RHYTHM 3 / MOTION 2**.

Dada's verdict that produced this rewrite (24 Sep 2026): *"aku tau ini kita masih yang penting ada
fiturnya, tapi ui website nya jelek banget harus akuin. contoh la website website terkenal sekarang
claude, netflix atau siapapun itu"* — then, when offered a light and a dark direction: **"iya A+B"**.

So both themes ship and both are measured: **light "Instrumen"** is the base, **dark "Sinematik"** is
the same instrument at night. A theme toggle is required and must work in both directions.

**The bar is a 2026 product.** The tool this replaces is grey Windows chrome with cramped tables;
anything that reads as desktop-era software or as an unstyled admin template is a defect, not a style
choice. Two failure modes are named as defects here: **retro-desktop** and **template-default**.

## Colour tokens

Authority for colour. `app/static/tokens.css` mirrors these blocks; no raw colour literal anywhere else
in the repo. Every ratio below was **measured** with the WCAG relative-luminance formula, in both themes.

**Light — "Instrumen"**

| Token | Value | Reason (subject) | Measured |
|---|---|---|---|
| `--paper` | `#F7F4EF` | Warm page ground: long tables on warm paper instead of clinical white | — |
| `--surface` | `#FFFFFF` | The data plane is the brightest thing on screen | — |
| `--surface-2` | `#EFEAE2` | Inset panels (table head, notes, code) without a second shadow | — |
| `--ink` | `#1E2422` | Near-black with a green undertone, matches the accent family | 14,39:1 on paper · 15,78:1 on surface |
| `--muted` | `#59635F` | Secondary text, labels, metadata | 5,67:1 on paper · 6,22:1 on surface · 5,20:1 on surface-2 |
| `--line` | `#DED6CA` | Hairlines and separators. Decorative only, never the sole signal | 1,44:1 (by design low) |
| `--control` | `#8A8073` | Border of interactive controls (input, button outline), must clear 3:1 | 3,88:1 on surface · 3,53:1 on paper |
| `--accent` | `#0E5A47` | The instrument accent: scale band, links, primary action, focus ring | 8,16:1 on surface · 7,44:1 on paper; white on it 8,16:1 |
| `--accent-soft` | `#E4EFE9` | Tinted panel behind the scale band and active step | ink on it 13,39:1 |
| `--fit` | `#12703F` | Correct / within range. Always paired with a glyph and a word | 6,15:1 on surface |
| `--warn` | `#7A5200` | Needs attention (unconfirmed, borderline) | 6,92:1 on surface |
| `--misfit` | `#A32222` | Wrong / missing / destructive | 7,48:1 on surface |

**Dark — "Sinematik"**

| Token | Value | Reason | Measured |
|---|---|---|---|
| `--paper` | `#0B0F0E` | Night ground, green undertone, not pure black (avoids halation on text) | — |
| `--surface` | `#151A18` | Cards sit one step above the ground | — |
| `--surface-2` | `#1D2422` | Inset panels | — |
| `--ink` | `#EDF3EF` | 15,65:1 on surface · 14,06:1 on surface-2 |
| `--muted` | `#A7B4AE` | 8,20:1 on surface · 7,37:1 on surface-2 |
| `--line` | `#2C3532` | Decorative hairline | — |
| `--control` | `#5F6C66` | Control border, 3:21:1 on surface · 3,51:1 on paper | 3,21:1 |
| `--accent` | `#63D8A8` | The same instrument accent, lit for night | 9,99:1 on surface; ground ink on it 10,95:1 |
| `--accent-soft` | `#12312A` | Tinted panel | ink on it 12,46:1 |
| `--fit` | `#6FD8A0` | 10,06:1 on surface |
| `--warn` | `#E8BE6A` | 10,06:1 on surface |
| `--misfit` | `#FF8F8F` | 8,03:1 on surface |

**Link rule (measured defect to never reintroduce).** Every anchor takes `--accent`, including visited and
hover, with `text-underline-offset: 2px` and a 1px underline: the browser default link colour
(`rgb(0, 0, 238)` blue with a thick underline) was measured on the file list of the first build and it read
as an unstyled page. Component links (`.appnav-link`, `.acct-link`, `.back-link`, `.btn`) keep their own
colour rules, which sit above the element selector.

Notes that bind the writer:

- The accent is **green in both themes** on purpose: status colour (fit / warn / misfit) already spends
  red, amber and green, so a second loud hue (e.g. orange) would make status unreadable. One accent,
  three semantic colours, nothing else.
- Semantic colour is never the only signal: every fit/warn/misfit state also carries a word and a glyph.
- Decorative hairlines (`--line`) are allowed to be low contrast; anything a user must perceive as a
  boundary (input border, button outline, focus ring, chart baseline) uses `--control` or `--accent`.

## Typography

**Archivo Black** for the wordmark, page and section titles and the tab strip; **Archivo** for UI text
and controls; **IBM Plex Mono** for numerals, item IDs, dataset IDs and code.

Reason: this is the pair the owner picked out of the published artifact ("yang di artifact udah bagus
banget", 25 Sep 2026). Archivo Black is the instrument's own voice — a black-weight grotesque that
carries a title without decoration, so hierarchy comes from weight rather than from colour or rules.
Archivo keeps the body neutral so dense numbers stay legible next to it, and Plex Mono keeps the
instrument role: unambiguous `0/O` and `1/l` for item codes, and `tabular-nums` so columns of measures
line up. The earlier Plus Jakarta Sans rationale is superseded by that direction, not by taste drift.

- Load from Google Fonts with `preconnect` + `display=swap`, and declare a fallback stack that still
  looks deliberate (`Georgia, serif` for display, `system-ui` for body) when the CDN is unreachable.
  **Self-hosted subset in `app/static/fonts/` is a later task (F5), named here so it is not forgotten.**
- Scale (desktop / mobile): display `44/30`, h1 `40/30`, h2 `28/24`, h3 `22/20`, lead `18/17`,
  body `16/16`, secondary `14/14`, micro label `12/12` (micro labels only, never body copy).
- Weight carries hierarchy: 400 body, 500 labels and controls, 600 headings and numbers, 700 reserved
  for the single page title. No all-bold rows, no uppercase-tracked micro labels.
- Line height: 1.2 headings, 1.5 body, 1.45 table body. Measure (line length) under 72 characters for
  prose; the hero line under 46.
- Every numeral in a table, metric tile or scale band uses `font-variant-numeric: tabular-nums`. One exception
  (5 Oct 2026): a standalone figure value in a dashboard figure row uses proportional figures (see the dashboard
  section), because alignment only matters in a column.
- **Density (owner's reference: the artifact, 25 Sep 2026).** Table body `14px`, header `14px` on
  `--surface-2`, cell padding `--space-2` block / `--space-3` inline, which measures a **37px** row
  instead of 47,7px. On 26 Sep 2026, the header was raised from 12px for legibility while the body cell
  and its 37 px row measure are unchanged. Why: the artifact's own 147-row table reads at 37,3px per row
  and stays legible at 1,45 line height, while a 47,7px row on a 59-row table spends about 630px of extra
  height, close to a full screen. Density here is rhythm, not small type: table body stays at 14px or
  above, never the 10-11px rows this file rejects elsewhere.
- Explorer blocks (caption, table, pager, figure grid) separate at `--space-4`; the tab strip carries
  `--space-4` above and below; the summary figure grid uses `--space-6`.
- **Interactive controls are 44px at every width** (added 26 Sep 2026): a sort header (`.th-sort`), a
  checkbox row (`.field--toggle`, used by the Wright misfit highlight and the Bandingkan delta filter) and any
  other control the mouse and the thumb both aim at take `min-height: 44px` on desktop as well. A 32px sort
  header inside a 37px row is the shape this rule exists to prevent.
- **A data row is not a control.** The Butir and Partisipan tables list numbers to read, sort and page
  through: the rows carry no `tabindex`, no role and no hover treatment, so a keyboard user meets the sort
  buttons and the pager instead of 147 dead tab stops (measured 26 Sep 2026: activating a row changed nothing).
  A row earns a tab stop only when a real action hangs off it, and that action decides the pattern.
- **The app bar keeps its targets on a phone** (added 26 Sep 2026): every control in it holds 44x44 at every
  width, including the icon-shaped ones (account summary, theme toggle) and the skip link. Measured at 360px,
  the bar could not carry wordmark + three nav links + account + theme at those sizes without the nav colliding
  with the avatar, so at `<=480px` the **account link leaves the nav**: it pointed at the same destination as
  the account menu sitting next to it, and the menu keeps that route reachable. Shedding the duplicate is the
  fix; shrinking a target below 44px is not. The two remaining links keep their natural width inside a strip that
  scrolls sideways (`overflow-x: auto` + `flex: none`), so a 320px screen scrolls the strip instead of squeezing
  a label into a 44px box: a link is either fully readable or off the strip, never clipped inside itself.

## Identity motif: the measured band (pita ukur)

The subject is a calibrated ruler: every dataset in the product is a matrix that will end up as items and
persons on one logit scale. The motif is a **thin measured band — a labelled tick rule with real
numbers** — used in exactly two places, each carrying information:

1. **Dataset card, capacity band.** A band showing cells used against the 6.000.000-cell cap, with both
   endpoints labelled and the dataset's own value printed **plus the share of the cap as text** (for example
   `12.000 sel terpakai (0,2% dari 6.000.000 sel)`). Tells the user how much room is left. The fill is the
   **true proportion, never floored or shifted**: a value of 0,15% draws 0,15% of the track. So that a small
   value is still visible, the same position is marked by a **1px non-scaling stroke at the true offset**
   (an SVG line with `vector-effect="non-scaling-stroke"`), and the printed number remains the authority. A
   floor that displaces a small value to make it visible is a defect (measured once: a floor of 0,8% drew a
   0,1% share at 0,8% of the axis).
2. **Detail page, above the missing table.** A horizontal axis from `0%` to the dataset's own maximum
   missing rate, with the total marked and labelled. Turns 147 identical rows into a readable shape. The
   fill and the total marker are **both** positioned by values derived from the data: a marker at
   `total / max × 100` of the axis, drawn as a non-scaling 1px stroke so it is visible without being moved,
   plus the total printed as text. An axis whose fill or marker is not derived from the data is a defect: it
   states endpoints while drawing nothing that reflects them (measured once on the detail page: an empty fill
   span and a marker with no position at all).

The brand mark is the wordmark plus the caption `skala logit`, stating what the product measures. It carries
**no tick rule**: a decorative micro-scale beside the wordmark was built once, measured as a divider wearing
the motif's clothes, and removed.

Rules: the band is drawn from tokens, is inline SVG or CSS (no chart library), carries at least two real
labels, and has one caption line saying what it measures. **A tick rule without numbers is a divider,
not a motif, and is a defect** (this exact mistake was caught and removed once already). A proportional
fill is set with an SVG `rect` width attribute, never with an inline `style` attribute. **A band that
renders as an empty track carries no information and is a defect** (measured once on the file list: a
150×12px track with no fill element at all).

## Layout — RHYTHM 3, bands that differ by shape

A wall of equal cards, or every section as centred title + identical card grid, is banned. Composition
changes between bands on purpose.

**Shell (all pages).** A top app bar: wordmark + motif caption on the left, current section as a real
link set, account menu (avatar + name, opens to `/account`, `/logout`) on the right, theme toggle at the
end. Height 72px desktop / 64px mobile, sticky with the `--paper` fill and a `--line` hairline. Account
links never sit inside a content card. Footer: product name, version, one line on what it measures.

The bar must FIT the narrowest phone: measured at 360px and 390px with zero horizontal overflow. Because
the bar is the first thing to break, its mobile behaviour is part of the contract, not a fallback: at
`≤719px` the gap and inline padding tighten to `--space-3` / `--space-4`, the theme toggle shows its glyph
with the text label hidden (the accessible name still names the target theme), and at `≤480px` the caption
`skala logit` hides with the wordmark (it stays in the markup). Every flex child of the bar carries `min-width: 0`. **Measured defect to
never reintroduce:** the first build overflowed 30px at 390px because four children plus 24px gaps and
24px padding needed 420px of room.

**`/datasets` — upload + list**

1. Title band: page title at h1, one-line explanation, and the *primary* action. One focal point.
2. Upload band: a real **dropzone** (dashed `--control`, `--surface-2` fill, ≥160px tall desktop,
   ≥140px mobile) with an upload glyph, a bold line, a muted format line and a per-file status row.
   Drag-over state changes border to `--accent` + `--accent-soft` fill. The optional `.con` file sits in
   a visually subordinate slot (smaller, secondary) inside the same band, never as an equal twin.
   Limits line sits directly under the dropzone as a scannable list (not a grey wall of text).
3. File list band: **cards on mobile, a real table on desktop** — not one table squeezed into 390px.
   Each file row/card carries: format chip, filename (mono), status with glyph + word, the capacity
   band (motif 1), metadata line (respondents × items · size · read format), and two actions with a
   clear hierarchy (one primary, one secondary).
4. Empty state: designed, with a next-step sentence, not a bare "no data".

**`/datasets/{id}` — preview + mapping**

1. Header band: filename, status, and the metadata as labelled pairs; back link.
2. Preview band: the response matrix table, sticky header, `sticky` first column, `NA` cells visually
   distinct from `0`/`1` using `--surface-2` plus a legend line.
3. Mapping band: token inventory as rows (token, mono; frequency, tabular right-aligned; classification,
   a real `<select>` with a text label). The commit action is **sticky** and always reachable, never
   buried under a long table.
4. Missing band: motif 2 axis on top, then the table, sortable with `aria-sort`, severity tint by band
   (`<2%` fit, `2-5%` warn, `>5%` misfit) with the number always printed.

**Vertical rhythm (all pages).** The first content block never touches the app bar: minimum `--space-8`
(32px) between the bar's bottom edge and the first band on desktop, `--space-6` (24px) at `<=719px`.
**Measured defect to never reintroduce:** every narrow band rendered at `0px` below the bar, because only
`.band--title` carried top padding while `.band--narrow` carried none, so `/account`, `/login`,
`/register`, `/forgot` and `/reset` all started glued to the header (probe: gap = 0px at 1440/1150/900/390,
both themes).

**Auth pages (`/login`, `/register`, `/forgot`, `/reset`), `/gate`.** One column, max 480px,
same shell, no marketing hero, no fake screenshots. Gate page states plainly that the product is not open
yet and links to login. Narrow-and-centred is right HERE because each of these is a single-purpose form;
the same 480px on a logged-in content page reads stranded (measured: a 432px card is 30% of a 1440px
canvas, with 293px of dead space under it).
**After a successful sign-in, the landing target is `/datasets`, never the profile page.** That covers the
login handler AND the two "already signed in" branches (`/login` and `/register`): a signed-in visitor
asking for a sign-in page is sent to the work, not to a profile. E-mail verification and password reset
land back on `/login` with a status message on purpose (the user has to sign in anyway), and the sign-in
that follows lands on `/datasets`. The first screen after signing in must be the actionable one, and a
redirect into a profile page is a design bug even when that page is flawless.

**`/account` — identity and summary (logged-in; a content page, never a form page)**

1. Block 1, identity band: h1 `Profil Akun`, the verification chip, and the account facts as labelled pairs
   (email mono, registration date). The account's own initials open the block as the page's focal point.
2. Block 2, summary band: a real TWO-COLUMN composition at `>=900px` (single column below, stacking in the
   same order) — left column `Berkas Pengukuran` (how many files the account holds, the limits that are true
   for it, link to `/datasets`); right column `Analisis` (how many analyses, the last one's date and status,
   link to that result when it exists). Both columns carry numbers read from the database, never invented:
   with nothing stored the copy says `Belum ada berkas` / `Belum ada analisis`, never a bare zero dressed up
   as a measurement.
3. Block 3, session band: `Keluar` as a destructive outline button, alone and last.
4. The navigation controls (account menu, theme toggle) stay in the shell, never inside a content card, and
   the blocks are bands in that shell rather than one narrow panel.

**Account avatar.** The initials show TWO letters (`IH`), not one: a single letter is legible for `M` and
invisible for `I`, `l`, `J`, which is what `idzharul.huda@gmail.com` rendered (a thin stroke on a 28px
tinted disc reads as a broken image). Minimum 44px on mobile, no border, no glow.

### The dashboard: `/analyses/{id}/explore` (redesign, 5 Oct 2026)

Owner's directive (5 Oct 2026): *"redesign ui/ux raschlab web terutama bagian dashboard"*, and *"biarin dia
juga yang nentuin design nya"*: the writer decides. This section is that decision. It is the contract for the
four redesign runs; a later run follows it and never re-picks it.

**Diagnosis (measured 5 Oct 2026 before any edit, seeded 147-item / 490-person analysis, both themes).** The
palette and type were not the problem: every token pair already passes AA and the owner picked them from the
artifact. Composition was. At 390px the first content a reader met was a back link, the share-password form,
five engine rows and a long warning box. The eight boxed tabs wrapped to **4 rows (224px)**, and the Wright map
started at **1617px**, nearly two phone screens down. At 1440 the map started at **1062px**, below a 900px fold,
so a desktop first screen showed no result at all. Three export buttons stacked full-width above the chart. The
readout was a browser-default `<dl>`. A stray `</div>` left the map, its readout and the misfit toggle
**outside** `#panel-wright`, so every other tab showed the map first (Butir content measured at 1994px on a
phone). `Salin tautan` had no handler (a dead control), and the account menu ignored Escape.

**Direction: keep the instrument, rebuild the reading order.** Same palette, same type family, same dials
(ENERGY 3 / RHYTHM 3 / MOTION 2). The dashboard now reads like a product's reading surface (the owner's
references are Claude and Netflix): the identity of the run is one compact band, the views are a quiet text tab
strip, and the first screen at every width is the result itself.

**What a reader must see first, in this order:** which run this is (file, run number, status), how big it is
and how many items misfit (the figure row), then the map. Provenance (engine version, timing, mode), sharing and
the anchor explanation are one click away, never in front of the result.

**Frame, top to bottom:**

1. **Header band `.dash-head`.** Back link; an eyebrow `Analisis #<id>` (mono); the h1 is the **file name**
   alone in the display face (the view lives in the tab strip; an h1 that said `Peta Wright:` kept saying it
   after the reader switched tabs). Status chips sit in one row under the title (`OK Selesai`, `Dipakai` /
   `Arsip`, and the anchor state as a chip with a glyph and a word). The actions sit right of the title on
   desktop and under it on a phone: the mark toggle and a **`Bagikan` popover** (a `<details>` menu holding the
   unchanged share form; it opens by itself when a link was just created or refused, because a once-only link
   must be seen). Provenance and the retention line live in an inline disclosure **`Detail proses`**. The
   unanchored / anchored explanation is an inline disclosure whose summary line states the fact (`Hasil Tanpa
   Jangkar (Unanchored)`); the anchor-dropped warning stays a full open alert because it reports a problem.
   Reason: the facts stay one click away and stay in the markup, while the band stops being taller than a
   phone screen.
2. **View tabs `.tabs`.** Text tabs on the paper ground with a hairline under the strip, sticky under the app
   bar, **one row at every width**. The active tab is ink with a 2px accent underline; inactive tabs are muted.
   Where eight labels do not fit (measured: below about 900px), the strip scrolls sideways with a scroll
   shadow on the side that has more tabs, and the active tab is scrolled into view on load and on every
   activation. Reason: a boxed strip that wraps spends 224px of a
   phone on navigation; a scroll strip is the shape every large product uses for more destinations than fit.
   Each tab is whole and reachable by swipe, Tab and the arrow keys; a tab cut by the strip's edge is the cue
   that more follow, never a label cut inside its own box. The underline is a shape, so the active state never
   rests on colour alone.
3. **Panels** share one frame width, `--shell-wide` (1360px). Reason: 1120px is right for the forms and lists
   elsewhere; at 1440 it left 320px empty while the Wright chart (at least 930px of plot) and the 14-column
   tables scrolled sideways inside it.

**What each view is FOR and the shape it takes** (one focal point each; no two share a layout, RHYTHM 3):

| view | the question it answers | shape | focal point |
|---|---|---|---|
| Peta Wright (landing) | Does the test fit these people, and which items do not fit? | figure row, then chart frame beside a readout rail (stacked below 1100px), exports at the rail's foot | the map |
| Ringkasan | Is this run usable? | verdict band (cleanliness band + misfit count) over a figure grid on top rules, the verbatim engine table last | the verdict |
| Butir | What does each item look like? | one toolbar row (search, count, export), dense table with pinned header, pager at the foot | the table |
| Partisipan | How is ability spread, and who misfits? | histogram in a chart frame, then the Butir toolbar shape over the paged table | the distribution |
| Opsi & Distraktor | Do the distractors behave? | caption over a two-row-header table grouped by item, pager | the table |
| Sub-Subtes | How do the sub-tests compare? | one caption line over a compact summary table | the counts |
| Tabulasi | How do difficulty and discrimination cross? | summary matrix first, then a search toolbar over the per-item table | the matrix |
| Bandingkan | What changed between two runs? | sticky two-select control strip, a figure row of match counts, the delta chart, the paired table | the delta |

**The landing view, Peta Wright.**

- **Figure row `#wright-meta.figure-row`**: `Partisipan`, `Butir`, `Dikecualikan (skor sempurna/nol)`, and the
  `Butir misfit` count the client appends from the embedded payload. Each figure is a label over a value on a
  top hairline; only the first carries the accent rule. A row of figures, never boxed stat cards. The frozen
  sentence (`Partisipan: <n> · Butir: <n> · ...`) is still the element's text: the colons and middle dots
  are `.sr-only`, so a screen reader and a copy-paste get the sentence while the eye gets the figures.
- **Chart frame `.chart-frame`**: a `--surface` panel with a hairline and `--radius-lg`. A toolbar line holds a
  one-line caption saying what the chart encodes, and the misfit toggle, so the toggle sits **before** the 147
  item stops in the Tab order. `#wright-scale` stays a `.chart-scroll`; below 720px a hint line says the map
  scrolls sideways.
- **Readout rail `.readout-rail`**: titled `Rincian butir`; `#wright-readout` shows the frozen prompt until an
  item is chosen, then the item's values as a two-column list (muted term, mono value). Beside the chart at
  `>=1100px` so a choice and its numbers are on screen together; under the chart below that. The three export
  links sit at the rail's foot as one compact group: a secondary action, after the thing it exports.
- **Figure values** use Archivo 600 with proportional figures; columns keep `tabular-nums`. Reason: tabular
  digits at 28px read loose; alignment only matters in a column.

**States (every one renders as text, never a blank box):**

| state | where | what renders |
|---|---|---|
| loading (fragment views) | the panel | `Memuat data…` in a quiet `.empty--loading` block, `role="status"`, the panel `aria-busy="true"` until the fragment lands |
| error (fragment fetch) | the panel | the loading block is **replaced** (never left under the error) by the frozen alert plus a working `Coba lagi` button that re-requests the same fragment |
| error / empty (Wright) | inside the chart frame | an analysis with zero measure bins cannot draw a map, and the server already reports it as `wright_error`, so the empty map is the error state: the frozen alert takes the chart's place, and the toggle and readout rail are not rendered (a toggle with no map is a dead control) |
| loading (Wright) | none | the map draws synchronously from the embedded payload on `DOMContentLoaded` (measured: load event at 97ms), so a loading text would flash for a frame and then lie under noscript; there is none on purpose |

**The fragment views (run 2, 5 Oct 2026).** Shared parts, each with its reason:

- **View head `.view-head`**: an h2 at `--step-22` (panel titles sit under the tab strip and the figure row,
  so the page-scale 28px read as a second page title), one `.view-lede` line saying what the view shows and
  how to read its marks, and the view's actions on the right. Reason: every view states its question before
  its numbers.
- **Toolbar `.view-tools`**: search on the left (at most 560px), the export on the right, one row on desktop.
  On a phone the field and its `Cari` button share one row under the label (three stacked full-width rows cost
  about 150px before the first table row).
- **The data plane `.table-scroll`**: one `--surface` frame with a hairline and `--radius-lg`. The `thead` is
  sticky as one block, because a sticky `th` per row stacked the engine's two header rows on top of each other.
  Headers do not wrap and numeric headers align right over their numbers (`th.num-col`). The caption is pinned
  to the frame's left edge and held to the visible width, so on a phone it no longer scrolls off with the table.
- **`.table-scroll--pin`**: the row identifier (first column) stays on screen while a wide table scrolls
  sideways on a phone. Reason: a bare 14-column table squeezed into 390px is a named tell; scrolling it without
  its identifier loses the row.
- **`.table-foot`**: the count line and the pager share one footer row under the table.
- **`.row-flag`**: a row that passes a documented threshold gets `!` in its identifier cell plus a 9% `--warn`
  tint, and the view head says what `!` means. Never the tint alone. Butir uses it for INFIT MNSQ at or above
  the analysis's own misfit threshold (the same cut the Ringkasan count uses).
- **Ringkasan verdict band `.verdict`**: `Kebersihan Data` (3 parts) beside `Butir Bermasalah` (2 parts) on
  surface cells at >=900px, stacked below. The misfit count is the view's **one hero figure** (`.hero`,
  `--step-56` / `--step-40`, Archivo 600, `--warn` when above zero, the word `butir` beside it), the frozen
  sentence under it. Reason: Ringkasan answers "is this run usable?", so the two verdicts lead and the
  statistics follow.
- **Cleanliness band words in HTML**: the SVG keeps only the line and the three segments (route geometry,
  untouched) and stretches to the cell; the `0` / `<n> baris` endpoints use the motif's `.band-scale-ends`, and
  `.band-legend` lists each segment as a colour swatch plus count and share in words. Reason: the SVG labels
  sat under each segment, so two small segments at the right end printed on top of each other and past the
  viewBox, and at 390px the 100%-width band drew 11-unit text at about 7px.
- **Rekap figures** use the figure-on-a-rule shape of the landing view (Indonesian label, the engine key as a
  mono note so each figure traces to its row in the table under it), never boxed cards.
- **Bandingkan control panel**: a surface panel (two selects on row one; the S.E. filter and the one primary
  button on row two, so DOM order is visual order), not sticky (it shared the sticky tab strip's offset). The
  match counts, means, delta filter, chart and table render only once two runs are chosen: before that the panel
  printed `Cocok: 0 butir` zeros and offered a filter with nothing to filter. The delta chart draws at its
  natural 860-unit width inside a 70vh frame, sorted by the largest change, so its text never scales below the
  micro label.
- **No opacity on text**: a muted state uses `--muted` (which passes 4.5:1), never `opacity`. The delta chart's
  `opacity: 0.45` rows measured about 2:1. Disabled controls keep 45% opacity: WCAG exempts inactive controls.
- **Opsi grouped per item**: one `tbody` per ENTRY with a firmer rule between items; the key option (SCORE 1 in
  this dichotomous product) carries `✓` and weight on its option code. Row markup is untouched (the `<tr>` count
  is pinned) and a header row with only empty cells is hidden by CSS, not removed.
- **Sub-Subtes range strips**: one row per sub-subtes (name, item and misfit counts, the mean item measure as a
  thick tick with a +/- S.SD whisker on one shared logit axis, the values as text), then the compact table. The
  axis runs from the floor of the lowest mean minus SD to the ceiling of the highest mean plus SD and always holds
  0; a value that does not parse prints `-` and is never drawn at 0. Reason: the question is "how do the
  sub-tests compare?", which a position on one scale answers faster than seven rows of numbers.
- **Tabulasi**: summary grouped per sub-subtes, a share bar of high-discrimination items (TINGGI over JUMLAH,
  stored counts) beside each total, then a search toolbar over the per-item table; the toolbar stays while a
  search is active so a search with no match can be edited.
- **Static chips are not controls**: only `button.chip` gets the 44px pointer treatment; the old `.chip-row
  .chip` rule gave the Kebersihan status chips a pointer and a hover they could not honour.
- **Tab strip scroll shadows** replace the first build's mask fade (which also faded the strip's background,
  so text scrolling under it showed through): a soft 16px edge shows only on the side with more tabs.

**Shell fix carried by this change.** At `<=480px` the nav link reads `Hasil` (the word `Analisis` is hidden,
the accessible name stays `Hasil Analisis`), because a scroll strip of two links cut `Hasil Analisi` mid-word at
375px. The account menu and the share popover close on Escape and return focus to their summary.

**Token change for the dashboard (5 Oct 2026).** One token is added and none changes value:

| Token | Value | Reason |
|---|---|---|
| `--shell-wide` | `1360px` | Dashboard frame width (header band, tab strip, panels). Measured: the 1120px shell left 320px empty at 1440 while the Wright plot (930px minimum) scrolled inside it. Forms and lists keep `--shell-max`. |

New text/surface pairs the frame introduces, measured with the WCAG formula: inactive tab `--muted` on `--paper`
5,67:1 light / 8,98:1 dark; active tab `--ink` on `--paper` 14,39 / 17,14; the active underline `--accent` on
`--paper` 7,44 / 10,95 (a non-text indicator, needs 3:1); readout flag `--warn` on `--surface` 6,92 / 10,06; chart
frame text `--muted` on `--surface` 6,22 / 8,20.

**Ringkasan is the view most at risk of the banned card wall.** Its figures are one grid, each a label
above a mono value on a `--line` rule, and only the first figure may carry the accent rule. A figure grid,
never four equal stat cards; the grid must stay multi-column at desktop width, because a single column is
how the earlier build read as a stacked list.

**Long tables.** Tables with more than about 40 rows scroll inside `.table-scroll` with a sticky header, so
the column names never leave the screen while the console is being read. The cap is `70vh`.

## E-mail palette (the one documented exception to "tokens only")

Mail clients do not run stylesheets, so `app/templates/email/*.html` must carry inline CSS and literal hex.
That exception is granted, but only against the hues declared here — an e-mail is a user-facing surface of
this product and a second accent hue there reads as a different product:

| role | value | note |
|---|---|---|
| paper | `#F7F4EF` | same warm ground as the light theme |
| surface | `#FFFFFF` | the card that holds the text |
| ink | `#1E2422` | body and headings |
| muted | `#59635F` | secondary lines |
| line | `#DED6CA` | hairlines |
| accent / link | `#0E5A47` | links and the primary button (green family, never blue) |

Blue was the previous e-mail link colour (`#0B6C8F`); it exists in no token block and in no other surface.
**A new colour may enter the e-mail templates only by being added to this table first.**

## Components and their states

- **Alert**: hairline border all around (`--control` when neutral, the semantic colour on `.alert--fit/--warn/
  --misfit`), radius `--radius-md`, `--surface` fill, and the semantic colour carried by the **leading glyph or
  word** inside the box. **No thick coloured side stripe** — that shape is the named Hallmark side-stripe tell
  and was removed on 26 Sep 2026; colour must never be the only signal.
- **Button**: primary (accent fill, ground-coloured label, 44px tall, radius 10px), secondary (`--control`
  outline, ink label), ghost (text only), destructive (outline `--misfit`). Hover shifts fill by 6%,
  active by 10%, focus shows a 2px `--accent` ring at 2px offset, disabled is 45% opacity with
  `cursor: not-allowed`. **Exactly one primary button per screen.**
- **Input / select / file**: 1px `--control` border, radius 10px, 44px tall, label above (never a
  placeholder-only field), focus ring, error state carries text.
- **Chip / status**: radius 8px (not a pill), `--surface-2` fill, glyph + word. Status vocabulary is
  fixed: `Menunggu konfirmasi` (warn), `Siap dianalisis` (fit), `Ditolak` (misfit), `Diproses` (accent).
- **Table**: sticky header on `--surface-2`, `th scope`, `aria-sort` on sortable columns, 3% ink hover
  tint, numeral columns right-aligned and tabular, no zebra fills, caption line above every table.
- **Metric / capacity band**: label, value, unit, band. Values tabular. Never four equal stat cards.
- **Toast**: confirmed actions only (upload accepted, file discarded), dismissible, `aria-live="polite"`.

- **Export control (F11, 26 Sep 2026)**: downloading how a table looks on screen. Wrapper `.action-bar`, control
  `.btn .btn--secondary`, label `Unduh Excel`, and a mandatory `aria-label` naming the table (six controls with
  the same visible word are unusable with a screen reader). On the list page the four keys are `.text-link`
  anchors, not buttons, so a row does not become four buttons wide. **Zero new classes**: the pins in
  `tests/test_ui_contract.py` (145 used / 159 defined) do not move for this feature. An export is an accent-free
  action: never `.btn--primary`, and never the only primary on the page. No em dash in its status text.
- **Two controls in one panel (F11b, 26 Sep 2026)**: the wright panel downloads two different tables, so its labels
  name the side each button carries, `Unduh measure` and `Unduh frekuensi` (see `INTERFACE.md`, sheet `frekuensi`).
  Same wrapper, same `.btn .btn--secondary`, same mandatory `aria-label`; the visible label still leads with the verb
  `Unduh`. A generic `Unduh Excel` next to a specific one would leave the reader guessing which button is which, so
  wherever a panel carries more than one export, every label in it is specific. Everywhere else the single label
  stays `Unduh Excel`.
- **Settings screen (F12, 26 Sep 2026)**: the step between a ready dataset and a run. Vertical order: back-link to
  the file, one title, an optional `alert alert--misfit` for a rejected value, then the three fields in ONE column
  (`Ambang Misfit` a number input with step 0.05 and a hint naming the default and what lowering it does, `Mode`
  and `Desimal` as selects), then the screen's single primary action `Jalankan Analisis` (`.btn .btn--primary`), then
  one closing line saying every analysis keeps its own settings. Existing form classes only, so the class pins stay
  put. The threshold is a number the user typed, never a badge, and it renders with a comma decimal separator
  (`1,50`). Defaults are visible, not implied: the form opens filled with `1,50` / `compat` / `2`.

## States (required, not bonus)

Empty, loading (upload + commit), error (each saying what happened, what to do, and keeping the user's
file listed), and the long case: an uploaded file appears in the list immediately with a pending status,
so the screen is never blank and never lies about progress.

## Motion (MOTION 2)

Hover/focus/state transitions 120ms; band and dialog entrances 200ms ease-out; one progress indicator per
action. No scroll reveals, no parallax, no count-ups, no animated backgrounds. **Every declared
`transition` or `animation` must sit inside a `@media (prefers-reduced-motion: reduce)` fallback** — one
uncovered transition is a failure, not a nitpick.

## Numeric limits in the copy (the two caps must agree)

Upload limits are pinned as a PAIR and the rendered page must state both exact numbers:

- **16 MB per file** (`MAX_UPLOAD_BYTES = 16 * 1024 * 1024`)
- **6.000.000 cells per dataset** (`MAX_CELLS = 6_000_000`)

**Export limits (F11, 26 Sep 2026) are a second pinned pair:** `EXPORT_MAX_ROWS = 1_048_000` and
`EXPORT_MAX_CELLS = 2_500_000`, stated in the copy of the refusal page with the actual numbers the table holds.
The row cap is Excel's own sheet limit (1.048.576) minus headroom; the cell cap comes from measurement through
the real writer path (687.540 cells = 10,3 s / 76,5 MiB; 1.500.030 cells = 28,4 s / 122,7 MiB, against a 120 s
timeout on a 2 GiB instance). Raising either cap is a memory/instance decision, not a code-only change.

Why 6M and not 8M: the ceiling is set by **memory, never by time**, and it moves with the instance. The
engine needs 5,2 s for 2,29 M cells and 11,2 s for 3,90 M cells against a 120 s request timeout, while
peak RSS on a 45.833-person matrix grows from 0,31 GiB (0,69 M cells) to 0,70 GiB (2,29 M) to 0,94 GiB
(3,90 M). At 3,90 M cells a 1 GiB instance would OOM, so the instance is **2 GiB** (`deploy_ui.sh`) and
6 M cells lands near 1,4 GiB with about 30% headroom. Raising this number without raising the instance
memory is a defect. Measured with the real parser plus the real engine:

| Cells | File | Upload | Engine | Peak RSS |
|---|---|---|---|---|
| 0,69 M (45.833 × 15) | 1,7 MB | 1,07 s | 8,4 s | 0,31 GiB |
| 2,29 M (45.833 × 50) | 5,3 MB | 1,29 s | 5,2 s | 0,70 GiB |
| 3,90 M (45.833 × 85) | 8,5 MB | 3,04 s | 11,2 s | 0,94 GiB |

The owner's real datasets (TBS 2025, 6 runs) top out at 2.328 × 147 = 342.216 cells, and the assessment
file that drove this work is 45.833 × 59 = 2,7 M cells, so 6 M keeps 2,2× headroom over the largest real
file seen. A test must assert the rendered upload page contains both numbers, so the copy can never
drift from the constants: the dataset page renders every occurrence of the cell cap from the `max_cells`
context value, and a literal limit in that template is a defect.

## Tells to avoid, by name (rejected on sight)

**Retro-desktop:** grey window chrome or title bars; bevels or inset borders; 11px cramped rows; boxy
2px hard-edged panels; ALL-CAPS grey column headers; unstyled native controls (a bare `input type=file`);
a dense mono block used as body copy; a screenshot-style toolbar.

**Template-default / AI-default:** a wall of equal stat cards; amber or cream-plus-terracotta brand fills;
gradient buttons; glows; glassmorphism; radial orbs; background grid or dot patterns; emoji as icons; a
fake terminal window; pills everywhere; skeleton blocks used as product shots; hero illustrations;
"AI powered / seamless / powerful"-class adjectives; an em dash in any copy; a coloured left stripe on
cards; a bare table squeezed into a 390px screen.

## Accessibility contract

Keyboard reachable in visual order; visible focus ring (2px `--accent`, 2px offset, never `outline: none`
without a replacement); real `<th scope>` and a caption above every table; `aria-sort` on sortable
headers; `aria-live="polite"` on upload and commit status; contrast per the measured tables in **both**
themes; tap targets ≥44px on mobile; **no horizontal overflow at 390px and none at desktop**; reduced
motion honoured; no information carried by colour alone; framework debug routes (`/docs`, `/redoc`,
`/openapi.json`) off outside dev.

## Swap test

Swap out the wordmark: the page still cannot belong to anyone else. It organises every file around a
measured band with real numbers, states its limits as exact values, and reads as an instrument for
Indonesian assessment work. Answer: passes.
