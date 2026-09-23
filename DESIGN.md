# DESIGN.md — RaschLab web

Design contract for every UI artifact in this repo. Arc owns this file. A writer executes it, never
re-picks a direction, never mixes in another palette.

- **Direction skill for writers: `data-dashboard`** (subject: an analysis console whose whole job is to
  show many numbers at once).
- **Process skills, always on: `design-tokens`, `a11y-audit`, `output-enforcement`.**
- **antislop mode: DURING**, closed by the Hallmark audit gate.
- Human-facing copy: Indonesian. Code, identifiers, comments: English.

## Design Read

Reading this as: a modern measurement workbench for people who analyse test items (teachers,
assessment teams, psychometricians), in a precise instrument language with real depth and no retro
chrome, dial **ENERGY 2 / RHYTHM 3 / MOTION 2**.

**The bar is current, not safe: this must look like a 2026 product, not like a statistics program from
2005.** Dada's words, 23 Sep 2026: "buat bener bener modern ya jangan yang keliatan jadul banget kaya
tampilan winsteps". The legacy tool it replaces is grey Windows chrome with cramped tables, so
anything that reads as desktop-era software is a defect here, not a style choice.

## Why not the skill named `impeccable`

The design library contains a skill literally named `impeccable` (editorial-poster: cream + burnt
orange). It is not used: that cream/terracotta palette was already rejected by Dada once, and a poster
language fights a screen built out of dense numeric tables. The direction comes from the subject, an
instrument that measures, and from the era, 2026.

## Colour tokens

Authority for colour. `app/static/tokens.css` mirrors these blocks; there is no raw colour literal
anywhere else in the repo. Light and dark are both shipped and both measured.

**Light**

| Token | Value | Reason | Measured |
|---|---|---|---|
| `--paper` | `#F4F5F7` | Cool page ground; a touch of blue keeps dense tables from going muddy | — |
| `--surface` | `#FFFFFF` | Data sits on the brightest plane | — |
| `--raised` | `#FFFFFF` | Raised panels get elevation from shadow, not from a different fill | — |
| `--ink` | `#0F1418` | Near-black for text and numerals | 16,98:1 on paper |
| `--muted` | `#5A6472` | Secondary text, labels, notes | 5,50:1 on paper |
| `--scale` | `#0B6C8F` | The instrument accent: measure scale, links, focus ring, primary action | 5,41:1 on paper |
| `--fit` | `#12694A` | Within-range fit, muted so it never shouts | 6,12:1 on paper |
| `--warn` | `#8A5A00` | Borderline statistics | 5,43:1 on paper |
| `--misfit` | `#B0251A` | Misfit flag, always with a glyph and the word "misfit" | 6,16:1 on paper |
| `--rule` | `#DFE3E8` | Hairlines and separators; decorative, never the only signal | 1,29:1 on surface |

**Dark**

| Token | Value | Measured |
|---|---|---|
| `--paper` | `#0D1116` | — |
| `--surface` | `#151A20` | — |
| `--raised` | `#1C2229` | — |
| `--ink` | `#EAEFF3` | 16,36:1 on paper, 15,11:1 on surface |
| `--muted` | `#9BA7B2` | 7,72:1 on paper |
| `--scale` | `#59BCE0` | 8,74:1 on paper |
| `--fit` | `#5FD3A0` | 10,20:1 |
| `--warn` | `#E7B24C` | 9,80:1 |
| `--misfit` | `#FF8A7A` | 8,27:1 |
| `--rule` | `#2A323B` | 1,35:1 on surface, decorative |

Every text pair above clears 4,5:1 and the focus ring clears 3:1 in both themes. Contrast was
**measured** with the WCAG formula, not eyeballed. Dark is the `prefers-color-scheme` default only when
the OS asks for it; there is no forced dark app.

## Typography

**IBM Plex Sans** for UI text, **IBM Plex Mono** for numerals, item IDs, run IDs and code. Reason:
Plex was drawn as a technical/instrument family, and the mono shares its skeleton, so a table of
measures reads as one voice instead of two pasted fonts (the reason to avoid the AI-default picks
Inter, Geist and Space Grotesk here, which say nothing about measurement).

- F0 loads them from Google Fonts with `preconnect` + `display=swap`; **self-hosted subset in `app/static/fonts/` is the F5 task**, so the app never depends on a third-party CDN for its identity.
- Numerals carry `font-variant-numeric: tabular-nums` everywhere.
- Scale: 12 / 13 / 14 / 16 / 20 / 24 / 32 / 44. Body 15-16 with line-height 1.5; table body 14 with
  line-height 1.45; the single lead number uses 44 at weight 600.
- Weight carries hierarchy: 400 body, 500 labels, 600 numbers and headings. No all-bold rows, no
  uppercase-tracked micro labels anywhere.

## Surfaces, radius and elevation

