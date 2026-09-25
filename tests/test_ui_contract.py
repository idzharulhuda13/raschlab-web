"""UI contract tests for RaschLab Web design system (Phase F2.5).

Verifies limits, tokens, transitions, accessibility, theme toggle, contrast ratios,
and template class inventory without network or external services.
"""

import datetime
import json
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.auth import COOKIE_NAME
from app.db import SessionLocal
from app.models import Analysis, Dataset, SessionRow, User
from app.security import hash_password, hash_token, new_token, now_epoch
from app.storage import MAX_CELLS, MAX_UPLOAD_BYTES
from app.ui import initials_for


def _create_authenticated_user(client: TestClient, email: str = "contract_tester@example.test") -> int:
    with SessionLocal() as db:
        now = now_epoch()
        user = User(
            email=email,
            email_normalized=email.lower().strip(),
            password_hash=hash_password("katasandi-ui-contract"),
            created_at=now,
            verified_at=now,
        )
        db.add(user)
        db.commit()
        user_id = user.id

        token = new_token()
        session_row = SessionRow(
            user_id=user_id,
            token_hash=hash_token(token),
            created_at=now,
            expires_at=now + 86400 * 30,
        )
        db.add(session_row)
        db.commit()

    client.cookies.set(COOKIE_NAME, token)
    return user_id


