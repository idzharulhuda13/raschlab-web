# PLAN.md — Share link read-only per analisis (raschlab-web)

**Binding contract. Phase 2 (writer) executes this literally; Arc verifies every claim by measurement.**
Where this file and any other description disagree, this file wins. A writer that believes a step is wrong
STOPS and says so in its report instead of improvising.

**Provenance.** Owner decisions = Dada, 4 Oct 2026 (clarify). Three planner runs produced drafts on the same
brief (`/root/raschlab-ops/share_link_ab/brief_share_link.md`); this file is the curation of all three, and the
per-arm measurements are in that directory:

- `planner` profile, `xiaomi/mimo-v2.6-flash` (`reasoning_effort: max`), session `20261004_114256_570262`,
  plan `out_mimo.md` (21,898 B) — 9/10 mechanical claim checks pass.
- `claude-sonnet-5-5-high` via agy, conv `03fad537`, 219 s, 7.856% of the Claude/GPT weekly bucket,
  plan `out_claude.txt` — 8/8 claims pass.
- `claude-opus-5-5-high` via agy, conv `7dc2ef71`, 281 s, 16.899% of the same bucket, plan `out_opus.txt` —
  9/12 claims pass.

**Curation corrections already applied here** (measured, do not re-derive):

1. `app/main.py` does NOT call `FastAPI(...)`: it defines `class App(FastAPI)` (L21) and instantiates
   `app = App(` (L31). The opus draft's "add to the `FastAPI(...)` constructor" is corrected to `App(`.
2. `_clean_audit` lives in **`app/analyze.py:56`** and is imported into `app/explore.py:24`, called at
   `app/explore.py:590`. It locates the STATUS column **by header name** (`header.index("STATUS")`), so passing
   redacted rows is safe; we still pass the original rows so no behaviour changes.
3. **No `static/explorer.js` edit is needed**: L93 already builds the fragment URL from
   `window.location.pathname`, which is `/s/{token}` in share mode. One whole risk is retired.
4. `tests/conftest.py` carries `reset_env` + `client` only; the done-analysis fixture is a per-file helper
   (`_create_dataset_with_done_analysis` in `tests/test_ui_contract.py`, and similar helpers in
   `tests/test_explorer_routes.py`, `tests/test_analysis_unit.py`). Do not assume a conftest fixture.
5. All forms/links inside the explorer templates use the absolute prefix `/analyses/{{ analysis.id }}/explore`.
   The contract replaces that prefix with one context variable, `explore_path` (see D-A), instead of editing
   twenty call sites individually.

## Owner decisions (Dada, 4 Oct 2026 — quoted, do not re-open)

1. Content: **"Dashboard lengkap 8 tab read-only tanpa unduhan"**.
2. Validity: **"7 hari"**.
3. Protection: **"Link plus password"**.
4. Respondent identity: **"Disembunyikan"**.
5. Scope: **"Satu analisis"**.

## Arc's decisions (numbered; 6-13 were in the brief, 14-19 close what the drafts left open)

6. The shared payload OMITS the identity columns (`PERSON`, and `NAME` when present) rather than blanking them.
7. Token: `new_token()` (32 bytes url-safe); only `hash_token(raw)` is stored; at most one active link per
   analysis; the owner can revoke.
8. Password via the app's own argon2id helpers; never in a URL, a log line, or an error message.
9. Unknown / expired / revoked token answers **404 with `PAGE_NOT_FOUND_MSG`** — never 403.
10. Wrong password re-renders the password page with an Indonesian message (no redirect loop), rate limited.
11. A share session must never satisfy an owner-only route.
12. The shared surface has its own minimal header: title + "hasil dibagikan" marker + theme toggle. No app nav,
    no account link, no link back into the app, no owner-only control.
13. Owner controls live on the dashboard header band of `/analyses/{id}/explore`. No separate management page.
14. **D-A — one path variable.** A new context key `explore_path` = `/analyses/{id}/explore` for the owner and
    `/s/{token}` in share mode. Every in-template absolute link/form action that today reads
    `/analyses/{{ analysis.id }}/explore` becomes `{{ explore_path }}`. Reason: forms are GET forms and the
    guard blocks the owner path from a share session, so the share page must post to itself.