Three planes (page → surface → raised) and two shadows; that is how depth is expressed, never with
gradients, glows or bevels.

- Radius: `--radius-sm 6px` inputs and table containers, `--radius-md 10px` cards, `--radius-lg 14px`
  panels and dialogs. A pill is allowed only for a real status chip.
- `--shadow-1`: `0 1px 2px rgb(16 20 24 / 0.05), 0 1px 3px rgb(16 20 24 / 0.07)` for cards.
- `--shadow-2`: `0 10px 30px rgb(16 20 24 / 0.10)` for dialogs and popovers.
- In dark, shadows are replaced by a 1px `--rule` border plus a slightly raised fill.

## Identity motif: the measure scale

The subject is a calibrated ruler: items and persons placed on one logit scale. The recurring motif is
a **fine tick rule** (1px baseline, 3px and 5px ticks, drawn in `--scale`), used in exactly three
places: under the header of the item and person tables, as the axis of the Wright map, and as the
"measure strip" on a run summary that puts the item-measure range and person-measure range on the same
ruler. Reason: it makes the product recognisable without a logo, and it comes from what the numbers
mean rather than from decoration.

## Layout bands (results screen), RHYTHM 3

Bands with different shapes; a wall of equal cards is banned (`data-dashboard`'s loudest tell).

1. Lead band: the leading number at 44px with the measure strip, spanning 8 columns; a compact run
   status panel beside it on 4.
2. Account band: persons input / reported / calibrated / extreme / deleted as one labelled line, plus
   the item count. Not five cards.
3. Distribution band: two different shapes side by side, the Wright map and a fit histogram, inline SVG
   from tokens, no chart library.
4. Table bands: item table, person table, option table, then the summary.
5. Footer: engine version, mode, iterations, wall time, run ID.

12-column grid with explicit spans, collapsing 12 → 6 → 1. Never `repeat(auto-fit, ...)` for the
primary bands.

## Components and their states

- Buttons: primary (accent fill, 6px radius, 40px tall), secondary (1px `--rule`, ink text), ghost
  (text only). Hover darkens by 6%, active by 10%, focus shows the 2px `--scale` ring at 2px offset,
  disabled is 45% opacity and `cursor:not-allowed`.
- Inputs: 1px `--rule`, 6px radius, 40px tall, focus ring, error state carries text, never colour alone.
- Status chip: pill, real status only (queued / running / done / failed), no decorative badges.
- Tables: sticky header, sortable with `aria-sort`, hover row tint of 3% ink, 1px `--rule` separators,
  no filled zebra stripes, numeric columns right-aligned and tabular.
- Run progress: determinate bar when progress is known, otherwise an indeterminate bar plus the
  account-of-persons line; `aria-live="polite"` on the status text.
- Toasts for confirmed actions (upload accepted, run finished), dismissible, never blocking.
- Skeleton loaders only while a table fetches, never as a product shot.

## States (required, not bonus)

Empty (no project yet, project with no run), loading (upload, run), error (upload rejected, parse
failed, engine failed, each saying what happened and what to do while keeping the user's file listed),
long run (the run row exists in the list immediately, the screen is never blank).

## Motion (MOTION 2)

Hover, focus and state transitions at 120ms, panel and dialog entrances at 200ms ease-out, one progress
indicator during a run. No scroll reveals, no animated charts, no parallax, no number count-ups.
`prefers-reduced-motion: reduce` removes all of it, including the indeterminate shimmer.

## Tells to avoid, by name (rejected on sight)

**Retro-desktop (the reason this file exists):** grey window chrome or title bars; beveled or inset
borders; 11px cramped rows with no vertical rhythm; boxy panels with 2px hard edges; ALL-CAPS grey
column headers; default unstyled buttons and selects; a dense mono block used as body copy; a
screenshot-style "file, edit, view" style toolbar.

**AI-default:** four or five equal stat cards; cream-plus-terracotta palette; amber brand fills;
gradient buttons; glows; glassmorphism; radial orbs; background grid patterns; emoji used as icons; a
fake terminal window; pill-shaped everything; skeleton blocks as product shots; hero illustrations;
"AI powered / seamless / powerful"-class adjectives; an em dash in any copy; a coloured left stripe on
cards.

## Accessibility contract

Keyboard reachable in visual order; visible focus ring (2px `--scale`, 2px offset); real `<th scope>`
and table captions; `aria-sort` on sortable headers; `aria-live="polite"` on run status; contrast per
the measured tables above in **both** themes; tap targets at least 44px on mobile; no horizontal
overflow at 390px; reduced-motion honoured; no information carried by colour alone.

## Swap test

If the logo and product name were swapped out, the page still reads as its own thing: no other
analytics console organises its screen around a logit ruler with item and person ranges on one scale,
and the tick-rule motif is not a template part. Answer: passes.
