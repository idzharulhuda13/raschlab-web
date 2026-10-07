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


def test_anchors_marking_chips_typing_values_and_submitting(client: TestClient, tmp_path: pathlib.Path):
    T._create_authenticated_user(client)
    dataset_id = T._upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert resp.status_code == 200
    html = _inline_assets(resp.text)

    html_file = tmp_path / "settings_anchors_submit.html"
    html_file.write_text(html, encoding="utf-8")

    intercepted_requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        _load_settings_page(page, html_file, client, intercepted_posts=intercepted_requests)

        # Open anchors picker
        page.locator('.pick-open[data-kind="anchors"]').click()
        page.wait_for_selector('#picker-results .pick-row')

        # Select two items (pos 1 and pos 2)
        checkboxes = page.locator('#picker-results .pick-row input[type="checkbox"]')
        checkboxes.nth(0).check()
        checkboxes.nth(1).check()

        # Summary reads 2 jangkar
        summary = page.locator('.pick-summary[data-summary="anchors"]')
        assert summary.inner_text() == "2 jangkar"

        # Chosen list contains two chips with number inputs
        chips = page.locator('#picker-chosen .chip')
        assert chips.count() == 2
        inputs = page.locator('#picker-chosen .chip input[type="number"]')
        assert inputs.count() == 2

        # Type anchor values into chips
        inputs.nth(0).fill("0.5")
        inputs.nth(1).fill("-1.25")

        # Hidden carriers in form
        pos_carriers = page.locator('#picker-carriers input[name="anchor_pos"]')
        val_carriers = page.locator('#picker-carriers input[name="anchor_value"]')
        assert pos_carriers.count() == 2
        assert val_carriers.count() == 2
        assert pos_carriers.nth(0).get_attribute("value") == "1"
        assert val_carriers.nth(0).get_attribute("value") == "0.5"
        assert pos_carriers.nth(1).get_attribute("value") == "2"
        assert val_carriers.nth(1).get_attribute("value") == "-1.25"

        # Close dialog and submit form
        page.locator('#picker-dialog [data-close]').click()
        page.locator('form.upload-form button[type="submit"]').click()

        browser.close()

    assert len(intercepted_requests) == 1
    req = intercepted_requests[0]
    assert req.method == "POST"
    post_data = req.post_data
    assert post_data is not None

    # Assert request carries both anchor_pos and anchor_value twice, in pairs
    assert post_data.count('name="anchor_pos"') == 2
    assert post_data.count('name="anchor_value"') == 2
    assert re.search(r'name="anchor_pos"\r?\n\r?\n1\b', post_data) is not None
    assert re.search(r'name="anchor_value"\r?\n\r?\n0\.5\b', post_data) is not None
    assert re.search(r'name="anchor_pos"\r?\n\r?\n2\b', post_data) is not None
    assert re.search(r'name="anchor_value"\r?\n\r?\n-1\.25\b', post_data) is not None


