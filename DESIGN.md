# DESIGN.md — RaschLab web

Design contract for every UI artifact in this repo. Arc owns this file; a writer executes it and never
re-picks a direction, never mixes in a second palette, never opens a second direction skill.

- **Direction skill for writers: `clean-minimal-beige-light-mode`** (subject: a calibre instrument for
  measurement, read on warm paper surfaces — not a cold enterprise console).
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

**Plus Jakarta Sans** for UI text, **IBM Plex Mono** for numerals, item IDs, dataset IDs and code.

Reason: Plus Jakarta Sans was commissioned as the identity face of Jakarta; this product's whole
audience and every dataset in it is Indonesian, so the face ties the interface to its context instead of
borrowing the AI-default look (Inter / Geist / Space Grotesk say nothing about measurement). Plex Mono
keeps the instrument role: unambiguous `0/O` and `1/l` for item codes, and `tabular-nums` so columns of
measures line up.

- Load from Google Fonts with `preconnect` + `display=swap`, and declare a fallback stack that still
  looks deliberate (`Georgia, serif` for display, `system-ui` for body) when the CDN is unreachable.
  **Self-hosted subset in `app/static/fonts/` is a later task (F5), named here so it is not forgotten.**
- Scale (desktop / mobile): display `44/30`, h1 `40/30`, h2 `28/24`, h3 `22/20`, lead `18/17`,
  body `16/16`, secondary `14/14`, micro label `12/12` (micro labels only, never body copy).
- Weight carries hierarchy: 400 body, 500 labels and controls, 600 headings and numbers, 700 reserved
  for the single page title. No all-bold rows, no uppercase-tracked micro labels.
- Line height: 1.2 headings, 1.5 body, 1.45 table body. Measure (line length) under 72 characters for
  prose; the hero line under 46.
- Every numeral in a table, metric tile or scale band uses `font-variant-numeric: tabular-nums`.

## Identity motif: the measured band (pita ukur)

The subject is a calibrated ruler: every dataset in the product is a matrix that will end up as items and
persons on one logit scale. The motif is a **thin measured band — a labelled tick rule with real
numbers** — used in exactly two places, each carrying information:

1. **Dataset card, capacity band.** A band showing cells used against the 8.000.000-cell cap, with both
   endpoints labelled and the dataset's own value printed **plus the share of the cap as text** (for example
   `12.000 sel terpakai (0,15% dari 8.000.000 sel)`). Tells the user how much room is left. The fill is the
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

## Components and their states

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
