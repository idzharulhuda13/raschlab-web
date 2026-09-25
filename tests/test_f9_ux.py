"""Integration tests for F9 UX batch (readability, placement, navigation, feedback).

Covers the 19 acceptance checks specified in PLAN-f9-ux.md:
1. GET /analyses signed in -> 200 and lists the seeded finished analysis (dataset name + both links).
2. Two-user isolation: user B never sees user A's analysis in the list or by direct URL.
3. Ordering: two analyses -> newest first.
4. Empty state text present when the user has no finished analysis.
5. Signed out -> 303 to /login (assert the redirect target).
6. A failed/running analysis is NOT listed.
7. Upload POST redirect Location carries ?msg=uploaded.
8. Upload destination page rendered on a plain GET shows confirmation sentence.
9. Commit POST redirect Location carries ?msg=committed.
10. Commit destination page rendered on a plain GET shows confirmation sentence.
11. Analyze POST redirect Location carries ?msg=analyzed.
12. Analyze destination page rendered on a plain GET shows confirmation sentence.
13. Discard POST redirect Location carries ?msg=discarded.
14. Discard destination page rendered on a plain GET shows confirmation sentence.
15. Tab parameters: GET /analyses/{id}/explore?view=butir&from=1&to=2 carries from=1 and to=2 in tab hrefs.
16. Tab parameters: request with no extra params renders hrefs with no trailing &.
17. Misfit band number equals recomputation from item table (INFIT MNSQ >= 1.50).
18. Exactly one nav link carries the active marker on each authenticated page.
19. Analysis page section order: Butir Bermasalah < Rekap Responden < Tabel Butir (15.1) < Tabel Opsi dan Distraktor (15.3) < Tabel Responden, and Tabel Ringkasan absent.
20. Item table sort buttons distinct visible text and distinct aria-labels.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from fastapi.testclient import TestClient

from app.analysis import load_tables
from app.db import SessionLocal
from app.models import Analysis, Dataset
from tests.test_analysis_routes import _create_authenticated_user
from tests.test_explorer_routes import (
    _ITEM_HEADER_ROW0,
    _ITEM_HEADER_ROW1,
    _PERSON_HEADER_ROW0,
    _PERSON_HEADER_ROW1,
    _WRIGHT_DATA_ROWS,
    _WRIGHT_HEADER_ROW0,
    _WRIGHT_HEADER_ROW1,
    _csv,
    _seed_done,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

_F9_HEADER_ROW0 = [
    "ENTRY", "TOTAL SCORE", "TOTAL COUNT", "MEASURE", "MODEL S.E.",
    "INFIT MNSQ", "INFIT ZSTD", "OUTFIT MNSQ", "OUTFIT ZSTD",
    "PTMEASUR-AL CORR.", "EXP.", "EXACT OBS%", "EXACT EXPECTED%", "ITEM"
]
_F9_HEADER_ROW1 = [
    "NUMBER", "SCORE", "COUNT", "MEASURE", "S.E.",
    "MNSQ", "ZSTD", "MNSQ", "ZSTD",
    "CORR.", "EXP.", "OBS%", "EXP%", "ITEM"
]


def _build_test_files(item_rows_extra: list[list[str]] | None = None) -> dict[str, str]:
    item_rows = [_F9_HEADER_ROW0, _F9_HEADER_ROW1]
    if item_rows_extra:
        item_rows.extend(item_rows_extra)
    else:
        # Default 3 items: two normal, one misfit (INFIT MNSQ >= 1.50)
        # col 5 is INFIT MNSQ
        r1 = ["1", "50", "30", "-0.50", "0.20", "1.10", "0.5", "1.05", "0.3", "0.45", "0.40", "70%", "68%", "Item1"]
        r2 = ["2", "45", "30", "0.00", "0.21", "1.65", "2.1", "1.70", "2.2", "0.35", "0.40", "60%", "65%", "Item2"]
        r3 = ["3", "40", "30", "0.50", "0.22", "0.95", "-0.2", "0.98", "-0.1", "0.50", "0.40", "75%", "72%", "Item3"]
        item_rows.extend([r1, r2, r3])

    return {
        "item_table_15.1.csv": _csv(item_rows),
        "option_table_15.3.csv": _csv([["ENTRY", "DATA"], ["", ""]]),
        "person_table.csv": _csv([_PERSON_HEADER_ROW0, _PERSON_HEADER_ROW1]),
        "summary_table.csv": _csv([["PERSON", "COUNT", "30"], ["ITEM", "COUNT", "3"]]),
        "wright_map_measure.csv": _csv([_WRIGHT_HEADER_ROW0, _WRIGHT_HEADER_ROW1] + _WRIGHT_DATA_ROWS),
        "wright_map_frequency.csv": _csv([_WRIGHT_HEADER_ROW0, _WRIGHT_HEADER_ROW1] + _WRIGHT_DATA_ROWS),
    }

def _seed_f9(
    user_id: int,
    filename: str,
    files: dict[str, str],
    status: str = "done",
    created_at: int | None = None,
    n_items: int = 12,
) -> int:
    aid = _seed_done(user_id, filename, files, status=status, created_at=created_at, n_items=n_items)
    with SessionLocal() as db:
        analysis = db.get(Analysis, aid)
        dataset = db.get(Dataset, analysis.dataset_id)
        dataset.summary_json = json.dumps({"missing_per_item": [0] * n_items})
        db.commit()
    return aid


# ---------------------------------------------------------------------------
# 1. GET /analyses signed in -> 200 and lists finished analysis
# ---------------------------------------------------------------------------

def test_analyses_signed_in_lists_finished_analysis(client: TestClient):
    user_id = _create_authenticated_user(client, email="user_f9_1@example.test")
    aid = _seed_f9(user_id, "ujian_matematika.csv", _build_test_files())

    resp = client.get("/analyses")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "ujian_matematika.csv" in resp.text, "Dataset filename 'ujian_matematika.csv' not found in response text"
    assert f'href="/analyses/{aid}"' in resp.text, f"Result link href='/analyses/{aid}' not found in response text"
    assert f'href="/analyses/{aid}/explore"' in resp.text, f"Explorer link href='/analyses/{aid}/explore' not found in response text"


# ---------------------------------------------------------------------------
# 2. Two-user isolation
# ---------------------------------------------------------------------------

def test_two_user_isolation(client: TestClient):
    user_a = _create_authenticated_user(client, email="user_f9_a@example.test")
    aid_a = _seed_f9(user_a, "dataset_rahasia_a.csv", _build_test_files())

    # Switch to User B
    user_b = _create_authenticated_user(client, email="user_f9_b@example.test")

    # In /analyses index, user A's analysis must not appear
    resp = client.get("/analyses")
    assert resp.status_code == 200, f"Expected 200 for user B, got {resp.status_code}"
    assert "dataset_rahasia_a.csv" not in resp.text, "User A's dataset filename appeared in User B's /analyses"
    assert f"/analyses/{aid_a}" not in resp.text, "User A's analysis ID appeared in User B's /analyses"

    # Direct GET to User A's analysis by User B must be 404
    resp_direct = client.get(f"/analyses/{aid_a}")
    assert resp_direct.status_code == 404, f"Expected 404 for foreign analysis, got {resp_direct.status_code}"


# ---------------------------------------------------------------------------
# 3. Ordering: newest first
# ---------------------------------------------------------------------------

def test_analyses_ordering_newest_first(client: TestClient):
    user_id = _create_authenticated_user(client, email="user_f9_order@example.test")
    aid_old = _seed_f9(user_id, "old_run.csv", _build_test_files(), created_at=1000)
    aid_new = _seed_f9(user_id, "new_run.csv", _build_test_files(), created_at=2000)

    resp = client.get("/analyses")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    idx_old = resp.text.find(f"/analyses/{aid_old}")
    idx_new = resp.text.find(f"/analyses/{aid_new}")
    assert idx_old != -1, f"Old analysis /analyses/{aid_old} not found in response text"
    assert idx_new != -1, f"New analysis /analyses/{aid_new} not found in response text"
    assert idx_new < idx_old, f"Expected newest analysis ({aid_new} at {idx_new}) before older ({aid_old} at {idx_old})"


# ---------------------------------------------------------------------------
# 4. Empty state text
# ---------------------------------------------------------------------------

def test_analyses_empty_state(client: TestClient):
    _create_authenticated_user(client, email="user_f9_empty@example.test")
    resp = client.get("/analyses")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "Belum ada hasil analisis" in resp.text, f"Empty state text 'Belum ada hasil analisis' not in response: {resp.text[:300]}"


# ---------------------------------------------------------------------------
# 5. Signed out -> 303 to /login
# ---------------------------------------------------------------------------

def test_analyses_signed_out_redirects(client: TestClient):
    client.cookies.clear()
    resp = client.get("/analyses", follow_redirects=False)
    assert resp.status_code == 303, f"Expected 303 redirect to /login for signed out GET /analyses, got {resp.status_code}"
    assert resp.headers.get("location") == "/login", f"Expected Location: /login, got {resp.headers.get('location')}"


# ---------------------------------------------------------------------------
# 6. Failed/running analysis is NOT listed
# ---------------------------------------------------------------------------

def test_analyses_failed_and_running_not_listed(client: TestClient):
    user_id = _create_authenticated_user(client, email="user_f9_status@example.test")
    aid_running = _seed_f9(user_id, "running.csv", _build_test_files(), status="running")
    aid_failed = _seed_f9(user_id, "failed.csv", _build_test_files(), status="failed")
    aid_done = _seed_f9(user_id, "done.csv", _build_test_files(), status="done")

    resp = client.get("/analyses")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert f"/analyses/{aid_done}" in resp.text, f"Done analysis /analyses/{aid_done} not in list"
    assert f"/analyses/{aid_running}" not in resp.text, f"Running analysis /analyses/{aid_running} must not be in list"
    assert f"/analyses/{aid_failed}" not in resp.text, f"Failed analysis /analyses/{aid_failed} must not be in list"


# ---------------------------------------------------------------------------
# 7-14. ?msg= on the four POSTs
# ---------------------------------------------------------------------------

def test_upload_post_redirect_location(client: TestClient):
    _create_authenticated_user(client, email="user_f9_msg_up@example.test")
    csv_bytes = (FIXTURES_DIR / "sample_300x40.csv").read_bytes()
    resp = client.post("/datasets", files={"data": ("upload_test.csv", csv_bytes, "text/csv")}, follow_redirects=False)
    assert resp.status_code == 303, f"Expected 303 from upload POST, got {resp.status_code}"
    location = resp.headers.get("location", "")
    assert "?msg=uploaded" in location, f"Expected ?msg=uploaded in redirect Location, got: {location}"


def test_upload_landing_page_shows_sentence(client: TestClient):
    _create_authenticated_user(client, email="user_f9_msg_up2@example.test")
    csv_bytes = (FIXTURES_DIR / "sample_300x40.csv").read_bytes()
    resp = client.post("/datasets", files={"data": ("upload_test2.csv", csv_bytes, "text/csv")}, follow_redirects=False)
    location = resp.headers.get("location", "")
    landing = client.get(location)
    assert landing.status_code == 200, f"Expected 200 on upload landing, got {landing.status_code}"
    expected_sentence = "Berkas berhasil diunggah. Periksa pratinjau, lalu tetapkan klasifikasi token."
    assert expected_sentence in landing.text, f"Upload sentence not found in landing page text: {landing.text[:400]}"


def test_commit_post_redirect_location(client: TestClient):
    _create_authenticated_user(client, email="user_f9_msg_com@example.test")
    csv_bytes = (FIXTURES_DIR / "sample_300x40.csv").read_bytes()
    up_resp = client.post("/datasets", files={"data": ("commit_test.csv", csv_bytes, "text/csv")}, follow_redirects=False)
    ds_id = int(up_resp.headers["location"].split("/")[-1].split("?")[0])

    commit_resp = client.post(
        f"/datasets/{ds_id}/commit",
        data={"t0": "1", "m0": "correct", "t1": "0", "m1": "incorrect", "t2": "NA", "m2": "missing", "t3": "", "m3": "missing"},
        follow_redirects=False,
    )
    assert commit_resp.status_code == 303, f"Expected 303 from commit POST, got {commit_resp.status_code}"
    location = commit_resp.headers.get("location", "")
    assert "?msg=committed" in location, f"Expected ?msg=committed in redirect Location, got: {location}"


def test_commit_landing_page_shows_sentence(client: TestClient):
    _create_authenticated_user(client, email="user_f9_msg_com2@example.test")
    csv_bytes = (FIXTURES_DIR / "sample_300x40.csv").read_bytes()
    up_resp = client.post("/datasets", files={"data": ("commit_test2.csv", csv_bytes, "text/csv")}, follow_redirects=False)
    ds_id = int(up_resp.headers["location"].split("/")[-1].split("?")[0])

    commit_resp = client.post(
        f"/datasets/{ds_id}/commit",
        data={"t0": "1", "m0": "correct", "t1": "0", "m1": "incorrect", "t2": "NA", "m2": "missing", "t3": "", "m3": "missing"},
        follow_redirects=False,
    )
    location = commit_resp.headers.get("location", "")
    landing = client.get(location)
    assert landing.status_code == 200, f"Expected 200 on commit landing, got {landing.status_code}"
    expected_sentence = "Pemetaan respon berhasil dikonfirmasi. Jalankan analisis untuk memperoleh hasil."
    assert expected_sentence in landing.text, f"Commit sentence not found in landing page text: {landing.text[:400]}"


def test_analyze_post_redirect_location(client: TestClient):
    _create_authenticated_user(client, email="user_f9_msg_ana@example.test")
    csv_bytes = (FIXTURES_DIR / "sample_300x40.csv").read_bytes()
    up_resp = client.post("/datasets", files={"data": ("ana_test.csv", csv_bytes, "text/csv")}, follow_redirects=False)
    ds_id = int(up_resp.headers["location"].split("/")[-1].split("?")[0])
    client.post(
        f"/datasets/{ds_id}/commit",
        data={"t0": "1", "m0": "correct", "t1": "0", "m1": "incorrect", "t2": "NA", "m2": "missing", "t3": "", "m3": "missing"},
        follow_redirects=False,
    )
    ana_resp = client.post(f"/datasets/{ds_id}/analyze", follow_redirects=False)
    assert ana_resp.status_code == 303, f"Expected 303 from analyze POST, got {ana_resp.status_code}"
    location = ana_resp.headers.get("location", "")
    assert "?msg=analyzed" in location, f"Expected ?msg=analyzed in redirect Location, got: {location}"


def test_analyze_landing_page_shows_sentence(client: TestClient):
    _create_authenticated_user(client, email="user_f9_msg_ana2@example.test")
    csv_bytes = (FIXTURES_DIR / "sample_300x40.csv").read_bytes()
    up_resp = client.post("/datasets", files={"data": ("ana_test2.csv", csv_bytes, "text/csv")}, follow_redirects=False)
    ds_id = int(up_resp.headers["location"].split("/")[-1].split("?")[0])
    client.post(
        f"/datasets/{ds_id}/commit",
        data={"t0": "1", "m0": "correct", "t1": "0", "m1": "incorrect", "t2": "NA", "m2": "missing", "t3": "", "m3": "missing"},
        follow_redirects=False,
    )
    ana_resp = client.post(f"/datasets/{ds_id}/analyze", follow_redirects=False)
    location = ana_resp.headers.get("location", "")
    landing = client.get(location)
    assert landing.status_code == 200, f"Expected 200 on analyze landing, got {landing.status_code}"
    expected_sentence = "Analisis berhasil dimulai. Tunggu hingga berstatus Selesai, lalu buka Jelajahi hasil."
    assert expected_sentence in landing.text, f"Analyze sentence not found in landing page text: {landing.text[:400]}"


def test_discard_post_redirect_location(client: TestClient):
    _create_authenticated_user(client, email="user_f9_msg_disc@example.test")
    csv_bytes = (FIXTURES_DIR / "sample_300x40.csv").read_bytes()
    up_resp = client.post("/datasets", files={"data": ("disc_test.csv", csv_bytes, "text/csv")}, follow_redirects=False)
    ds_id = int(up_resp.headers["location"].split("/")[-1].split("?")[0])

    disc_resp = client.post(f"/datasets/{ds_id}/discard", follow_redirects=False)
    assert disc_resp.status_code == 303, f"Expected 303 from discard POST, got {disc_resp.status_code}"
    location = disc_resp.headers.get("location", "")
    assert "?msg=discarded" in location, f"Expected ?msg=discarded in redirect Location, got: {location}"


def test_discard_landing_page_shows_sentence(client: TestClient):
    _create_authenticated_user(client, email="user_f9_msg_disc2@example.test")
    csv_bytes = (FIXTURES_DIR / "sample_300x40.csv").read_bytes()
    up_resp = client.post("/datasets", files={"data": ("disc_test2.csv", csv_bytes, "text/csv")}, follow_redirects=False)
    ds_id = int(up_resp.headers["location"].split("/")[-1].split("?")[0])

    disc_resp = client.post(f"/datasets/{ds_id}/discard", follow_redirects=False)
    location = disc_resp.headers.get("location", "")
    landing = client.get(location)
    assert landing.status_code == 200, f"Expected 200 on discard landing, got {landing.status_code}"
    expected_sentence = "Berkas berhasil dibuang. Unggah berkas baru untuk memulai kembali."
    assert expected_sentence in landing.text, f"Discard sentence not found in landing page text: {landing.text[:400]}"


# ---------------------------------------------------------------------------
# 15-16. Tab parameters
# ---------------------------------------------------------------------------

def test_tab_parameters_preserve_query_params(client: TestClient):
    user_id = _create_authenticated_user(client, email="user_f9_tabs@example.test")
    aid1 = _seed_f9(user_id, "tab_test1.csv", _build_test_files())
    aid2 = _seed_f9(user_id, "tab_test2.csv", _build_test_files())

    resp = client.get(f"/analyses/{aid1}/explore?view=butir&from={aid1}&to={aid2}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    tab_hrefs = re.findall(r'<a[^>]+id="tab-[^"]+"[^>]+href="([^"]+)"', resp.text)
    assert len(tab_hrefs) > 0, "No tab links found with id='tab-...'"
    for href in tab_hrefs:
        assert f"from={aid1}" in href, f"Tab href '{href}' does not carry from={aid1}"
        assert f"to={aid2}" in href, f"Tab href '{href}' does not carry to={aid2}"


def test_tab_parameters_no_trailing_ampersand(client: TestClient):
    user_id = _create_authenticated_user(client, email="user_f9_tabs_clean@example.test")
    aid = _seed_f9(user_id, "tab_clean.csv", _build_test_files())

    resp = client.get(f"/analyses/{aid}/explore")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    tab_hrefs = re.findall(r'<a[^>]+id="tab-[^"]+"[^>]+href="([^"]+)"', resp.text)
    assert len(tab_hrefs) > 0, "No tab links found with id='tab-...'"
    for href in tab_hrefs:
        assert not href.endswith("&"), f"Tab href '{href}' has trailing '&'"
        assert "&" not in href or "?" in href, f"Tab href '{href}' has invalid query structure"


# ---------------------------------------------------------------------------
# 17. Misfit band number recomputation match
# ---------------------------------------------------------------------------

def test_misfit_band_count_equals_recomputation(client: TestClient):
    user_id = _create_authenticated_user(client, email="user_f9_misfit@example.test")
    # Seed analysis with 1 misfit out of 3
    aid = _seed_f9(user_id, "misfit_test.csv", _build_test_files())

    with SessionLocal() as db:
        analysis = db.get(Analysis, aid)
        tables = load_tables(analysis)
        item_table = tables["item_table_15.1.csv"]

        # Production rule:
        # rows[0] long header INFIT MNSQ, rows[2:] data rows with float(val) >= 1.50
        long_headers = [str(h).strip().upper() for h in item_table[0]]
        infit_idx = long_headers.index("INFIT MNSQ")
        recomputed_misfit = 0
        data_rows = item_table[2:]
        for r in data_rows:
            if infit_idx < len(r) and float(r[infit_idx]) >= 1.50:
                recomputed_misfit += 1

    resp = client.get(f"/analyses/{aid}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    # Extract misfit band number from rendered text: "X dari Y butir melewati ambang misfit INFIT MNSQ ≥ 1,50."
    m = re.search(r"(\d+)\s+dari\s+(\d+)\s+butir melewati ambang misfit INFIT MNSQ", resp.text)
    assert m is not None, f"Misfit orientation band not found in analysis HTML: {resp.text[:500]}"
    rendered_misfit = int(m.group(1))

    assert rendered_misfit == recomputed_misfit, (
        f"Misfit count mismatch: rendered={rendered_misfit} != recomputed={recomputed_misfit}"
    )


# ---------------------------------------------------------------------------
# 18. Exactly one nav link carries active marker
# ---------------------------------------------------------------------------

def test_exactly_one_active_nav_marker_per_page(client: TestClient):
    user_id = _create_authenticated_user(client, email="user_f9_nav@example.test")
    aid = _seed_f9(user_id, "nav_test.csv", _build_test_files())

    # Get dataset id from analysis
    with SessionLocal() as db:
        analysis = db.get(Analysis, aid)
        ds_id = analysis.dataset_id

    routes_to_test = [
        "/datasets",
        f"/datasets/{ds_id}",
        f"/analyses/{aid}",
        f"/analyses/{aid}/explore",
        "/analyses",
        "/account",
    ]

    for path in routes_to_test:
        resp = client.get(path)
        assert resp.status_code == 200, f"Expected 200 for {path}, got {resp.status_code}"

        nav_match = re.search(r'<nav[^>]*class="[^"]*\bappnav\b[^"]*"[^>]*>(.*?)</nav>', resp.text, re.DOTALL)
        nav_html = nav_match.group(1) if nav_match else ""
        active_class_links = re.findall(r'<a[^>]+class="[^"]*\bis-active\b[^"]*"', nav_html)
        aria_current_links = re.findall(r'<a[^>]+aria-current="page"', nav_html)

        active_count = len(active_class_links)
        aria_count = len(aria_current_links)

        assert active_count == 1, (
            f"Page {path}: expected exactly 1 active nav link, found {active_count} ({active_class_links})"
        )
        assert aria_count == 1, (
            f"Page {path}: expected exactly 1 aria-current='page' nav link, found {aria_count} ({aria_current_links})"
        )


# ---------------------------------------------------------------------------
# 19. Analysis page section order
# ---------------------------------------------------------------------------

def test_analysis_page_section_order(client: TestClient):
    user_id = _create_authenticated_user(client, email="user_f9_order_sec@example.test")
    aid = _seed_f9(user_id, "sections_test.csv", _build_test_files())

    resp = client.get(f"/analyses/{aid}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    html = resp.text

    idx_misfit = html.find("Butir Bermasalah")
    idx_rekap = html.find("Rekap Responden")
    idx_butir = html.find("Tabel Butir (15.1)")
    idx_opsi = html.find("Tabel Opsi dan Distraktor (15.3)")
    idx_responden = html.find("Tabel Responden")

    assert idx_misfit != -1, f"'Butir Bermasalah' not found in HTML"
    assert idx_rekap != -1, f"'Rekap Responden' not found in HTML"
    assert idx_butir != -1, f"'Tabel Butir (15.1)' not found in HTML"
    assert idx_opsi != -1, f"'Tabel Opsi dan Distraktor (15.3)' not found in HTML"
    assert idx_responden != -1, f"'Tabel Responden' not found in HTML"

    assert idx_misfit < idx_rekap, f"Expected 'Butir Bermasalah' ({idx_misfit}) < 'Rekap Responden' ({idx_rekap})"
    assert idx_rekap < idx_butir, f"Expected 'Rekap Responden' ({idx_rekap}) < 'Tabel Butir (15.1)' ({idx_butir})"
    assert idx_butir < idx_opsi, f"Expected 'Tabel Butir (15.1)' ({idx_butir}) < 'Tabel Opsi dan Distraktor (15.3)' ({idx_opsi})"
    assert idx_opsi < idx_responden, f"Expected 'Tabel Opsi dan Distraktor (15.3)' ({idx_opsi}) < 'Tabel Responden' ({idx_responden})"

    assert "Tabel Ringkasan" not in html, "'Tabel Ringkasan' must be absent from analysis page"


# ---------------------------------------------------------------------------
# 20. Item table sort buttons distinct visible text and aria-labels
# ---------------------------------------------------------------------------

def test_item_table_sort_buttons_distinct_visible_text_and_aria_labels(client: TestClient):
    user_id = _create_authenticated_user(client, email="user_f9_distinct_headers@example.test")
    aid = _seed_f9(user_id, "distinct_headers.csv", _build_test_files())

    resp = client.get(f"/analyses/{aid}/explore?view=butir")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    html = resp.text

    button_matches = re.findall(
        r'(<button[^>]*class="[^"]*\bth-sort\b[^"]*"[^>]*>(.*?)</button>)',
        html,
        re.DOTALL,
    )
    assert len(button_matches) > 0, "No button.th-sort elements found in item table"

    visible_texts = []
    aria_labels = []
    for full_tag, inner_text in button_matches:
        vis = inner_text.strip()
        aria_m = re.search(r'aria-label="([^"]*)"', full_tag)
        aria = aria_m.group(1).strip() if aria_m else ""
        visible_texts.append(vis)
        aria_labels.append(aria)

    seen_vis: set[str] = set()
    dup_vis: list[str] = []
    for v in visible_texts:
        if v in seen_vis:
            dup_vis.append(v)
        seen_vis.add(v)
    assert not dup_vis, f"Duplicated visible text found in button.th-sort: {dup_vis}"

    seen_aria: set[str] = set()
    dup_aria: list[str] = []
    for a in aria_labels:
        if a in seen_aria:
            dup_aria.append(a)
        seen_aria.add(a)
    assert not dup_aria, f"Duplicated aria-label found in button.th-sort: {dup_aria}"

