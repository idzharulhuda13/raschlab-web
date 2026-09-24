"""UI contract tests for RaschLab Web design system (Phase F2.5).

Verifies limits, tokens, transitions, accessibility, theme toggle, contrast ratios,
and template class inventory without network or external services.
"""

from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

from app.auth import COOKIE_NAME
from app.db import SessionLocal
from app.models import SessionRow, User
from app.security import hash_password, hash_token, new_token, now_epoch
from app.storage import MAX_CELLS, MAX_UPLOAD_BYTES


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
    assert len(page_templates) == 10, f"Expected 10 page templates directly under app/templates, found {len(page_templates)}"
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
