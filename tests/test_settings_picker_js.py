"""Playwright browser tests locking the picker dialog, search, and carrier synchronization.

Phase F22 item 5 (R3).
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


def _load_settings_page(page, html_file: pathlib.Path, client: TestClient, intercepted_posts: list | None = None, picker_requests: list | None = None):
    def handle_route(route, request):
        url = request.url
        if url.endswith("/settings.html") or url.endswith("/page"):
            route.fulfill(
                status=200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                body=html_file.read_text(encoding="utf-8"),
            )
        elif "/picker" in url:
            if picker_requests is not None:
                picker_requests.append(url)
            m = re.search(r"(/datasets/\d+/picker\??.*)", url)
            path_and_query = m.group(1) if m else url
            r = client.get(path_and_query)
            route.fulfill(
                status=r.status_code,
                headers={"Content-Type": "application/json"},
                body=r.content,
            )
        elif "/analyze" in url:
            if intercepted_posts is not None:
                intercepted_posts.append(request)
            route.fulfill(status=200, body="OK")
        else:
            route.continue_()

    page.route("http://app.test/**", handle_route)
    page.goto("http://app.test/settings.html")


def test_picker_results_bounded_and_search_query_forwarded(client: TestClient, tmp_path: pathlib.Path):
    T._create_authenticated_user(client)
    dataset_id = T._upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert resp.status_code == 200
    html = _inline_assets(resp.text)

    html_file = tmp_path / "settings.html"
    html_file.write_text(html, encoding="utf-8")

    picker_requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        _load_settings_page(page, html_file, client, picker_requests=picker_requests)

        # Click open button for persons
        page.locator('.pick-open[data-kind="persons"]').click()

        # Wait for dialog and first page of results
        page.wait_for_selector('#picker-results .pick-row')
        rows = page.locator('#picker-results .pick-row')
        # 1. with a 300-person fixture, #picker-results children <= 5 after opening
        assert rows.count() <= 5
        assert rows.count() == 5

        # Check status says "5 dari 300"
        status_text = page.locator('#picker-status').inner_text()
        assert "5 dari 300" in status_text

        # Type search query
        page.locator('#picker-search').fill("001")
        # Wait for debounce and network request to complete
        page.wait_for_timeout(300)
        page.wait_for_selector('#picker-results .pick-row')

        # 2. #picker-results children <= 5 after typing a query
        rows_after_query = page.locator('#picker-results .pick-row')
        assert rows_after_query.count() <= 5

        # 3. Search request carries typed `q` and right `kind`
        search_urls = [u for u in picker_requests if "q=001" in u]
        assert len(search_urls) >= 1
        assert "kind=persons" in search_urls[0]

        browser.close()


def test_select_rows_writes_carriers_and_summary_and_remove_chip(client: TestClient, tmp_path: pathlib.Path):
    T._create_authenticated_user(client)
    dataset_id = T._upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert resp.status_code == 200
    html = _inline_assets(resp.text)

    html_file = tmp_path / "settings_select.html"
    html_file.write_text(html, encoding="utf-8")

    intercepted_posts = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        _load_settings_page(page, html_file, client, intercepted_posts=intercepted_posts)

        # Open persons picker
        page.locator('.pick-open[data-kind="persons"]').click()
        page.wait_for_selector('#picker-results .pick-row')

        # Select two rows (checkbox in row 1 and row 2)
        checkboxes = page.locator('#picker-results .pick-row input[type="checkbox"]')
        checkboxes.nth(0).check()
        checkboxes.nth(1).check()

        # Summary reads "2 dipilih"
        summary = page.locator('.pick-summary[data-summary="persons"]')
        assert summary.inner_text() == "2 dipilih"

        # Exactly two pd_pick carriers
        carriers = page.locator('#picker-carriers input[name="pd_pick"]')
        assert carriers.count() == 2
        assert page.locator('#picker-carriers input[name="pd_pick"][value="1"]').count() == 1
        assert page.locator('#picker-carriers input[name="pd_pick"][value="2"]').count() == 1

        # Check chips in dialog
        chips = page.locator('#picker-chosen .chip')
        assert chips.count() == 2

        # Removing a chip removes its carrier
        chip_remove_btn = page.locator('#picker-chosen .chip[data-pos="1"] .chip-remove')
        chip_remove_btn.click()

        # Now only 1 carrier remains
        carriers_after = page.locator('#picker-carriers input[name="pd_pick"]')
        assert carriers_after.count() == 1
        assert page.locator('#picker-carriers input[name="pd_pick"][value="2"]').count() == 1
        assert summary.inner_text() == "1 dipilih"

        # Checkbox for pos 1 is now unchecked
        assert not checkboxes.nth(0).is_checked()

        browser.close()


def test_escape_closes_dialog_and_returns_focus_to_open_button(client: TestClient, tmp_path: pathlib.Path):
    T._create_authenticated_user(client)
    dataset_id = T._upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert resp.status_code == 200
    html = _inline_assets(resp.text)

    html_file = tmp_path / "settings_escape.html"
    html_file.write_text(html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        _load_settings_page(page, html_file, client)

        open_btn = page.locator('.pick-open[data-kind="persons"]')
        open_btn.click()

        dialog = page.locator('#picker-dialog')
        assert dialog.is_visible()

        # Press Escape
        page.keyboard.press("Escape")

        # Dialog is closed
        assert not dialog.is_visible()

        # Focus returns to the .pick-open button that opened it
        focused_el = page.evaluate("() => document.activeElement.getAttribute('data-kind')")
        assert focused_el == "persons"

        browser.close()


def test_rejected_settings_restore_participants_and_items_in_browser(client: TestClient, tmp_path: pathlib.Path):
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

        _load_settings_page(page, html_file, client, intercepted_posts=intercepted_requests)

        # Assert summaries restored from pre-rendered carriers
        persons_summary = page.locator('.pick-summary[data-summary="persons"]')
        assert persons_summary.inner_text() == "2 dipilih"
        items_summary = page.locator('.pick-summary[data-summary="items"]')
        assert items_summary.inner_text() == "1 dipilih"

        # Open persons dialog and check chips
        page.locator('.pick-open[data-kind="persons"]').click()
        page.wait_for_selector('#picker-chosen .chip')

        chips = page.locator('#picker-chosen .chip')
        assert chips.count() == 2

        # Close dialog
        page.locator('#picker-dialog [data-close]').click()

        # Submit form and verify carriers posted
        page.locator('#misfit').fill("1.50")
        page.locator('form.upload-form button[type="submit"]').click()

        browser.close()

    assert len(intercepted_requests) == 1
    req = intercepted_requests[0]
    assert req.method == "POST"
    post_data = req.post_data
    assert post_data is not None

    # Assert request carries pd_pick twice (2 and 5) and id_pick once (1)
    assert post_data.count('name="pd_pick"') == 2
    assert re.search(r'name="pd_pick"\r?\n\r?\n2\b', post_data) is not None
    assert re.search(r'name="pd_pick"\r?\n\r?\n5\b', post_data) is not None
    assert post_data.count('name="id_pick"') == 1
    assert re.search(r'name="id_pick"\r?\n\r?\n1\b', post_data) is not None


def test_items_list_filling_carriers_and_submitting(client: TestClient, tmp_path: pathlib.Path):
    T._create_authenticated_user(client)
    dataset_id = T._upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert resp.status_code == 200
    html = _inline_assets(resp.text)

    html_file = tmp_path / "settings_items.html"
    html_file.write_text(html, encoding="utf-8")

    intercepted_requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        _load_settings_page(page, html_file, client, intercepted_posts=intercepted_requests)

        # Open items picker
        page.locator('.pick-open[data-kind="items"]').click()
        page.wait_for_selector('#picker-results .pick-row')

        # Check item row content has item label (I01)
        first_row = page.locator('#picker-results .pick-row').first
        assert "I01" in first_row.inner_text()

        # Select item pos 1
        page.locator('#picker-results .pick-row input[type="checkbox"]').first.check()

        # Close dialog
        page.locator('#picker-dialog [data-close]').click()

        # Check summary reads "1 dipilih"
        assert page.locator('.pick-summary[data-summary="items"]').inner_text() == "1 dipilih"

        # Submit form
        page.locator('form.upload-form button[type="submit"]').click()

        browser.close()

    assert len(intercepted_requests) == 1
    req = intercepted_requests[0]
    assert req.method == "POST"
    post_data = req.post_data
    assert post_data is not None

    assert post_data.count('name="id_pick"') == 1
    assert re.search(r'name="id_pick"\r?\n\r?\n1\b', post_data) is not None
