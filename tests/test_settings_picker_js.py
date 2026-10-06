"""Playwright browser tests locking the participant picker client-side behavior.

Phase F22 item 5.
"""
from __future__ import annotations

import pathlib
import re

from fastapi.testclient import TestClient
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import tests.test_settings_picker as T


def _inline_assets(html: str) -> str:
    root = pathlib.Path(__file__).resolve().parent.parent
    static = root / "app" / "static"
    css = "\n".join((static / name).read_text(encoding="utf-8") for name in ("tokens.css", "app.css"))
    js = "\n".join(
        (static / name).read_text(encoding="utf-8")
        for name in ("app.js", "settings-presets.js", "settings-picker.js")
    )

    html = re.sub(r'\s*<link rel="stylesheet" href="https://fonts\.googleapis\.com[^>]*>', "", html)
    html = re.sub(r'\s*<link rel="stylesheet" href="/static/tokens\.css">', "", html)
    html = re.sub(r'\s*<link rel="stylesheet" href="/static/app\.css">', "", html)
    html = re.sub(r'\s*<script src="/static/app\.js" defer></script>', "", html)
    html = re.sub(r'\s*<script src="/static/settings-presets\.js" defer></script>', "", html)
    html = re.sub(r'\s*<script src="/static/settings-picker\.js" defer></script>', "", html)
    inline = f"<style>\n{css}\n</style>\n<script>\n{js}\n</script>\n"
    return html.replace("</head>", inline + "</head>", 1)


def test_participant_rows_built_by_javascript(client: TestClient, tmp_path: pathlib.Path):
    T._create_authenticated_user(client)
    dataset_id = T._upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert resp.status_code == 200
    html = _inline_assets(resp.text)

    html_file = tmp_path / "settings.html"
    html_file.write_text(html, encoding="utf-8")

    intercepted_requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def handle_route(route, request):
            intercepted_requests.append(request)
            route.fulfill(status=200, body="OK")

        page.route("**/analyze", handle_route)

        page.goto(html_file.as_uri())

        # Wait for the participant rows to be built
        page.wait_for_selector('#pd-picker input[name="pd_pick"]')

        # Assert participant list produced one checkbox per person with name="pd_pick"
        pd_checkboxes = page.locator('#pd-picker input[name="pd_pick"]')
        assert pd_checkboxes.count() == 300

        # Assert matching population label (P0001 for person 1)
        first_row = page.locator('#pd-picker .pick-row').first
        assert "P0001" in first_row.inner_text()
        assert "1" in first_row.inner_text()

        # Tick two rows (index 1 is person 2, index 4 is person 5)
        pd_checkboxes.nth(1).check()
        pd_checkboxes.nth(4).check()
        assert pd_checkboxes.nth(1).is_checked()
        assert pd_checkboxes.nth(4).is_checked()

        # Set one anchor value in the item list
        anchor_input = page.locator('input[name="anchor_value"]').first
        anchor_input.fill("1.25")

        # Click submit
        page.locator('form.upload-form button[type="submit"]').click()

        browser.close()

    assert len(intercepted_requests) == 1
    req = intercepted_requests[0]
    assert req.method == "POST"
    post_data = req.post_data
    assert post_data is not None

    # Assert request carries pd_pick twice
    assert post_data.count('name="pd_pick"') == 2
    assert re.search(r'name="pd_pick"\r?\n\r?\n2\b', post_data) is not None
    assert re.search(r'name="pd_pick"\r?\n\r?\n5\b', post_data) is not None

    # Assert anchor pair (pos 1, value 1.25)
    assert re.search(r'name="anchor_pos"\r?\n\r?\n1\b', post_data) is not None
    assert re.search(r'name="anchor_value"\r?\n\r?\n1\.25\b', post_data) is not None


def test_rejected_settings_restore_participants_in_browser(client: TestClient, tmp_path: pathlib.Path):
    T._create_authenticated_user(client)
    dataset_id = T._upload_and_commit_sample(client)

    resp = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={
            "misfit": "-1",
            "pd_pick": ["2", "5"],
            "id_pick": ["1"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422
    html = _inline_assets(resp.text)

    html_file = tmp_path / "settings_restore.html"
    html_file.write_text(html, encoding="utf-8")

    intercepted_requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def handle_route(route, request):
            intercepted_requests.append(request)
            route.fulfill(status=200, body="OK")

        page.route("**/analyze", handle_route)

        page.goto(html_file.as_uri())

        page.wait_for_selector('#pd-picker input[name="pd_pick"]')

        pd_checkboxes = page.locator('#pd-picker input[name="pd_pick"]')
        assert pd_checkboxes.count() == 300

        assert page.locator('#pd-picker input[name="pd_pick"][value="2"]').is_checked()
        assert page.locator('#pd-picker input[name="pd_pick"][value="5"]').is_checked()
        checked_boxes = page.locator('#pd-picker input[name="pd_pick"]:checked')
        assert checked_boxes.count() == 2

        page.locator('#pd-picker input[name="pd_pick"][value="2"]').uncheck()
        assert not page.locator('#pd-picker input[name="pd_pick"][value="2"]').is_checked()

        page.locator('#misfit').fill("1.50")
        page.locator('form.upload-form button[type="submit"]').click()

        browser.close()

    assert len(intercepted_requests) == 1
    req = intercepted_requests[0]
    assert req.method == "POST"
    post_data = req.post_data
    assert post_data is not None

    assert post_data.count('name="pd_pick"') == 1
    assert re.search(r'name="pd_pick"\r?\n\r?\n5\b', post_data) is not None
    assert re.search(r'name="pd_pick"\r?\n\r?\n2\b', post_data) is None