def test_unmarking_anchor_removes_carrier_pair(client: TestClient, tmp_path: pathlib.Path):
    T._create_authenticated_user(client)
    dataset_id = T._upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert resp.status_code == 200
    html = _inline_assets(resp.text)

    html_file = tmp_path / "settings_anchors_unmark.html"
    html_file.write_text(html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        _load_settings_page(page, html_file, client)

        # Open anchors picker
        page.locator('.pick-open[data-kind="anchors"]').click()
        page.wait_for_selector('#picker-results .pick-row')

        # Select two items (pos 1 and pos 2)
        checkboxes = page.locator('#picker-results .pick-row input[type="checkbox"]')
        checkboxes.nth(0).check()
        checkboxes.nth(1).check()

        # Type anchor values
        inputs = page.locator('#picker-chosen .chip input[type="number"]')
        inputs.nth(0).fill("0.5")
        inputs.nth(1).fill("-1.25")

        summary = page.locator('.pick-summary[data-summary="anchors"]')
        assert summary.inner_text() == "2 jangkar"

        # Unmark pos 1 via chip remove button
        page.locator('#picker-chosen .chip[data-pos="1"] .chip-remove').click()

        # Summary updates to 1 jangkar
        assert summary.inner_text() == "1 jangkar"
        assert page.locator('#picker-chosen .chip').count() == 1

        # Carrier pair for pos 1 is removed, only pos 2 remains
        pos_carriers = page.locator('#picker-carriers input[name="anchor_pos"]')
        val_carriers = page.locator('#picker-carriers input[name="anchor_value"]')
        assert pos_carriers.count() == 1
        assert val_carriers.count() == 1
        assert pos_carriers.nth(0).get_attribute("value") == "2"
        assert val_carriers.nth(0).get_attribute("value") == "-1.25"

        # Row 1 checkbox in results is unchecked
        assert not page.locator('#picker-results .pick-row[data-pos="1"] input[type="checkbox"]').is_checked()

        # Unmark pos 2 via checkbox in results
        page.locator('#picker-results .pick-row[data-pos="2"] input[type="checkbox"]').uncheck()

        # Summary updates to Belum ada and all anchor carriers removed
        assert summary.inner_text() == "Belum ada"
        assert page.locator('#picker-chosen .chip').count() == 0
        assert page.locator('#picker-carriers input[name="anchor_pos"]').count() == 0
        assert page.locator('#picker-carriers input[name="anchor_value"]').count() == 0

        browser.close()


def test_rejected_non_numeric_anchor_value_restores_picker_state(client: TestClient, tmp_path: pathlib.Path):
    T._create_authenticated_user(client)
    dataset_id = T._upload_and_commit_sample(client)

    resp = client.post(
        f"/datasets/{dataset_id}/analyze",
        data={
            "anchor_pos": ["1"],
            "anchor_value": ["abc"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422
    html = _inline_assets(resp.text)

    html_file = tmp_path / "settings_bad_anchor_restore.html"
    html_file.write_text(html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        _load_settings_page(page, html_file, client)

        # Summary reads 1 jangkar after JavaScript runs
        summary = page.locator('.pick-summary[data-summary="anchors"]')
        assert summary.inner_text() == "1 jangkar"

        # Open anchors picker
        page.locator('.pick-open[data-kind="anchors"]').click()
        page.wait_for_selector('#picker-chosen .chip')

        # Chip is restored with typed value in input
        chip = page.locator('#picker-chosen .chip[data-pos="1"]')
        assert chip.count() == 1
        val_input = chip.locator('input')
        assert val_input.get_attribute("value") == "abc"

        # Results row for pos 1 is checked
        page.wait_for_selector('#picker-results .pick-row')
        assert page.locator('#picker-results .pick-row[data-pos="1"] input[type="checkbox"]').is_checked()

        browser.close()


def test_picker_results_bounded_with_anchors_and_search(client: TestClient, tmp_path: pathlib.Path):
    T._create_authenticated_user(client)

    # 300-item dataset fixture
    header = "id," + ",".join(f"Item{i:03d}" for i in range(1, 301))
    rows = [header]
    for p in range(1, 6):
        rows.append(f"P{p:03d}," + ",".join("1" if (p + i) % 2 == 0 else "0" for i in range(1, 301)))
    csv_bytes = "\n".join(rows).encode("utf-8")

    upload_resp = client.post(
        "/datasets",
        files={"data": ("items_300.csv", csv_bytes, "text/csv")},
        follow_redirects=False,
    )
    assert upload_resp.status_code == 303
    dataset_id = int(upload_resp.headers["location"].split("/")[-1].split("?")[0])

    commit_resp = client.post(
        f"/datasets/{dataset_id}/commit",
        data={"t0": "1", "m0": "correct", "t1": "0", "m1": "incorrect"},
        follow_redirects=False,
    )
    assert commit_resp.status_code == 303

    resp = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert resp.status_code == 200
    html = _inline_assets(resp.text)

    html_file = tmp_path / "settings_anchors_search_300.html"
    html_file.write_text(html, encoding="utf-8")

    picker_requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        _load_settings_page(page, html_file, client, picker_requests=picker_requests)

        # Open anchors picker
        page.locator('.pick-open[data-kind="anchors"]').click()
        page.wait_for_selector('#picker-results .pick-row')

        # Bounded at most 5 rows with 300-item dataset
        rows = page.locator('#picker-results .pick-row')
        assert rows.count() <= 5
        assert rows.count() == 5
        assert "5 dari 300" in page.locator('#picker-status').inner_text()

        # Mark first item as anchor
        rows.first.locator('input[type="checkbox"]').check()
        assert page.locator('#picker-chosen .chip').count() == 1

        # Search in anchors picker with anchor in play
        page.locator('#picker-search').fill("001")
        page.wait_for_timeout(300)
        page.wait_for_selector('#picker-results .pick-row')

        # Results still bounded at most 5 rows
        rows_after = page.locator('#picker-results .pick-row')
        assert rows_after.count() <= 5

        # Search requested kind=items
        search_urls = [u for u in picker_requests if "q=001" in u]
        assert len(search_urls) >= 1
        assert "kind=items" in search_urls[0]

        browser.close()


def test_items_dialog_anchor_toggle_marks_anchor_and_syncs_carriers(client: TestClient, tmp_path: pathlib.Path):
    T._create_authenticated_user(client)
    dataset_id = T._upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert resp.status_code == 200
    html = _inline_assets(resp.text)

    html_file = tmp_path / "settings_items_anchor_toggle.html"
    html_file.write_text(html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        _load_settings_page(page, html_file, client)

        # Open items picker
        page.locator('.pick-open[data-kind="items"]').click()
        page.wait_for_selector('#picker-results .pick-row')

        # Toggle anchor checkbox for pos 1
        anchor_cb = page.locator('#picker-results .pick-row[data-pos="1"] input[data-action="anchor"]')
        anchor_cb.check()

        # Summary for anchors updates
        assert page.locator('.pick-summary[data-summary="anchors"]').inner_text() == "1 jangkar"

        # Chip appears in chosen list with number input
        chip = page.locator('#picker-chosen .chip[data-pos="1"]')
        assert chip.count() == 1
        num_input = chip.locator('input[type="number"]')
        assert num_input.count() == 1
        num_input.fill("0.5")

        # Hidden carriers reflect anchor
        assert page.locator('#picker-carriers input[name="anchor_pos"][value="1"]').count() == 1
        assert page.locator('#picker-carriers input[name="anchor_value"][value="0.5"]').count() == 1

        browser.close()