def test_upload_page_states_both_limits_from_constants(client: TestClient):
    _create_authenticated_user(client)
    resp = client.get("/datasets")
    assert resp.status_code == 200

    mb = str(MAX_UPLOAD_BYTES // (1024 * 1024)) + " MB"
    cells = f"{MAX_CELLS:,}".replace(",", ".") + " sel"

    assert mb in resp.text
    assert cells in resp.text


def test_no_style_blocks_in_any_template():
    templates_dir = Path("app/templates")
    if not templates_dir.exists():
        pytest.fail("app/templates directory not found")

    for html_file in templates_dir.rglob("*.html"):
        content = html_file.read_text()
        assert "<style" not in content, f"<style tag found in {html_file}"

    page_templates = list(templates_dir.glob("*.html"))
    assert len(page_templates) == 12, f"Expected 12 page templates directly under app/templates, found {len(page_templates)}"
    for html_file in page_templates:
        content = html_file.read_text()
        assert 'style="' not in content, f'style=" attribute found in page template {html_file}'


def test_retired_names_and_token_contract():
    retired_strings = [
        "--raised",
        "--rule",
        "--scale",
        "--step-13",
        "--step-20",
        "--step-24",
        "--step-32",
        "--step-44",
        "tick-rule",
    ]

    for html_file in Path("app/templates").rglob("*.html"):
        content = html_file.read_text()
        for retired in retired_strings:
            assert retired not in content, f"Retired string {retired} found in {html_file}"

    for static_file in [Path("app/static/tokens.css"), Path("app/static/app.css"), Path("app/static/app.js")]:
        if not static_file.exists():
            pytest.fail(f"Static file {static_file} missing")
        content = static_file.read_text()
        for retired in retired_strings:
            assert retired not in content, f"Retired string {retired} found in {static_file}"

    tokens_css = Path("app/static/tokens.css").read_text()
    required_tokens = [
        "--paper",
        "--surface",
        "--surface-2",
        "--ink",
        "--muted",
        "--line",
        "--control",
        "--accent",
        "--accent-soft",
        "--fit",
        "--warn",
        "--misfit",
        "--font-ui",
        "--font-mono",
        "--step-12",
        "--step-14",
        "--step-16",
        "--step-18",
        "--step-22",
        "--step-28",
        "--step-40",
        "--step-56",
        "--space-1",
        "--space-2",
        "--space-3",
        "--space-4",
        "--space-6",
        "--space-8",
        "--space-12",
        "--space-16",
        "--space-24",
        "--radius-sm",
        "--radius-md",
        "--radius-lg",
        "--shadow-1",
        "--shadow-2",
        "--dur-1",
        "--dur-2",
        "--dur-3",
        "--band-h",
        "--shell-max",
    ]
    assert len(required_tokens) == 41
    for token in required_tokens:
        assert token in tokens_css, f"Required token {token} missing from tokens.css"

    app_css = Path("app/static/app.css").read_text()
    assert "96px" not in app_css, "Raw literal 96px found in app.css"

    for html_file in Path("app/templates").glob("*.html"):
        content = html_file.read_text()
        assert "96px" not in content, f"Raw literal 96px found in page template {html_file}"


def test_reduced_motion_covers_every_transition():
    app_css_path = Path("app/static/app.css")
    if not app_css_path.exists():
        pytest.fail("app/static/app.css missing")
    css = app_css_path.read_text()
    css_stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    assert "prefers-reduced-motion" in css_stripped
    assert "@keyframes" not in css_stripped

    parts = re.split(r"@media[^{]*prefers-reduced-motion[^{]*\{", css_stripped)
    assert len(parts) >= 2, "Could not find prefers-reduced-motion block in app.css"

    outside = parts[0]
    inside = parts[1]

    outside_count = outside.count("transition")
    inside_count = inside.count("transition")

    assert outside_count >= 1, f"Expected at least 1 transition outside reduce block, found {outside_count}"
    assert inside_count >= outside_count, f"Expected inside count ({inside_count}) >= outside count ({outside_count})"


def test_theme_toggle_markup_and_mechanism(client: TestClient):
    resp = client.get("/login")
    assert resp.status_code == 200
    html = resp.text

    button_match = re.search(r'<button\b[^>]*id=["\']theme-toggle["\'][^>]*>', html)
    assert button_match is not None, "Button with id='theme-toggle' not found in /login"
    assert "aria-label=" in button_match.group(0), "theme-toggle button missing aria-label attribute"

    js_path = Path("app/static/app.js")
    if not js_path.exists():
        pytest.fail("app/static/app.js missing")
    js = js_path.read_text()
    assert "rl_theme" in js, "rl_theme missing from app.js"
    assert "aria-label" in js, "aria-label missing from app.js"
    assert "dataset.theme" in js or "data-theme" in js, "theme attribute mechanism missing from app.js"

    tokens_path = Path("app/static/tokens.css")
    if not tokens_path.exists():
        pytest.fail("app/static/tokens.css missing")
    tokens = tokens_path.read_text()
    assert '[data-theme="dark"]' in tokens, '[data-theme="dark"] selector missing from tokens.css'
    assert "@media (prefers-color-scheme: dark)" in tokens or "prefers-color-scheme: dark" in tokens, "prefers-color-scheme: dark media query missing from tokens.css"
    assert ':root:not([data-theme="light"])' in tokens, ':root:not([data-theme="light"]) missing from tokens.css'

    base_path = Path("app/templates/base.html")
    if not base_path.exists():
        pytest.fail("app/templates/base.html missing")
    base = base_path.read_text()
    assert re.search(r'<script\b[^>]*src=["\']/static/app\.js["\'][^>]*defer', base) or re.search(r'<script\b[^>]*defer[^>]*src=["\']/static/app\.js["\']', base), "base.html does not link /static/app.js with defer"


def test_contrast_both_themes_computed_from_tokens():
    tokens_path = Path("app/static/tokens.css")
    if not tokens_path.exists():
        pytest.fail("app/static/tokens.css missing")
    content = tokens_path.read_text()

    root_match = re.search(r':root\s*\{([^}]*)\}', content)
    dark_match = re.search(r'\[data-theme=["\']dark["\']\]\s*\{([^}]*)\}', content)
    if not root_match or not dark_match:
        pytest.fail("Could not find light and dark token blocks in tokens.css")

    def parse_tokens(block: str) -> dict[str, str]:
        tokens: dict[str, str] = {}
        for line in block.splitlines():
            line = line.strip()
            m = re.match(r'--([\w-]+):\s*(#[0-9a-fA-F]{6});', line)
            if m:
                tokens[m.group(1)] = m.group(2)
        return tokens

    light_tokens = parse_tokens(root_match.group(1))
    dark_tokens = parse_tokens(dark_match.group(1))

    def rel_luminance(hex_str: str) -> float:
        hex_str = hex_str.lstrip("#")
        r = int(hex_str[0:2], 16) / 255.0
        g = int(hex_str[2:4], 16) / 255.0
        b = int(hex_str[4:6], 16) / 255.0

        def channel(c: float) -> float:
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    def contrast_ratio(hex1: str, hex2: str) -> float:
        l1 = rel_luminance(hex1)
        l2 = rel_luminance(hex2)
        lighter = max(l1, l2)
        darker = min(l1, l2)
        return (lighter + 0.05) / (darker + 0.05)

    pairs_45 = [
        ("ink", "paper"),
        ("ink", "surface"),
        ("ink", "surface-2"),
        ("muted", "paper"),
        ("muted", "surface"),
        ("muted", "surface-2"),
        ("accent", "paper"),
        ("accent", "surface"),
        ("accent", "surface-2"),
        ("fit", "surface"),
        ("warn", "surface"),
        ("misfit", "surface"),
        ("fit", "surface-2"),
        ("warn", "surface-2"),
        ("misfit", "surface-2"),
        ("ink", "accent-soft"),
        ("paper", "accent"),
    ]

    pairs_30 = [
        ("control", "paper"),
        ("control", "surface"),
    ]

    for theme_name, tokens in [("light", light_tokens), ("dark", dark_tokens)]:
        for fg, bg in pairs_45:
            assert fg in tokens and bg in tokens, f"Token pair {fg}/{bg} missing in {theme_name}"
            cr = contrast_ratio(tokens[fg], tokens[bg])
            assert cr >= 4.5, f"{theme_name} theme: {fg}/{bg} contrast ratio {cr:.2f} is below 4.5"
        for fg, bg in pairs_30:
            assert fg in tokens and bg in tokens, f"Token pair {fg}/{bg} missing in {theme_name}"
            cr = contrast_ratio(tokens[fg], tokens[bg])
            assert cr >= 3.0, f"{theme_name} theme: {fg}/{bg} contrast ratio {cr:.2f} is below 3.0"


def test_all_template_classes_defined_in_app_css():
    app_css_path = Path("app/static/app.css")
    if not app_css_path.exists():
        pytest.fail("app/static/app.css missing")
    css_text = app_css_path.read_text()
    defined_classes = set(re.findall(r"\.([A-Za-z][\w-]*)", css_text))

    used_classes: set[str] = set()
    templates_dir = Path("app/templates")
    if not templates_dir.exists():
        pytest.fail("app/templates missing")

    for html_file in templates_dir.rglob("*.html"):
        content = html_file.read_text()
        for m in re.finditer(r'class="([^"]*)"', content):
            attr = m.group(1)
            attr_cleaned = re.sub(r"\{%.*?%\}|\{\{.*?\}\}", " ", attr)
            tokens = [t for t in attr_cleaned.split() if re.fullmatch(r"[A-Za-z][\w-]*", t)]
            used_classes.update(tokens)

    undefined = used_classes - defined_classes
    assert not undefined, f"Used classes not defined in app.css: {sorted(undefined)}"

    # Measured with the exact logic above: 134 distinct classes are used across
    # app/templates/**/*.html (now including the explorer templates) and 148 classes
    # are defined in app/static/app.css (now including the F4 explorer section).
    # Pinning both numbers makes adding or dropping a class a deliberate act.
    # 136: the partisipan histogram added .chart-block and .chart-caption, both defined in app.css and
    # both carrying contract meaning, so the count moves with them on purpose.
    # 142 / 156 (F9: readability, placement, navigation): action-bar, action-group--danger, danger-gap, page-exit, text-link, cmp-filter.
    assert len(used_classes) == 142, f"Used template class count changed to {len(used_classes)}"
    assert len(defined_classes) == 156, f"Defined app.css class count changed to {len(defined_classes)}"


def _create_dataset_with_done_analysis(user_id: int, filename: str = "matriks_ujian.csv") -> tuple[int, int]:
    """Insert one Dataset and one completed Analysis row for the given user."""
    now = now_epoch()
    with SessionLocal() as db:
        dataset = Dataset(
            user_id=user_id,
            filename=filename,
            kind="dikotomus",
            format="wide",
            status="committed",
            n_persons=300,
            n_items=40,
            item_labels_json=json.dumps([f"I{i}" for i in range(40)]),
            mapping_json=json.dumps({"correct": ["1"], "incorrect": ["0"]}),
            summary_json=json.dumps({"n_persons": 300, "n_items": 40}),
            raw_gzip=b"prn,item\n",
            raw_bytes=10,
            created_at=now,
            committed_at=now,
        )
        db.add(dataset)
        db.commit()
        dataset_id = dataset.id

        analysis = Analysis(
            user_id=user_id,
            dataset_id=dataset_id,
            status="done",
            params_json=json.dumps({"mode": "compat"}),
            engine_ref="raschlab-engine-test",
            created_at=now,
            started_at=now,
            finished_at=now,
            expires_at=now + 180 * 86400,
        )
        db.add(analysis)
        db.commit()
        analysis_id = analysis.id

    return dataset_id, analysis_id


def _create_dataset_with_analysis(
    user_id: int, filename: str, status: str, created_at: int | None = None
) -> tuple[int, int]:
    """Insert one Dataset and one Analysis row with the given status."""
    when = now_epoch() if created_at is None else created_at
    with SessionLocal() as db:
        dataset = Dataset(
            user_id=user_id,
            filename=filename,
            kind="dikotomus",
            format="wide",
            status="committed",
            n_persons=300,
            n_items=40,
            item_labels_json=json.dumps([f"I{i}" for i in range(40)]),
            mapping_json=json.dumps({"correct": ["1"], "incorrect": ["0"]}),
            summary_json=json.dumps({"n_persons": 300, "n_items": 40}),
            raw_gzip=b"prn,item\n",
            raw_bytes=10,
            created_at=when,
            committed_at=when,
        )
        db.add(dataset)
        db.commit()
        dataset_id = dataset.id

        analysis = Analysis(
            user_id=user_id,
            dataset_id=dataset_id,
            status=status,
            params_json=json.dumps({"mode": "compat"}),
            engine_ref="raschlab-engine-test",
            created_at=when,
            started_at=when,
            finished_at=when,
            expires_at=when + 180 * 86400,
        )
        db.add(analysis)
        db.commit()
        analysis_id = analysis.id

    return dataset_id, analysis_id


def _insert_cross_owner_analysis(user_id: int, dataset_id: int, created_at: int) -> int:
    """Insert the deliberately corrupt row: user_id and dataset_id disagree.

    The write path cannot produce this (an analysis is always created for the
    owner of its dataset); it exists only to prove the read path does not trust
    Analysis.user_id on its own.
    """
    with SessionLocal() as db:
        analysis = Analysis(
            user_id=user_id,
            dataset_id=dataset_id,
            status="queued",
            params_json=json.dumps({"mode": "compat"}),
            engine_ref="raschlab-engine-test",
            created_at=created_at,
            expires_at=created_at + 180 * 86400,
        )
        db.add(analysis)
        db.commit()
        analysis_id = analysis.id

    return analysis_id


def test_signed_in_login_and_register_redirect_to_datasets(client: TestClient):
    _create_authenticated_user(client, email="sudahmasuk@example.test")

    login_resp = client.get("/login", follow_redirects=False)
    assert login_resp.status_code == 303
    assert login_resp.headers["location"] == "/datasets"

    register_resp = client.get("/register", follow_redirects=False)
    assert register_resp.status_code == 303
    assert register_resp.headers["location"] == "/datasets"


def test_account_template_band_composition_contract():
    account_template = Path("app/templates/account.html").read_text()

    # The auth-form band must not come back to a content page.
    assert "band--narrow" not in account_template
    # Two summary columns inside the single full-width panel, one large avatar.
    assert account_template.count("summary-col") == 2
    assert account_template.count("acct-avatar--lg") == 1


def test_account_empty_state_copy_without_figures(client: TestClient):
    _create_authenticated_user(client, email="kosong@example.test")

    resp = client.get("/account")
    assert resp.status_code == 200
    html = resp.text

    assert "Belum ada berkas" in html
    assert "Belum ada analisis" in html
    # No counts means no summary figure at all.
    assert "summary-figure" not in html

    # account.html prints the constants-derived limits paragraph in both states,
    # so the empty account page carries it too, not only /datasets.
    mb = f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
    cells = f"{MAX_CELLS:,}".replace(",", ".") + " sel"
    assert f"Maksimal {mb} per berkas dan {cells} per dataset." in html

    datasets_resp = client.get("/datasets")
    assert datasets_resp.status_code == 200
    assert mb in datasets_resp.text
    assert cells in datasets_resp.text


def test_account_populated_state_shows_counts_limits_and_last_analysis(client: TestClient):
    user_id = _create_authenticated_user(client, email="terisi@example.test")
    _dataset_id, analysis_id = _create_dataset_with_done_analysis(user_id)

    resp = client.get("/account")
    assert resp.status_code == 200
    html = resp.text

    # Exactly one dataset and one analysis: both figures render with count 1.
    assert '<span class="mono">1</span> <span class="section-text">berkas tersimpan</span>' in html
    assert '<span class="mono">1</span> <span class="section-text">analisis tersimpan</span>' in html

    # Limits copy built from the constants.
    mb = f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
    cells = f"{MAX_CELLS:,}".replace(",", ".") + " sel"
    assert mb in html
    assert cells in html

    with SessionLocal() as db:
        created_at = db.scalar(select(Analysis.created_at).where(Analysis.id == analysis_id))
    expected_date = datetime.datetime.fromtimestamp(created_at).strftime("%Y-%m-%d")

    assert expected_date in html
    assert "matriks_ujian.csv" in html
    assert "Selesai" in html
    assert f'href="/analyses/{analysis_id}"' in html


def test_account_avatar_renders_two_initials(client: TestClient):
    _create_authenticated_user(client, email="idzharul.huda@gmail.com")

    resp = client.get("/account")
    assert resp.status_code == 200
    html = resp.text

    # Two initials, never a single letter: the app-shell avatar and the
    # account band avatar must both render IH for idzharul.huda@gmail.com.
    assert '<span class="acct-avatar">IH</span>' in html
    assert 'acct-avatar--lg">IH<' in html


@pytest.mark.parametrize(
    "account, expected",
    [
        ("idzharul.huda@gmail.com", "IH"),
        ("budi_santoso@x.id", "BS"),
        ("siti-aminah@x.id", "SA"),
        ("solo@gmail.com", "SO"),
        ("probe@local.test", "PR"),
        ("a@b.co", "A"),
        ("x_y_z@a.b", "XY"),
        ("@example.com", "E"),
        (".@x.id", "X"),
        ("x@y", "X"),
        (None, ""),
        ("", ""),
    ],
)
def test_initials_for_verified_cases(account, expected):
    result = initials_for(account)
    assert result == expected, f"initials_for({account!r}) returned {result!r}, expected {expected!r}"
    assert len(result) <= 2, f"initials_for({account!r}) returned more than two characters: {result!r}"


def test_initials_for_never_raises_and_never_exceeds_two_characters():
    adversarial_inputs = [
        "idzharul.huda@gmail.com",
        "budi_santoso@x.id",
        "siti-aminah@x.id",
        "solo@gmail.com",
        "probe@local.test",
        "a@b.co",
        "x_y_z@a.b",
        "@example.com",
        ".@x.id",
        "x@y",
        None,
        "",
        "   ",
        "@",
        ".",
        "-",
        "1.2@3.4",
        "  spaced@x.id  ",
    ]
    for account in adversarial_inputs:
        result: str | None = None
        try:
            result = initials_for(account)
        except Exception as exc:  # pragma: no cover - only on regression
            pytest.fail(f"initials_for({account!r}) raised {exc!r}")
        assert isinstance(result, str), f"initials_for({account!r}) returned a non-string {result!r}"
        assert len(result) <= 2, f"initials_for({account!r}) returned more than two characters: {result!r}"


def test_account_queued_analysis_shows_queue_chip_not_failure(client: TestClient):
    user_id = _create_authenticated_user(client, email="antrean@example.test")
    _create_dataset_with_analysis(user_id, filename="matriks_antrean.csv", status="queued")

    resp = client.get("/account")
    assert resp.status_code == 200
    html = resp.text

    assert "matriks_antrean.csv" in html
    assert "Dalam antrean" in html
    # A queued run is on the queue, never a failure: the chip copy must not
    # accuse it of failing.
    assert "Gagal" not in html


def test_account_last_analysis_ignores_cross_owner_row(client: TestClient):
    owner_a = _create_authenticated_user(client, email="pemilik.a@example.test")
    _create_dataset_with_analysis(owner_a, filename="berkas_milik_a.csv", status="done")

    # Owner B owns a dataset that A must never see. B is inserted straight into
    # the database so the helper does not clobber A's session cookie.
    now = now_epoch()
    with SessionLocal() as db:
        owner_b = User(
            email="pemilik.b@example.test",
            email_normalized="pemilik.b@example.test",
            password_hash=hash_password("katasandi-ui-contract"),
            created_at=now,
            verified_at=now,
        )
        db.add(owner_b)
        db.commit()

        dataset_b = Dataset(
            user_id=owner_b.id,
            filename="rahasia_milik_b.csv",
            kind="dikotomus",
            format="wide",
            status="committed",
            n_persons=300,
            n_items=40,
            item_labels_json=json.dumps([f"I{i}" for i in range(40)]),
            mapping_json=json.dumps({"correct": ["1"], "incorrect": ["0"]}),
            summary_json=json.dumps({"n_persons": 300, "n_items": 40}),
            raw_gzip=b"prn,item\n",
            raw_bytes=10,
            created_at=now,
            committed_at=now,
        )
        db.add(dataset_b)
        db.commit()
        dataset_b_id = dataset_b.id

    # Deliberately corrupt row: user_id says A, dataset_id says B, and it is
    # newer than A's own row, so a read path trusting Analysis.user_id alone
    # would surface B's filename and its queued status on A's page.
    _insert_cross_owner_analysis(owner_a, dataset_b_id, created_at=now_epoch() + 60)

    resp = client.get("/account")
    assert resp.status_code == 200
    html = resp.text

    assert "rahasia_milik_b.csv" not in html
    assert "Dalam antrean" not in html
    assert "berkas_milik_a.csv" in html
    assert "Selesai" in html

    # The figure next to the analysis label must count exactly one run: A's own.
    # The corrupt cross-owner row must never inflate it to two.
    assert (
        '<span class="mono">1</span> '
        '<span class="section-text">analisis tersimpan</span>'
    ) in html
    assert (
        '<span class="mono">2</span> '
        '<span class="section-text">analisis tersimpan</span>'
    ) not in html