15. **D-B — the session is a stateless cookie**, not a second table: value `hash_token("{token_hash}:{password_hash}")`,
    `HttpOnly; Secure; SameSite=Lax; Path=/s/{token}`, `max_age = expires_at - now`. Revocation and expiry still
    bite because the route looks the link up in the DB on every request. Reason: one table instead of two, no
    session GC, and the password hash is already a per-link secret.
16. **D-C — the guard is an app-level dependency, NOT middleware.** Add `dependencies=[Depends(share_guard)]` to
    the `App(` constructor (L31) and have `share_guard` raise `HTTPException(404, PAGE_NOT_FOUND_MSG)`. Reason: a
    `HTTPException` raised inside `app.middleware("http")` is not translated by the app's exception handlers
    (the handler layer sits inside the middleware stack) and would surface as a 500.
17. **D-D — the shared response is hardened**: `Cache-Control: no-store`, `Referrer-Policy: no-referrer`,
    `X-Robots-Tag: noindex`, on every `/s/` response including its 404s.
18. **D-E — create-link rate limit is per owner** (`share-create:{user.id}`, 20 per hour) next to the per
    (ip, share) password limit (`share:{ip}:{share.id}`, 10 per 900 s). The limiter key uses `share.id`, never
    the raw token, so no token reaches the limiter store.
19. **D-F — the leak suite must include a roster fixture** that carries a `NAME` column and both
    `subsubtes_summary.csv` and `tabulasi_item.csv`, because those tables have never been audited for
    per-respondent rows (opus draft's risk; two other drafts missed it).

## Non-negotiables

- UI copy Indonesian, **zero em dash** (the suite greps for it).
- **Zero new CSS classes.** Pins stay `used == 148` (`tests/test_ui_contract.py:334`) and `defined == 161`
  (same file, next assert). Every class the new markup needs already exists in `app/static/app.css`:
  `btn`, `btn--secondary`, `chip`, `chip--accent`, `field`, `field-label`, `field-hint`, `alert`,
  `alert--misfit`, `alert--info`, `mono`, `header-actions`, `detail-title`, `page-exit`, `band`, `band--header`,
  `action-bar`, `text-link`, `empty`, `empty-text`, `search-bar` (all verified present today).
- The page-template pin moves **13 -> 14** in `tests/test_ui_contract.py:74` in the same run that adds
  `share_password.html`.
- No new dependency. No engine change. No existing table altered.
- The owner's `/analyses/{id}/explore` response stays **byte-identical** except for the new share controls.
- Every writer run: `--mode accept-edits --dangerously-skip-permissions`, prompt from a file, one repo writer
  at a time, and the run reports raw command output (never a claim).

## Measured anchors (verified today, 4 Oct 2026)

- Baseline suite: `.venv/bin/python -m pytest -q` -> **336 passed**, 59 s. HEAD `2c7378a`, tree clean.
- `app/explore.py`: `PAGE_NOT_FOUND_MSG` defined L37; `VIEWS` (8) L54; `router = APIRouter()` L364;
  `get_explore` starts L368; gate + `_current_user` checks L373-385; `raw_view` L400-401;
  `filter_rows(person_data, q_person, (0, 13))` L554; `_clean_audit(person_rows, rekap)` L590;
  `user.id` at L380, L384 (from/to), L440, L444, L473, L523, L639; `context["user"]` L476.
- `app/templates/explore.html`: `band--header` L22, back-link L23, `h1.detail-title` L24, mark POST form L33,
  `<noscript>` L99-103, `action-bar` L120, the three export links L121-123, `page-exit` L210,
  island `<script id="explorer-data">` L212.
- `app/templates/explore/fragment.html`: 11 export anchors (L3, 7, 11, 225, 309, 374, 403, 421, 422, 451, 452;
  keys `butir, responden, bandingkan, ringkasan, opsi, subsubtes` x2, `tabulasi` x2, `tabulasi_butir` x2);
  GET `search-bar`/`compare-strip` forms with the absolute action at L15, 103, 461, 529; "Hapus pencarian" and
  view links at L26, 114, 211, 218, 514.
- `app/templates/base.html`: wordmark anchor `<a href="/" class="wordmark">` L29; nav/account already
  conditional on the account object, so `user=None` removes them.
- `app/export.py`: L244 / L247 already raise 404 with `PAGE_NOT_FOUND_MSG` for an anonymous request, so the
  export route needs **no** edit.
- `app/config.py`: `app_base_url` (default `http://127.0.0.1:7860`, `.rstrip("/")`).
- `app/security.py`: `new_token()` -> `secrets.token_urlsafe(32)`; `hash_token`; `hash_password`/`verify_password`
  (argon2id); `password_policy` = `10 <= len(password) <= 128`; `now_epoch`.
- Alembic: `alembic/versions/` holds `0001_init` .. `0005_analysis_primary`; `.venv/bin/python -m alembic heads`
  prints `0005 (head)`. The venv has no `pip` (use `uv pip install --python .venv/bin/python`).
- `app/main.py`: `class App(FastAPI)` L21, `app = App(` L31, five `include_router` calls L49-53.

## EDIT LIST (runs are sequential; one repo writer at a time)

### W1 — data layer (`app/models.py`, `alembic/versions/0006_analysis_shares.py`)

- Append to `app/models.py`, in the file's existing column style, no existing class touched:
  `class AnalysisShare(Base)` -> `__tablename__ = "analysis_shares"` with `id` PK, `analysis_id` FK
  `analyses.id` `ondelete="CASCADE"`, `user_id` FK `users.id` `ondelete="CASCADE"`, `token_hash`
  `String(64)` `unique=True`, `password_hash` `String`, `created_at` `BigInteger`, `expires_at` `BigInteger`,
  `revoked_at` `BigInteger` nullable; plus a partial unique index `uq_analysis_shares_open` on `analysis_id`
  with `postgresql_where=text("revoked_at IS NULL")` and `sqlite_where=text("revoked_at IS NULL")`.
- New `alembic/versions/0006_analysis_shares.py`, `down_revision = "0005_analysis_primary"`, structured like
  its neighbour: `upgrade()` creates the table + the unique constraint on `token_hash` + the partial index,
  `downgrade()` drops the table. No existing column altered.
- **SELF-VERIFY (paste raw):** `.venv/bin/python -m alembic upgrade head && .venv/bin/python -m alembic current`
  (current = `0006_analysis_shares (head)`) and `.venv/bin/python -m pytest -q` -> **336 passed**.

### W2 — `app/explore.py`, edit 1 of 2 (constants + helpers + `explore_path`)

- Add near L37: `COMPARE_SHARED_MSG = "Perbandingan dengan analisis lain tidak tersedia pada hasil yang dibagikan."`
  and `IDENTITY_HEADERS = ("PERSON", "NAME")`.
- Add `def redact_person_rows(rows):` — returns `(rows_without_identity, dropped_indices)`; find indices by
  header name in BOTH of the first two rows (exact match after `.strip().upper()`); drop those indices from
  every row; **fail closed**: when no `PERSON` header is found, return headers only and no data rows.
- Add `def owner_share_info(db, analysis_id):` -> `None` or `{"expires_label": datetime.fromtimestamp(...).strftime("%Y-%m-%d %H:%M")}`
  for the newest row with `revoked_at IS NULL` (label `"kedaluwarsa"` when `expires_at <= now_epoch()`).
- Add `explore_path` to the context in `get_explore`: `context["explore_path"] = f"/analyses/{analysis.id}/explore"`.
- **SELF-VERIFY (paste raw):** `.venv/bin/python -c "import app.explore as e; print(e.redact_person_rows([['ENTRY','PERSON','NAME','STATUS'],['NUMBER','PERSON','NAME','STATUS'],['1','A1','Budi','kept']]))"`
  must show the identity cells gone and `('1','kept')` remaining, plus `.venv/bin/python -m pytest -q` -> 336.

### W3 — `app/explore.py`, edit 2 of 2 (share-aware render)

- Split `get_explore`: keep gate/user/ownership/stale-run/redirect logic in place; everything from
  `raw_view = ...` (L400) onward moves into `def render_explore(request, db, analysis, dataset, *, user, share=None, extra=None)`.
  `get_explore` then calls it with `share=None`.
- Inside `render_explore`, when `share` is set: `from`/`to` in the query -> `HTTPException(404, PAGE_NOT_FOUND_MSG)`;
  `mark_state=None`, `can_mark=False`, no `_marked_ids` query; `context["user"] = None`;
  `filter_rows(person_data, q_person, (0,))` (no identity column searchable) and person rows pass through
  `redact_person_rows` **before** `paginate`, while `_clean_audit` keeps receiving the ORIGINAL `person_rows`;
  the bandingkan options query is skipped (`options=[]`) and the view shows `COMPARE_SHARED_MSG`;
  `context["explore_path"] = f"/s/{share['token']}"`; context gains `share=share`, `share_mode=True`.
- Owner path: unchanged output plus `owner_share=owner_share_info(db, analysis.id)`, `share_mode=False`,
  `share=None`, `share_new_url=None`, `share_error=None`.
- **SELF-VERIFY (paste raw):** `.venv/bin/python -m pytest -q` -> 336 passed, and the owner page snapshot
  recipe in ACCEPTANCE step 5 diffing empty.

### W4 — `app/share.py` (new: constants, guard, helpers, 4 routes)

- Constants: `SHARE_COOKIE = "raschlab_share"`, `SHARE_TTL_S = 604800`,
  `WRONG_PW_MSG = "Password salah. Coba lagi."`, `TOO_MANY_MSG = "Terlalu banyak percobaan. Coba lagi nanti."`,
  `SHARE_PW_POLICY_MSG = "Password tautan minimal 10 karakter."`,
  `SHARE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"}`.
- `share_guard(request)`: when the `raschlab_share` cookie is present **and** the owner cookie is absent and the
  path is not under `/s/`, `/static/` or `/health` -> `raise HTTPException(404, PAGE_NOT_FOUND_MSG)`.
  Import `COOKIE_NAME` from `app.auth` and `PAGE_NOT_FOUND_MSG` from `app.explore`.
- `share_cookie_value(share)` = `hash_token(f"{share.token_hash}:{share.password_hash}")`;
  `resolve_share(db, raw_token)` -> `(share, analysis, dataset)` or `None` (invalid when revoked, expired,
  analysis not `done`, or owner mismatch).
- Routes on a module-level `router = APIRouter()`:
  - `GET /s/{token}`: no valid share -> 404; cookie mismatch -> 200 `share_password.html` (no filename, no data);
    cookie match -> `render_explore(..., user=None, share={"token": token, "expires_label": ...})`; always add `SHARE_HEADERS`.
  - `POST /s/{token}` (form field `password`): `check_limit(f"share:{client_ip(request)}:{share.id}", 10, 900)`
    BEFORE `verify_password` (argon2 is expensive); over limit -> 429 + `Retry-After`; wrong -> 200 with
    `WRONG_PW_MSG`; correct -> set the share cookie and 303 to `/s/{token}`.
  - `POST /analyses/{id}/share` (owner only, 404 otherwise): `check_limit(f"share-create:{user.id}", 20, 3600)`;
    password must pass `password_policy` (else re-render with `share_error`); revoke every open row for that
    analysis, insert the new row, then render the dashboard once with `share_new_url = f"{settings.app_base_url}/s/{raw}"`
    and `SHARE_HEADERS`.
  - `POST /analyses/{id}/share/revoke` (owner only): set `revoked_at`, 303 to `/analyses/{id}/explore`.
- Nothing logs the token or the password.
- **SELF-VERIFY (paste raw):** `.venv/bin/python -c "import app.share; print(app.share.SHARE_TTL_S)"` -> 604800,
  then `.venv/bin/python -m pytest -q` -> 336.

### W5 — `app/main.py` (guard + router)

- `dependencies=[Depends(share_guard)]` in the `App(` constructor call (L31) and
  `app.include_router(share.router)` next to the five existing includes (L49-53). Imports: `Depends` from
  `fastapi`, `share`, `share_guard` from `app.share`.
- **SELF-VERIFY (paste raw):** `.venv/bin/python -c "from app.main import app; print(sorted({r.path for r in app.routes if r.path.startswith('/s/') or 'share' in r.path}))"`
  lists the three paths, then `.venv/bin/python -m pytest -q` -> 336.

### W6 — templates: `app/templates/explore.html` + `app/templates/base.html`

- `base.html` L29: `{% if share_mode %}<span class="wordmark">{{ dataset.filename }}</span><span class="wordmark-caption">hasil dibagikan</span>{% else %}` + today's anchor + `{% endif %}`. Theme toggle untouched, no tag on its own line that adds whitespace to other pages.
- `explore.html`:
  - L23 back-link, L33 mark form, L99-103 noscript download sentence, L120 `action-bar` (the three export links), L210 `page-exit`: wrap each in `{% if not share %}` (inline tags, so owner HTML keeps its whitespace).
  - In the `band--header` block, owner-only: when `owner_share` is set show `Berlaku hingga {{ owner_share.expires_label }}` + a `Cabut tautan` POST form to `/analyses/{{ analysis.id }}/share/revoke`; when `share_new_url` is set also show a readonly `<input id="share-url" class="mono" value="{{ share_new_url }}" readonly>` + a `Salin tautan` button with `data-copy-target="share-url"` and the hint `Tautan hanya tampil sekali.`; otherwise show the create form (POST `/analyses/{{ analysis.id }}/share`, `type=password` field, `minlength=10`, label `Password tautan`, hint `Berlaku 7 hari. Penerima melihat 8 tab hasil tanpa unduhan dan tanpa nama responden.`, button `Buat tautan bagikan`) and the `share_error` alert (`alert alert--misfit role="alert"`).
  - Share mode: `h1` + `chip chip--accent` `Hasil dibagikan` replacing the owner band content.
- **SELF-VERIFY (paste raw):** `.venv/bin/python -m pytest -q tests/test_ui_contract.py` green, then
  `git diff -- app/templates/explore.html | grep -c '—'` -> 0, then `.venv/bin/python -m pytest -q` -> 336.

### W7 — `app/templates/explore/fragment.html`

- Replace the absolute prefix `/analyses/{{ analysis.id }}/explore` with `{{ explore_path }}` at L15, 26, 103, 114, 211, 218, 461, 514, 529 (forms + links).
- Wrap each of the 11 export anchors (L3, 7, 11, 225, 309, 374, 403, 421, 422, 451, 452) in `{% if not share %}`.
- **SELF-VERIFY (paste raw):** `grep -c 'explore_path' app/templates/explore/fragment.html` -> 9,
  `grep -c 'export?table=' app/templates/explore/fragment.html` -> 11 (all still present, now guarded),
  `.venv/bin/python -m pytest -q` -> 336.

### W8 — `app/templates/share_password.html` (new) + `tests/test_ui_contract.py` pin

- New page extends `base.html`; Indonesian copy: `h1` `Hasil dibagikan`, hint
  `Masukkan password dari pemilik hasil untuk membuka dashboard.`, a form with method post and **no action**
  (posts to the current URL, so the token is never echoed into markup), `type=password` with
  `autocomplete="current-password"`, button `Buka hasil`, and the error in `alert alert--misfit role="alert"`.
  No filename, no analysis data, no `<style>`, existing classes only.
- `tests/test_ui_contract.py:74`: page-template literal `13` -> `14`.
- **SELF-VERIFY (paste raw):** `.venv/bin/python -m pytest -q tests/test_ui_contract.py` green.

### W9 — `app/static/app.js` (copy button only)

- Append a delegated click handler for `[data-copy-target]` that reads the target input's value, calls
  `navigator.clipboard.writeText`, falls back to `input.select()`, and announces `Tautan disalin.` through an
  `aria-live="polite"` region created on first use. **Do not touch `explorer.js`** (L93 already uses
  `window.location.pathname`).
- **SELF-VERIFY (paste raw):** `grep -c 'data-copy-target' app/static/app.js` -> 1, `.venv/bin/python -m pytest -q` -> 336.

### W10 — `tests/test_share.py` (new)

Cases (names literal, one per line in the report):

1. `test_create_returns_url_once_and_stores_only_hashes` — POST as owner -> 200 with `{app_base_url}/s/`, DB row holds sha256 only, raw token in no column.
2. `test_second_create_revokes_the_first` — old token 404, new token gate 200.
3. `test_revoke_answers_404` and `test_non_owner_cannot_create_or_revoke` (404).
4. `test_expiry_and_revocation_with_a_valid_cookie` — monkeypatch `app.share.now_epoch` to `+7 days +1 s`: GET, POST and a previously valid cookie all 404.
5. `test_unknown_token_is_404_not_403` — body equals `PAGE_NOT_FOUND_MSG`.
6. `test_gate_page_carries_no_data` — no dataset filename, no island, no sentinel.
7. `test_wrong_password_renders_gate` — 200, Indonesian message, no `Set-Cookie`.
8. `test_password_rate_limit` — 11th attempt 429 + `Retry-After`, another link unaffected.
9. `test_cookie_flags_and_scope` — HttpOnly, Secure, `Path=/s/{token}`, value != stored hash.
10. `test_all_views_and_fragments_hide_identity` — 8 `?view=` + 7 `?fragment=` responses contain zero roster sentinel (fixture with `NAME` + `subsubtes_summary.csv` + `tabulasi_item.csv` per D-F), `>PERSON<`/`>NAME<` header cells absent on `partisipan`, `>RANK<` present as control, `q_person=<sentinel>` -> count 0.
11. `test_share_session_cannot_reach_owner_routes` — with only the share cookie: every `export?table=` key, `POST mark`, `POST analyze`, `/datasets*`, `/analyses`, `/analyses/{id}`, `/analyses/{id}/explore`, `/account` -> 404; `/s/{token}` and `/static/app.css` stay 200.
12. `test_shared_html_has_no_owner_links` — no `href`/`action` to `/export`, `/datasets`, `/analyses`, `/account`, `/login`, `/logout`, `/`.
13. `test_owner_page_unchanged_but_carries_controls` — owner 200 with the create form; owner + share cookie together still reaches `/analyses`.
14. `test_no_token_or_password_in_logs` — `caplog` clean.
15. Hardening: `Referrer-Policy`, `Cache-Control`, `X-Robots-Tag` present on `/s/` responses.

- **SELF-VERIFY (paste raw):** `.venv/bin/python -m pytest -q tests/test_share.py` -> N passed, then
  `.venv/bin/python -m pytest -q` -> 336 + N.

## ACCEPTANCE (measured, not asserted)

1. `.venv/bin/python -m pytest -q` green with the raw count (baseline **336**).
2. `.venv/bin/python -m pytest -q tests/test_ui_contract.py` green with `used == 148`, `defined == 161`,
   page templates `14`.
3. `grep -rn "—" app/ tests/` empty.
4. `.venv/bin/python -m alembic current` -> `0006_analysis_shares (head)`.
5. Owner page unchanged: snapshot `/analyses/{id}/explore` (all 8 views) before W2 and after W9 and diff;
   only the new share controls may differ.
6. `python3 scripts/page_contrast_probe.py` (Arc runs it) on the share gate, the shared dashboard and the owner
   dashboard: 0 failing passes across 390/1440 x light/dark.
7. Live check after Dada's deploy: create a link on a test analysis, open it logged out in a private window,
   complete the password, verify 8 tabs render, no `PERSON` column, every export link absent, and
   `/health` reports the new commit.

## RISKS

1. A missed `user.id`/`user` dereference in share mode -> 500; the 8-view leak test is the net.
2. Positional reads in `fragment.html` (`row[13]`) would shift after redaction; the grep in W7 checks, and the
   column-name lookups in the tests are the control.
3. The share cookie is `Path`-scoped, so a browser never sends it to owner routes; only a crafted request
   reaches `share_guard`. The guard is defence in depth, not the only control.
4. Refresh of the create response re-posts and rotates the link (accepted trade-off of show-once).
5. `check_limit` is per-process, so limits weaken on multi-instance Cloud Run — pre-existing property of
   login/register limits, unchanged by this feature.
6. Retention deletion of an analysis cascades to `analysis_shares`; an orphan row can only ever 404.

## ROLLBACK

- Code: `git revert <feature commits>` (or `git reset --hard 2c7378a` before any commit).
- Schema, after traffic has moved: `.venv/bin/python -m alembic downgrade 0005_analysis_primary`, which drops
  `analysis_shares` and nothing else.
- Traffic: `gcloud run services update-traffic raschlab-web --region asia-southeast1 --to-revisions raschlab-web-00038-7nm=100`.
- New tables are additive, so the previous revision keeps serving against them without a rollback.
- Emergency, no deploy needed: `UPDATE analysis_shares SET revoked_at = <now> WHERE revoked_at IS NULL;`
  makes every link answer 404 immediately.


---

## VERIFICATION RECORD (Arc, 4 Oct 2026 — measured on the frozen tree)

Baseline before this change: `pytest -q` → 336 passed, HEAD `2c7378a`.

**Suite**: `pytest -q` → **353 passed** (336 baseline + 17 in the new `tests/test_share.py`), no other file's
count moved. `tests/test_ui_contract.py` green with used-classes **148**, defined-classes **161** (zero new
classes) and page templates **14**.

**Mutation checks (each core behaviour broken on purpose, then restored from a /tmp copy with md5 compared)**:

| mutation | expected | measured |
|---|---|---|
| `redact_person_rows` returns rows unchanged | identity leak | `test_all_views_and_fragments_hide_identity` FAILED |
| `dependencies=[Depends(share_guard)]` removed from `App(` | crafted cookie reaches owner routes | `test_share_cookie_cannot_reach_owner_routes` FAILED |
| sort branch reverted to the positional form (both halves) | RANK sorts as text again | `test_all_views_and_fragments_hide_identity` FAILED |

**End-to-end probe driven by Arc before the test file existed** (13 steps, all green): create → gate (no data,
no filename) → wrong password (200, Indonesian message, no cookie) → correct password (303, cookie
`HttpOnly; Secure; Path=/s/{token}`) → 8 views render with zero identity values → fragment fetch on the share
path → crafted share cookie on `/analyses`, `/datasets`, `/account`, `/analyses/{id}`, `/analyses/{id}/explore`
and every export key → 404 each, while `/s/{token}` and `/static/app.css` stay 200 → expiry at +8 days → 404 →
revoke → 404 → owner page never re-shows the token.

**UI gate** (`page_contrast_probe.run_pass` driven through a cookie-carrying context; 4 surfaces × 390/1440 ×
light/dark = 16 passes): 12 failing passes, all from **two** findings which reproduce identically on the
untouched owner dashboard, so neither is a regression of this change:

1. **Contrast ~1.09 in dark mode** — every flagged node sits inside an SVG `<title>` (verified by walking the
   tag chain: `['title','g','g','svg']`). Those are accessible names, never painted. An independent scan over
   painted text nodes only (skipping `title`/`desc`/`defs`/`script`/`style`, zero-size boxes, computing each
   ratio against the first opaque ancestor background) reports **0 failures** on both the shared and the owner
   dashboard. Matches `references/probe-verdicts.md` §1.
2. **`#wright-misfit-toggle` measures 20×20** — real, but **pre-existing**. `app.css` carries the house rule
   `.field--toggle input[type="checkbox"] { appearance: none; flex: 0 0 44px; width: 44px; height: 44px }`,
   the element's parent IS `.field field--toggle`, and `el.matches(selector)` is true; the sizing is overridden
   by a later **ID** rule `#wright-misfit-toggle { inline-size: 20px; block-size: 20px; flex: none }` (app.css
   line 2004, present at HEAD). The 44px row and a 245×44 `label[for]` remain clickable, so the row is usable —
   but the control itself misses the 44px house minimum. Fix is one line (drop the sizing declarations from the
   ID rule) and belongs in its own change-set, not this reviewed diff.

**Hallmark mechanical scan** (`hallmark_mechanical_scan.py` on `share_password.html` + `explore.html`):
**0 critical, 0 major, 1 minor** — the minor is the scanner's source-level "straight quotes in copy" pattern
matching a Jinja string literal, the false-positive class its own header warns about.

**Fixture fidelity**: the leak tests build the person table from `raschlab.report.PERSON_HEADER_ROW_1/2` plus an
appended `NAME` (18+1 columns, the producer's real shape). The repo's older 14-column fixture hid a real defect:
dropping the identity column shifted the template's positional sort branch onto `RANK`, which then sorted as
text. That shift is fixed by the name-based branch in `explore/fragment.html` (owner behaviour unchanged).


## REVIEW ROUND (Arc, 4 Oct 2026) — independent reviewer, different model family (`gpt-6-luna`)

Four findings raised over two rounds, all closed; final delta verdict **NO FINDINGS** with quoted lines.

1. **MEDIUM — invalid-fragment 404 lost the hardening headers.** A shared request with `?fragment=bogus` raised
   `HTTPException` inside `render_explore` before `_harden` ran. Fixed: `get_share` wraps the call and hardens
   every answer. Then a follow-up finding (MEDIUM) — **a non-`HTTPException` render failure** (malformed
   `analysis.params_json` → `JSONDecodeError`) produced an unhardened framework 500 — closed by catching
   `Exception`, logging with `logger.exception` and returning a hardened 500 carrying `SERVER_ERROR_MSG`.
2. **LOW — the owner's PERSON sort control vanished.** The `{% set h1 = col | trim %}` line had moved INSIDE the
   `{% if %}` block during the W7b re-apply, and `data-sort` still used the positional `loop.index0 == 13`.
   Regression inside this change-set, invisible to the tests because the shared page has no `PERSON` column at
   all. Fixed, plus a new owner-side regression test (one text sort, six controls). Sortable set verified
   unchanged for the owner: `{0, 3, 4, 5, 7}` plus the `PERSON` position.
3. **LOW — test gaps.** The expiry boundary was never asserted at exactly `expires_at`, and the unknown-token
   test checked presence of the message rather than the exact body. Both tightened; a mutation (`<=` → `<`)
   makes the boundary test fail.

**Mutating what the tests claim to cover** (each restored from a copy, md5 compared): identity redaction
disabled → RED · guard dependency removed → RED · sort branch reverted (both halves) → RED · `expires_at <= now`
→ `<` → RED · `_harden` dropped from the 500 branch → RED.

**Two self-inflicted process failures, recorded so they are not repeated.** (a) A mutation script restored
`app/templates/explore/fragment.html` with `git checkout --`, which discarded the whole uncommitted change-set
for that file (9 rewritten links, 11 guards). (b) A later script restored `app/share.py` from a copy taken BEFORE
the writer run that added the fix, removing the fix, and the same script then committed that reduced file; the
delta review dispatched next saw only a one-file diff (the test) and legitimately answered `NO FINDINGS` about a
product change it never saw. Both were caught by the suite/verification and repaired in `d1c2241`; nothing left
the branch. The rules that now live in `agy-build-pipeline/references/run-discipline.md`: restore from a copy
taken AFTER the change you mean to keep, grep the markers and run the FULL suite between the restore and the
commit, and confirm `files=$(grep -c '^diff --git' <diff>)` covers every file a fix touched before handing a
delta to a reviewer.
