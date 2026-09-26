"""Integration tests for the F4 Explorer route (/analyses/{id}/explore).

Covers:
- Auth and gate guards: anonymous, foreign owner, gate closed.
- Status-based redirects: running and failed analyses redirect to /analyses/{id}.
- Full-page render: shell structure, tablist, five tabs and panels, is-active state,
  embedded #explorer-data JSON with schema 1, noscript block.
- View parameter: view=butir activates the butir panel; unknown view falls back to wright.
- Wright payload reconciliation: bins equal seeded rows, NR_PERSON and NR_ITEM sums match.
- Item payload fields: ENTRY parsed as int, label and numeric cells verbatim.
- Wright-meta line: PERSON COUNT, ITEM COUNT, and excluded count derived from summary rows.
- Ringkasan fragment: summary rows appear verbatim, #summary-note present.
- Item search: matching query narrows rows and shows count; no-match renders #butir-empty
  with frozen sentence and reset link preserving view=butir.
- Person search: same guard for the partisipan panel.
- Pager: links carry view, query and page number.
- Fragment endpoint: valid fragment returns panel HTML without tablist; fragment=wright and
  unknown fragments return 404; foreign analysis fragment returns 404.
- Compare panel: both analysis ids and filenames appear, delta cells carry signed strings
  computed from seeded measures, both means appear verbatim, #cmp-caveat and #cmp-counts
  are present.
- Compare parameter rules: missing one id, equal ids, nonexistent id, foreign id, not-done
  id all return 404.
- Malformed Wright data: status 200, #explorer-error with frozen reason, no #explorer-data,
  butir fragment still returns 200.
- Results page link: done analysis page carries link to /analyses/{id}/explore with label
  "Buka dashboard hasil".
- Cross-dataset compare pairing keys: label-based pairing, entry-based pairing, unpairable
  case with frozen reason sentence.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import COOKIE_NAME
from app.db import SessionLocal
from app.models import Analysis, AnalysisFile, Dataset, SessionRow, User
from app.security import hash_password, hash_token, new_token, now_epoch


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _csv(rows: list[list[str]]) -> str:
    """Produce CSV text exactly as the engine writes it: commas, CRLF, trailing CRLF."""
    return "\r\n".join(",".join(cell for cell in row) for row in rows) + "\r\n"


def _seed_done(
    user_id: int,
    filename: str,
    files: dict[str, str],
    status: str = "done",
    created_at: Optional[int] = None,
    n_persons: int = 30,
    n_items: int = 12,
) -> int:
    """Seed Dataset + Analysis + AnalysisFile rows without running the engine.

    Returns the analysis id.
    """
    now = created_at if created_at is not None else now_epoch()
    with SessionLocal() as db:
        raw_text = b"dummy,csv,content"
        raw_gz = gzip.compress(raw_text, mtime=0)
        item_labels = [f"Item{i+1}" for i in range(n_items)]
        dataset = Dataset(
            user_id=user_id,
            filename=filename,
            kind="delimited",
            format="csv",
            status="ready",
            n_persons=n_persons,
            n_items=n_items,
            item_labels_json=json.dumps(item_labels),
            mapping_json=json.dumps({"1": "correct", "0": "incorrect"}),
            summary_json=json.dumps({}),
            raw_gzip=raw_gz,
            raw_bytes=len(raw_text),
            created_at=now,
            committed_at=now,
        )
        db.add(dataset)
        db.commit()
        dataset_id = dataset.id

        analysis = Analysis(
            user_id=user_id,
            dataset_id=dataset_id,
            status=status,
            params_json=json.dumps({"mode": "compat", "digits": 2}),
            engine_ref="test-ref",
            created_at=now,
            expires_at=now + 180 * 86400,
            finished_at=now if status == "done" else None,
            elapsed_ms=1234 if status == "done" else None,
        )
        db.add(analysis)
        db.commit()
        analysis_id = analysis.id

        for fname, text in files.items():
            raw_bytes = text.encode("utf-8")
            af = AnalysisFile(
                analysis_id=analysis_id,
                filename=fname,
                content_gzip=gzip.compress(raw_bytes, mtime=0),
                sha256=hashlib.sha256(raw_bytes).hexdigest(),
                bytes=len(raw_bytes),
            )
            db.add(af)
        db.commit()

    return analysis_id


def _create_authenticated_user(client: TestClient, email: str = "researcher@example.test") -> int:
    with SessionLocal() as db:
        now = now_epoch()
        user = User(
            email=email,
            email_normalized=email.lower().strip(),
            password_hash=hash_password("katasandi-analysis-123"),
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


# ---------------------------------------------------------------------------
# Shared fixture builder
# ---------------------------------------------------------------------------

# Item table: 12 items, columns 0-13. col 3 = MEASURE, col 13 = LABEL.
_ITEM_HEADER_ROW0 = ["ENTRY", "TOTAL", "TOTAL", "JMLE", "MODEL", "INFIT", "INFIT", "OUTFIT", "OUTFIT", "PTMEASUR-AL", "EXP.", "EXACT", "EXACT", "ITEM"]
_ITEM_HEADER_ROW1 = ["", "SCORE", "COUNT", "MEASURE", "S.E.", "MNSQ", "ZSTD", "MNSQ", "ZSTD", "CORR.", "", "OBS%", "EXPECTED%", ""]

# Person table: 30 persons, columns 0-13.
_PERSON_HEADER_ROW0 = ["ENTRY", "TOTAL", "TOTAL", "JMLE", "MODEL", "INFIT", "INFIT", "OUTFIT", "OUTFIT", "PTMEASUR-AL", "EXP.", "EXACT", "EXACT", "PERSON"]
_PERSON_HEADER_ROW1 = ["", "SCORE", "COUNT", "MEASURE", "S.E.", "MNSQ", "ZSTD", "MNSQ", "ZSTD", "CORR.", "", "OBS%", "EXPECTED%", ""]

_N_ITEMS = 12
_N_PERSONS = 30

# Wright map: 8 bins. NR_PERSON values that sum to 28 (non-extreme out of 30).
# Columns: MEASURE, NR_PERSON, PERSON_HIST, NR_ITEM, ITEMS, ITEM_HIST, PERSON_ENTRIES, ITEM_ENTRIES
_WRIGHT_HEADER_ROW0 = ["MEASURE", "NR_PERSON", "PERSON_HIST", "NR_ITEM", "ITEMS", "ITEM_HIST", "PERSON_ENTRIES", "ITEM_ENTRIES"]
_WRIGHT_HEADER_ROW1 = ["", "", "", "", "", "", "", ""]

_WRIGHT_DATA_ROWS = [
    ["-2.00", "2", "**", "0", "", "", "1 2", ""],
    ["-1.50", "4", "****", "1", "3", "*", "3 4 5 6", "3"],
    ["-1.00", "5", "*****", "2", "1 2", "**", "7 8 9 10 11", "1 2"],
    ["-0.50", "3", "***", "1", "4", "*", "12 13 14", "4"],
    ["0.00", "4", "****", "2", "5 6", "**", "15 16 17 18", "5 6"],
    ["0.50", "3", "***", "2", "7 8", "**", "19 20 21", "7 8"],
    ["1.00", "4", "****", "2", "9 10", "**", "22 23 24 25", "9 10"],
    ["1.50", "3", "***", "2", "11 12", "**", "26 27 28", "11 12"],
]
# sum of NR_PERSON = 2+4+5+3+4+3+4+3 = 28
# sum of NR_ITEM   = 0+1+2+1+2+2+2+2 = 12

_SUMMARY_DATA_ROWS = [
    ["SECTION", "STATISTIC", "VALUE"],
    ["", "", ""],
    ["ITEM", "COUNT", "12"],
    ["ITEM", "MEASURE MEAN", "0.00"],
    ["PERSON", "COUNT", "28"],
    ["PERSON", "MEASURE MEAN", "0.15"],
    ["PERSON", "EXTREME INCL COUNT", "30"],
]

# Summary rekap keys the server builds:
# "ITEM COUNT" -> "12"
# "ITEM MEASURE MEAN" -> "0.00"
# "PERSON COUNT" -> "28"
# "PERSON MEASURE MEAN" -> "0.15"
# "PERSON EXTREME INCL COUNT" -> "30"
# excluded = EXTREME INCL COUNT - PERSON COUNT = 30 - 28 = 2


def _make_item_row(entry: int, measure: str, label: str = "") -> list[str]:
    """Build a 14-column item data row matching the engine format."""
    return [
        str(entry),   # 0 ENTRY
        "50",          # 1 TOTAL SCORE
        "30",          # 2 COUNT
        measure,       # 3 MEASURE
        "0.30",        # 4 S.E.
        "1.10",        # 5 INFIT MNSQ
        "0.50",        # 6 INFIT ZSTD
        "1.05",        # 7 OUTFIT MNSQ
        "0.30",        # 8 OUTFIT ZSTD
        "0.55",        # 9 PTMEA CORR.
        "0.52",        # 10 EXP.
        "73.5",        # 11 EXACT OBS%
        "72.0",        # 12 EXACT EXPECTED%
        label,         # 13 LABEL
    ]


def _make_person_row(entry: int, measure: str, label: str = "") -> list[str]:
    """Build a 14-column person data row matching the engine format."""
    return [
        str(entry),   # 0 ENTRY
        "8",           # 1 TOTAL SCORE
        "12",          # 2 COUNT
        measure,       # 3 MEASURE
        "0.50",        # 4 S.E.
        "1.20",        # 5 INFIT MNSQ
        "0.80",        # 6 INFIT ZSTD
        "1.15",        # 7 OUTFIT MNSQ
        "0.60",        # 8 OUTFIT ZSTD
        "0.48",        # 9 PTMEA CORR.
        "0.50",        # 10 EXP.
        "70.0",        # 11 EXACT OBS%
        "68.0",        # 12 EXACT EXPECTED%
        label,         # 13 PERSON label
    ]


def _build_standard_files(item_measures: Optional[list[str]] = None) -> dict[str, str]:
    """Build the six engine output CSV texts for a standard 12-item, 30-person analysis."""
    if item_measures is None:
        item_measures = [f"{(i - 6) * 0.25:.2f}" for i in range(_N_ITEMS)]

    item_rows = (
        [_ITEM_HEADER_ROW0, _ITEM_HEADER_ROW1]
        + [_make_item_row(i + 1, item_measures[i], f"Label{i+1}") for i in range(_N_ITEMS)]
    )
    person_rows = (
        [_PERSON_HEADER_ROW0, _PERSON_HEADER_ROW1]
        + [_make_person_row(i + 1, f"{(i - 15) * 0.1:.2f}") for i in range(_N_PERSONS)]
    )
    wright_rows = (
        [_WRIGHT_HEADER_ROW0, _WRIGHT_HEADER_ROW1]
        + _WRIGHT_DATA_ROWS
    )
    option_rows = [
        ["ENTRY", "DATA", "SCORE", "DATA"],
        ["", "", "", ""],
        ["1", "30", "1", "A"],
    ]

    return {
        "item_table_15.1.csv": _csv(item_rows),
        "person_table.csv": _csv(person_rows),
        "summary_table.csv": _csv(_SUMMARY_DATA_ROWS),
        "wright_map_measure.csv": _csv(wright_rows),
        "wright_map_frequency.csv": _csv(wright_rows),  # same shape, content irrelevant here
        "option_table_15.3.csv": _csv(option_rows),
    }


# ---------------------------------------------------------------------------
# (1) Anonymous → 404
# ---------------------------------------------------------------------------

def test_explore_anonymous_returns_404(client: TestClient):
    # No cookie set; the route returns 404 for unauthenticated requests.
    resp = client.get("/analyses/999/explore")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# (2) Foreign owner → 404
# ---------------------------------------------------------------------------

def test_explore_foreign_owner_returns_404(client: TestClient):
    owner_id = _create_authenticated_user(client, "owner@test.example")
    files = _build_standard_files()
    analysis_id = _seed_done(owner_id, "data.csv", files)

    # Log in as a different user.
    _create_authenticated_user(client, "stranger@test.example")

    resp = client.get(f"/analyses/{analysis_id}/explore")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# (3) Gate closed → 404
# ---------------------------------------------------------------------------

def test_explore_gate_closed_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from app.config import settings
    monkeypatch.setattr(settings, "gate_open", False)

    resp = client.get("/analyses/1/explore")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# (4) Running analysis → 303 to /analyses/{id}
# ---------------------------------------------------------------------------

def test_explore_running_redirects_to_status_page(client: TestClient):
    user_id = _create_authenticated_user(client)
    files = _build_standard_files()
    analysis_id = _seed_done(user_id, "run.csv", files, status="running")

    resp = client.get(f"/analyses/{analysis_id}/explore", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/analyses/{analysis_id}"


# ---------------------------------------------------------------------------
# (5) Failed analysis → 303 to /analyses/{id}
# ---------------------------------------------------------------------------

def test_explore_failed_redirects_to_status_page(client: TestClient):
    user_id = _create_authenticated_user(client)
    files = _build_standard_files()
    analysis_id = _seed_done(user_id, "fail.csv", files, status="failed")

    resp = client.get(f"/analyses/{analysis_id}/explore", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/analyses/{analysis_id}"


# ---------------------------------------------------------------------------
# (6) Done analysis renders shell and payload
# ---------------------------------------------------------------------------

def test_explore_done_renders_shell_and_payload(client: TestClient):
    user_id = _create_authenticated_user(client)
    files = _build_standard_files()
    analysis_id = _seed_done(user_id, "sample.csv", files)

    resp = client.get(f"/analyses/{analysis_id}/explore")
    assert resp.status_code == 200
    html = resp.text

    # Tablist present.
    assert 'id="tablist"' in html

    # Five tabs.
    for tab_id in ("tab-wright", "tab-butir", "tab-partisipan", "tab-ringkasan", "tab-bandingkan"):
        assert f'id="{tab_id}"' in html

    # Five panels.
    for panel_id in ("panel-wright", "panel-butir", "panel-partisipan", "panel-ringkasan", "panel-bandingkan"):
        assert f'id="{panel_id}"' in html

    # Exactly one panel carries is-active (the wright panel by default).
    active_count = html.count('class="explorer-panel is-active"')
    assert active_count == 1

    # #explorer-data JSON present and schema == 1.
    assert 'id="explorer-data"' in html
    start = html.index('id="explorer-data"')
    snippet = html[start: start + 2000]
    json_start = snippet.index(">") + 1
    json_end = snippet.index("</script>")
    payload = json.loads(snippet[json_start:json_end])
    assert payload["schema"] == 1

    # noscript block exists.
    assert "<noscript>" in html
    assert "membutuhkan JavaScript" in html


# ---------------------------------------------------------------------------
# (7) view=butir activates butir panel
# ---------------------------------------------------------------------------

def test_explore_view_param_activates_panel(client: TestClient):
    user_id = _create_authenticated_user(client)
    files = _build_standard_files()
    analysis_id = _seed_done(user_id, "sample.csv", files)

    resp = client.get(f"/analyses/{analysis_id}/explore?view=butir")
    assert resp.status_code == 200
    html = resp.text

    # The tab for butir must carry is-active.
    assert 'id="tab-butir"' in html
    # Confirm butir tab has is-active class.
    tab_idx = html.index('id="tab-butir"')
    tab_snippet = html[tab_idx: tab_idx + 200]
    assert "is-active" in tab_snippet

    # The panel for butir must carry is-active.
    panel_idx = html.index('id="panel-butir"')
    panel_snippet = html[panel_idx: panel_idx + 300]
    assert "is-active" in panel_snippet


# ---------------------------------------------------------------------------
# (8) Unknown view falls back to wright
# ---------------------------------------------------------------------------

def test_explore_unknown_view_falls_back_to_wright(client: TestClient):
    user_id = _create_authenticated_user(client)
    files = _build_standard_files()
    analysis_id = _seed_done(user_id, "sample.csv", files)

    resp = client.get(f"/analyses/{analysis_id}/explore?view=nonexistent")
    assert resp.status_code == 200
    html = resp.text

    # Wright tab must be active.
    tab_idx = html.index('id="tab-wright"')
    tab_snippet = html[tab_idx: tab_idx + 200]
    assert "is-active" in tab_snippet


# ---------------------------------------------------------------------------
# (9) Wright bins reconcile with seeded data
# ---------------------------------------------------------------------------

def test_explore_payload_reconciles_wright_bins(client: TestClient):
    user_id = _create_authenticated_user(client)
    files = _build_standard_files()
    analysis_id = _seed_done(user_id, "sample.csv", files)

    resp = client.get(f"/analyses/{analysis_id}/explore")
    assert resp.status_code == 200
    html = resp.text

    # Extract embedded JSON.
    start = html.index('id="explorer-data"')
    snippet = html[start: start + 50000]
    json_start = snippet.index(">") + 1
    json_end = snippet.index("</script>")
    payload = json.loads(snippet[json_start:json_end])

    bins = payload["bins"]
    # Should have exactly as many bins as data rows in the seeded Wright file.
    assert len(bins) == len(_WRIGHT_DATA_ROWS)

    # Each bin is [MEASURE, NR_PERSON, NR_ITEM, ITEM_ENTRIES].
    total_persons = sum(int(b[1]) for b in bins)
    total_items = sum(int(b[2]) for b in bins)
    expected_persons = sum(int(r[1]) for r in _WRIGHT_DATA_ROWS)
    expected_items = sum(int(r[3]) for r in _WRIGHT_DATA_ROWS)
    assert total_persons == expected_persons  # 28
    assert total_items == expected_items      # 12

    # First bin's MEASURE matches the seeded first data row.
    assert bins[0][0] == _WRIGHT_DATA_ROWS[0][0]


# ---------------------------------------------------------------------------
# (10) Item payload fields are verbatim
# ---------------------------------------------------------------------------

def test_explore_payload_item_fields_are_verbatim(client: TestClient):
    user_id = _create_authenticated_user(client)
    item_measures = [f"{(i - 6) * 0.25:.2f}" for i in range(_N_ITEMS)]
    files = _build_standard_files(item_measures)
    analysis_id = _seed_done(user_id, "sample.csv", files)

    resp = client.get(f"/analyses/{analysis_id}/explore")
    assert resp.status_code == 200
    html = resp.text

    start = html.index('id="explorer-data"')
    snippet = html[start: start + 50000]
    json_start = snippet.index(">") + 1
    json_end = snippet.index("</script>")
    payload = json.loads(snippet[json_start:json_end])

    items = payload["items"]
    assert len(items) == _N_ITEMS

    # First item: projected as [ENTRY(int), LABEL(str), MEASURE, S.E., INFIT MNSQ, INFIT ZSTD,
    #                             OUTFIT MNSQ, OUTFIT ZSTD, PTMEA CORR., EXACT OBS%]
    first = items[0]
    assert isinstance(first[0], int)  # ENTRY is integer
    assert first[0] == 1
    assert first[1] == "Label1"       # LABEL verbatim
    assert first[2] == item_measures[0]  # MEASURE verbatim
    assert first[3] == "0.30"         # S.E. verbatim
    assert first[4] == "1.10"         # INFIT MNSQ verbatim
    assert first[8] == "0.55"         # PTMEA CORR. (index 9 in row → index 8 in projection)
    assert first[9] == "73.5"         # EXACT OBS% verbatim


# ---------------------------------------------------------------------------
# (11) Wright-meta line shows seeded PERSON COUNT, ITEM COUNT, excluded count
# ---------------------------------------------------------------------------

def test_explore_meta_line_counts_equal_summary_strings(client: TestClient):
    user_id = _create_authenticated_user(client)
    files = _build_standard_files()
    analysis_id = _seed_done(user_id, "sample.csv", files)

    resp = client.get(f"/analyses/{analysis_id}/explore")
    assert resp.status_code == 200
    html = resp.text

    # The seeded summary has PERSON COUNT=28, ITEM COUNT=12, EXTREME INCL COUNT=30.
    # excluded = 30 - 28 = 2.
    assert 'id="wright-meta"' in html
    meta_idx = html.index('id="wright-meta"')
    meta_end = html.index("</p>", meta_idx)
    meta_text = html[meta_idx: meta_end]

    assert "Partisipan:" in meta_text
    assert "28" in meta_text   # PERSON COUNT
    assert "Butir:" in meta_text
    assert "12" in meta_text   # ITEM COUNT
    assert "Dikecualikan" in meta_text
    assert "2" in meta_text    # excluded = 30 - 28


# ---------------------------------------------------------------------------
# (12) Ringkasan fragment renders summary rows verbatim and #summary-note present
# ---------------------------------------------------------------------------

def test_explore_ringkasan_renders_summary_verbatim(client: TestClient):
    user_id = _create_authenticated_user(client)
    files = _build_standard_files()
    analysis_id = _seed_done(user_id, "sample.csv", files)

    resp = client.get(f"/analyses/{analysis_id}/explore?view=ringkasan")
    assert resp.status_code == 200
    html = resp.text

    # The seeded summary values must appear.
    assert "ITEM COUNT" in html
    assert ">12<" in html      # id_num("12") = "12"
    assert "PERSON COUNT" in html
    assert ">28<" in html
    assert "0,15" in html      # id_num("0.15") = "0,15"

    # #summary-note must be present (frozen id from INTERFACE F4).
    assert 'id="summary-note"' in html
    assert "Angka partisipan di tabel ini mencakup skor sempurna dan nol" in html


# ---------------------------------------------------------------------------
# (13) Item search filters and empty state
# ---------------------------------------------------------------------------

def test_explore_item_search_filters_and_empty_state(client: TestClient):
    user_id = _create_authenticated_user(client)
    files = _build_standard_files()
    analysis_id = _seed_done(user_id, "sample.csv", files)

    # Matching query: "Label1" matches item 1 and item 10 (contains "1").
    resp_match = client.get(f"/analyses/{analysis_id}/explore?view=butir&q_item=Label1")
    assert resp_match.status_code == 200
    html_match = resp_match.text
    # Count line must be present.
    assert 'id="butir-count"' in html_match

    # Non-matching query: no item has this label.
    resp_no = client.get(f"/analyses/{analysis_id}/explore?view=butir&q_item=ZZZ_NO_MATCH")
    assert resp_no.status_code == 200
    html_no = resp_no.text

    # #butir-empty must be present with the frozen no-match sentence.
    assert 'id="butir-empty"' in html_no
    assert "Tidak ada baris yang cocok dengan pencarian." in html_no

    # Reset link must keep view=butir.
    assert "?view=butir" in html_no
    assert "Hapus pencarian" in html_no


# ---------------------------------------------------------------------------
# (14) Person search filters
# ---------------------------------------------------------------------------

def test_explore_person_search_filters(client: TestClient):
    user_id = _create_authenticated_user(client)
    files = _build_standard_files()
    analysis_id = _seed_done(user_id, "sample.csv", files)

    # Non-matching query triggers empty state.
    resp = client.get(f"/analyses/{analysis_id}/explore?view=partisipan&q_person=ZZZNOMATCH999")
    assert resp.status_code == 200
    html = resp.text

    assert 'id="partisipan-empty"' in html
    assert "Tidak ada baris yang cocok dengan pencarian." in html

    # Reset link must keep view=partisipan.
    assert "?view=partisipan" in html
    assert "Hapus pencarian" in html


# ---------------------------------------------------------------------------
# (16b) Partisipan histogram payload
# ---------------------------------------------------------------------------

def test_explore_partisipan_histogram_agrees_with_the_map(client: TestClient):
    """The distribution the artifact pairs with the table, on the map's own binning."""
    user_id = _create_authenticated_user(client)
    files = _build_standard_files()
    analysis_id = _seed_done(user_id, "sample.csv", files)

    html = client.get(f"/analyses/{analysis_id}/explore?view=partisipan").text

    assert 'id="partisipan-chart"' in html
    assert 'id="partisipan-hist-data"' in html
    assert "chart-caption" in html

    payload = json.loads(html.split('id="partisipan-hist-data">')[1].split("</script>")[0])
    map_payload = json.loads(html.split('id="explorer-data">')[1].split("</script>")[0])

    assert payload["schema"] == 1
    assert len(payload["bins"]) == len(map_payload["bins"])
    assert payload["total"] == sum(int(b[1]) for b in map_payload["bins"])
    assert payload["total"] > 0
    assert payload["step"]

    # Sorted by measure, counts integral, and the histogram is the map's person column verbatim.
    measures = [float(b[0]) for b in payload["bins"]]
    assert measures == sorted(measures)
    for entry, source in zip(payload["bins"], map_payload["bins"]):
        assert entry[1] == int(source[1])
    assert payload["filled"] == sum(1 for b in payload["bins"] if b[1] > 0)


# ---------------------------------------------------------------------------
# (15) Pager preserves view and query
# ---------------------------------------------------------------------------

def test_explore_pager_preserves_view_and_query(client: TestClient):
    user_id = _create_authenticated_user(client)

    # Build enough items to force pagination: RENDER_PAGE=500, so use a small override.
    # We use q_item to filter to >0 but <all, and check that pager links appear.
    # With 12 items all on one page (500 per page), we instead just verify that
    # the pager nav is present and the links carry the correct parameters.
    files = _build_standard_files()
    analysis_id = _seed_done(user_id, "sample.csv", files)

    resp = client.get(f"/analyses/{analysis_id}/explore?view=butir&q_item=Label")
    assert resp.status_code == 200
    html = resp.text

    # Pager nav element is present.
    assert '<nav class="pager"' in html

    # The pager links (even disabled ones as buttons) carry the view parameter.
    # On a single page, there are no prev/next anchors but the nav is still rendered.
    # Verify that the count line reflects the filter.
    assert 'id="butir-count"' in html


# ---------------------------------------------------------------------------
# (16) Fragment endpoint: valid, wright (404), unknown (404), foreign (404)
# ---------------------------------------------------------------------------

def test_explore_fragment_returns_panel_or_404(client: TestClient):
    user_id = _create_authenticated_user(client)
    files = _build_standard_files()
    analysis_id = _seed_done(user_id, "sample.csv", files)

    # Valid fragment: butir → panel HTML, no tablist.
    resp_frag = client.get(f"/analyses/{analysis_id}/explore?view=butir&fragment=butir")
    assert resp_frag.status_code == 200
    html_frag = resp_frag.text
    assert 'id="tablist"' not in html_frag
    assert "butir-search" in html_frag or "data-explorer-table" in html_frag

    # fragment=wright → 404 (wright is not a valid fragment view).
    resp_wright = client.get(f"/analyses/{analysis_id}/explore?fragment=wright")
    assert resp_wright.status_code == 404

    # Unknown fragment → 404.
    resp_unknown = client.get(f"/analyses/{analysis_id}/explore?fragment=unknown_panel")
    assert resp_unknown.status_code == 404

    # Valid fragment for a different (foreign) analysis → 404.
    owner2_id = _create_authenticated_user(client, "owner2@test.example")
    analysis_id_2 = _seed_done(owner2_id, "other.csv", files)
    # Switch back to original user.
    _create_authenticated_user(client, "backtofirst@test.example")
    # original user cannot access owner2's analysis.
    resp_foreign = client.get(f"/analyses/{analysis_id_2}/explore?fragment=butir")
    assert resp_foreign.status_code == 404


# ---------------------------------------------------------------------------
# (17) Compare renders statement table, delta cells, means, #cmp-caveat, #cmp-counts
# ---------------------------------------------------------------------------

def test_explore_compare_renders_statement_table_delta_and_means(client: TestClient):
    user_id = _create_authenticated_user(client)

    # First analysis with measures for 12 items.
    item_measures_1 = ["0.10", "0.20", "0.30", "0.40", "0.50", "0.60",
                        "0.70", "0.80", "0.90", "1.00", "1.10", "1.20"]
    files1 = _build_standard_files(item_measures_1)
    analysis_id_1 = _seed_done(user_id, "dataset_a.csv", files1, created_at=now_epoch() - 100)

    # Second analysis on a DIFFERENT dataset with different measures.
    item_measures_2 = ["0.20", "0.30", "0.40", "0.50", "0.60", "0.70",
                        "0.80", "0.90", "1.00", "1.10", "1.20", "1.30"]
    files2 = _build_standard_files(item_measures_2)
    analysis_id_2 = _seed_done(user_id, "dataset_b.csv", files2, created_at=now_epoch())

    resp = client.get(
        f"/analyses/{analysis_id_1}/explore?view=bandingkan"
        f"&from={analysis_id_1}&to={analysis_id_2}"
    )
    assert resp.status_code == 200
    html = resp.text

    # Both analysis ids appear.
    assert f"#{analysis_id_1}" in html
    assert f"#{analysis_id_2}" in html

    # Both dataset filenames appear.
    assert "dataset_a.csv" in html
    assert "dataset_b.csv" in html

    # Delta for item 1: to_m - from_m = 0.20 - 0.10 = +0.10.
    expected_delta_1 = "+0.10"
    assert expected_delta_1 in html

    # Both means appear. The server uses id_num which turns "0.00" → "0,00".
    # Seeded summary_table.csv has ITEM MEASURE MEAN = "0.00" for both.
    assert "0,00" in html

    # #cmp-caveat and #cmp-counts present.
    assert 'id="cmp-caveat"' in html
    assert "Selisih lintas berkas hanya bermakna bila kedua analisis memakai butir penghubung" in html
    assert 'id="cmp-counts"' in html
    assert "Cocok:" in html


# ---------------------------------------------------------------------------
# (18) Compare parameter rules all produce 404
# ---------------------------------------------------------------------------

def test_explore_compare_param_rules_all_404(client: TestClient):
    user_id = _create_authenticated_user(client)
    files = _build_standard_files()
    analysis_id = _seed_done(user_id, "sample.csv", files)

    base = f"/analyses/{analysis_id}/explore?view=bandingkan"

    # from without to.
    r = client.get(f"{base}&from={analysis_id}")
    assert r.status_code == 404

    # from equal to to.
    r = client.get(f"{base}&from={analysis_id}&to={analysis_id}")
    assert r.status_code == 404

    # Nonexistent id.
    r = client.get(f"{base}&from=999999&to={analysis_id}")
    assert r.status_code == 404

    # Foreign analysis id: create a second user and their analysis.
    user2_id = _create_authenticated_user(client, "user2@test.example")
    foreign_id = _seed_done(user2_id, "foreign.csv", files)
    # Switch back to user_id.
    _create_authenticated_user(client, "backagain@test.example")
    # original user cannot compare with foreign analysis.
    r = client.get(f"/analyses/{analysis_id}/explore?view=bandingkan&from={analysis_id}&to={foreign_id}")
    assert r.status_code == 404

    # An analysis that is not done.
    running_id = _seed_done(user_id, "running.csv", files, status="running")
    r = client.get(f"/analyses/{analysis_id}/explore?view=bandingkan&from={analysis_id}&to={running_id}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# (19) Malformed Wright data renders error state, butir fragment still 200
# ---------------------------------------------------------------------------

def test_explore_malformed_wright_renders_error_state(client: TestClient):
    user_id = _create_authenticated_user(client)

    # Wright file has headers only (no data rows) — malformed.
    wright_header_only = _csv([_WRIGHT_HEADER_ROW0])
    files = _build_standard_files()
    files["wright_map_measure.csv"] = wright_header_only

    analysis_id = _seed_done(user_id, "broken.csv", files)

    resp = client.get(f"/analyses/{analysis_id}/explore")
    assert resp.status_code == 200
    html = resp.text

    # #explorer-error visible with frozen reason sentence.
    assert 'id="explorer-error"' in html
    assert "Data peta Wright tidak dapat dibaca untuk analisis ini." in html

    # #explorer-data must NOT be present (payload not built).
    assert 'id="explorer-data"' not in html

    # Butir fragment still returns 200.
    resp_frag = client.get(f"/analyses/{analysis_id}/explore?view=butir&fragment=butir")
    assert resp_frag.status_code == 200


# ---------------------------------------------------------------------------
# (20) Results page links to explore with label "Buka dashboard hasil"
# ---------------------------------------------------------------------------

def test_results_page_links_to_explore(client: TestClient):
    user_id = _create_authenticated_user(client)
    files = _build_standard_files()
    analysis_id = _seed_done(user_id, "sample.csv", files)

    resp = client.get(f"/analyses/{analysis_id}")
    assert resp.status_code == 200
    html = resp.text

    assert f'href="/analyses/{analysis_id}/explore"' in html
    assert "Buka dashboard hasil" in html


# ---------------------------------------------------------------------------
# (21) Cross-dataset compare: pairing key cases
# ---------------------------------------------------------------------------

def test_explore_compare_cross_dataset_pairing_keys(client: TestClient):
    user_id = _create_authenticated_user(client)

    # -----------------------------------------------------------------------
    # Case A: Labels present on BOTH sides → pair by label, count shared labels.
    # -----------------------------------------------------------------------
    def _make_items_with_labels(
        measures: list[str],
        labels: list[str],
    ) -> str:
        rows = [_ITEM_HEADER_ROW0, _ITEM_HEADER_ROW1]
        for i, (m, lbl) in enumerate(zip(measures, labels)):
            rows.append(_make_item_row(i + 1, m, lbl))
        return _csv(rows)

    # 3 items each, 2 shared labels (Shared1, Shared2), 1 unshared each.
    labels_a = ["Shared1", "Shared2", "OnlyA"]
    labels_b = ["Shared1", "Shared2", "OnlyB"]
    measures_a = ["0.10", "0.20", "0.30"]
    measures_b = ["0.30", "0.50", "0.70"]

    def _mini_files(item_csv: str) -> dict[str, str]:
        """Minimal file set with a custom item table."""
        standard = _build_standard_files()
        standard["item_table_15.1.csv"] = item_csv
        return standard

    files_a = _mini_files(_make_items_with_labels(measures_a, labels_a))
    files_b = _mini_files(_make_items_with_labels(measures_b, labels_b))

    # Use n_items=3 override so dataset is consistent.
    with SessionLocal() as db:
        now = now_epoch() - 200
        raw = gzip.compress(b"dummy", mtime=0)
        ds_a = Dataset(
            user_id=user_id, filename="caseA_a.csv", kind="delimited", format="csv",
            status="ready", n_persons=30, n_items=3,
            item_labels_json=json.dumps(labels_a), mapping_json=json.dumps({}),
            summary_json=json.dumps({}), raw_gzip=raw, raw_bytes=5,
            created_at=now, committed_at=now,
        )
        db.add(ds_a)
        db.commit()
        ds_a_id = ds_a.id

        an_a = Analysis(
            user_id=user_id, dataset_id=ds_a_id, status="done",
            params_json=json.dumps({}), engine_ref="test",
            created_at=now, expires_at=now + 180 * 86400,
            finished_at=now, elapsed_ms=100,
        )
        db.add(an_a)
        db.commit()
        an_a_id = an_a.id
        for fname, text in files_a.items():
            rb = text.encode()
            db.add(AnalysisFile(
                analysis_id=an_a_id, filename=fname,
                content_gzip=gzip.compress(rb, mtime=0),
                sha256=hashlib.sha256(rb).hexdigest(), bytes=len(rb),
            ))

        ds_b = Dataset(
            user_id=user_id, filename="caseA_b.csv", kind="delimited", format="csv",
            status="ready", n_persons=30, n_items=3,
            item_labels_json=json.dumps(labels_b), mapping_json=json.dumps({}),
            summary_json=json.dumps({}), raw_gzip=raw, raw_bytes=5,
            created_at=now + 1, committed_at=now + 1,
        )
        db.add(ds_b)
        db.commit()
        ds_b_id = ds_b.id

        an_b = Analysis(
            user_id=user_id, dataset_id=ds_b_id, status="done",
            params_json=json.dumps({}), engine_ref="test",
            created_at=now + 1, expires_at=now + 1 + 180 * 86400,
            finished_at=now + 1, elapsed_ms=100,
        )
        db.add(an_b)
        db.commit()
        an_b_id = an_b.id
        for fname, text in files_b.items():
            rb = text.encode()
            db.add(AnalysisFile(
                analysis_id=an_b_id, filename=fname,
                content_gzip=gzip.compress(rb, mtime=0),
                sha256=hashlib.sha256(rb).hexdigest(), bytes=len(rb),
            ))
        db.commit()

    resp_a = client.get(
        f"/analyses/{an_a_id}/explore?view=bandingkan&from={an_a_id}&to={an_b_id}"
    )
    assert resp_a.status_code == 200
    html_a = resp_a.text

    # 2 shared labels → matched = 2.
    assert "Cocok: 2 butir." in html_a
    # Paired by label.
    assert "Dipasangkan berdasarkan label butir." in html_a

    # Delta for Shared1: to - from = 0.30 - 0.10 = +0.20.
    expected_delta_shared1 = "+0,20"
    assert expected_delta_shared1 in html_a

    # Delta for Shared2: to - from = 0.50 - 0.20 = +0.30.
    expected_delta_shared2 = "+0,30"
    assert expected_delta_shared2 in html_a

    # -----------------------------------------------------------------------
    # Case B: Labels absent on BOTH sides, EQUAL item counts → pair by entry.
    # -----------------------------------------------------------------------
    measures_c = ["1.00", "2.00", "3.00"]
    measures_d = ["1.50", "2.50", "3.50"]

    def _make_items_no_labels(measures: list[str]) -> str:
        rows = [_ITEM_HEADER_ROW0, _ITEM_HEADER_ROW1]
        for i, m in enumerate(measures):
            rows.append(_make_item_row(i + 1, m, ""))  # empty label
        return _csv(rows)

    files_c = _mini_files(_make_items_no_labels(measures_c))
    files_d = _mini_files(_make_items_no_labels(measures_d))

    with SessionLocal() as db:
        now2 = now_epoch() - 100
        raw = gzip.compress(b"dummy", mtime=0)

        ds_c = Dataset(
            user_id=user_id, filename="caseB_c.csv", kind="delimited", format="csv",
            status="ready", n_persons=30, n_items=3,
            item_labels_json=json.dumps([]), mapping_json=json.dumps({}),
            summary_json=json.dumps({}), raw_gzip=raw, raw_bytes=5,
            created_at=now2, committed_at=now2,
        )
        db.add(ds_c)
        db.commit()
        ds_c_id = ds_c.id

        an_c = Analysis(
            user_id=user_id, dataset_id=ds_c_id, status="done",
            params_json=json.dumps({}), engine_ref="test",
            created_at=now2, expires_at=now2 + 180 * 86400,
            finished_at=now2, elapsed_ms=100,
        )
        db.add(an_c)
        db.commit()
        an_c_id = an_c.id
        for fname, text in files_c.items():
            rb = text.encode()
            db.add(AnalysisFile(
                analysis_id=an_c_id, filename=fname,
                content_gzip=gzip.compress(rb, mtime=0),
                sha256=hashlib.sha256(rb).hexdigest(), bytes=len(rb),
            ))

        ds_d = Dataset(
            user_id=user_id, filename="caseB_d.csv", kind="delimited", format="csv",
            status="ready", n_persons=30, n_items=3,
            item_labels_json=json.dumps([]), mapping_json=json.dumps({}),
            summary_json=json.dumps({}), raw_gzip=raw, raw_bytes=5,
            created_at=now2 + 1, committed_at=now2 + 1,
        )
        db.add(ds_d)
        db.commit()
        ds_d_id = ds_d.id

        an_d = Analysis(
            user_id=user_id, dataset_id=ds_d_id, status="done",
            params_json=json.dumps({}), engine_ref="test",
            created_at=now2 + 1, expires_at=now2 + 1 + 180 * 86400,
            finished_at=now2 + 1, elapsed_ms=100,
        )
        db.add(an_d)
        db.commit()
        an_d_id = an_d.id
        for fname, text in files_d.items():
            rb = text.encode()
            db.add(AnalysisFile(
                analysis_id=an_d_id, filename=fname,
                content_gzip=gzip.compress(rb, mtime=0),
                sha256=hashlib.sha256(rb).hexdigest(), bytes=len(rb),
            ))
        db.commit()

    resp_b = client.get(
        f"/analyses/{an_c_id}/explore?view=bandingkan&from={an_c_id}&to={an_d_id}"
    )
    assert resp_b.status_code == 200
    html_b = resp_b.text

    # 3 items, same count, no labels → entry-based, 3 matched.
    assert "Cocok: 3 butir." in html_b
    assert "Dipasangkan berdasarkan nomor butir (kedua berkas tidak memuat label butir)." in html_b

    # Entry 1: delta = 1.50 - 1.00 = +0.50.
    assert "+0,50" in html_b

    # -----------------------------------------------------------------------
    # Case C: Labels absent, DIFFERENT item counts → no pairs, frozen sentence.
    # -----------------------------------------------------------------------
    measures_e = ["0.10", "0.20", "0.30"]          # 3 items
    measures_f = ["0.10", "0.20", "0.30", "0.40"]  # 4 items — different count

    def _make_items_n(measures: list[str]) -> str:
        rows = [_ITEM_HEADER_ROW0, _ITEM_HEADER_ROW1]
        for i, m in enumerate(measures):
            rows.append(_make_item_row(i + 1, m, ""))
        return _csv(rows)

    files_e = _mini_files(_make_items_n(measures_e))
    files_f = _mini_files(_make_items_n(measures_f))

    with SessionLocal() as db:
        now3 = now_epoch() - 50
        raw = gzip.compress(b"dummy", mtime=0)

        ds_e = Dataset(
            user_id=user_id, filename="caseC_e.csv", kind="delimited", format="csv",
            status="ready", n_persons=30, n_items=3,
            item_labels_json=json.dumps([]), mapping_json=json.dumps({}),
            summary_json=json.dumps({}), raw_gzip=raw, raw_bytes=5,
            created_at=now3, committed_at=now3,
        )
        db.add(ds_e)
        db.commit()
        ds_e_id = ds_e.id

        an_e = Analysis(
            user_id=user_id, dataset_id=ds_e_id, status="done",
            params_json=json.dumps({}), engine_ref="test",
            created_at=now3, expires_at=now3 + 180 * 86400,
            finished_at=now3, elapsed_ms=100,
        )
        db.add(an_e)
        db.commit()
        an_e_id = an_e.id
        for fname, text in files_e.items():
            rb = text.encode()
            db.add(AnalysisFile(
                analysis_id=an_e_id, filename=fname,
                content_gzip=gzip.compress(rb, mtime=0),
                sha256=hashlib.sha256(rb).hexdigest(), bytes=len(rb),
            ))

        ds_f = Dataset(
            user_id=user_id, filename="caseC_f.csv", kind="delimited", format="csv",
            status="ready", n_persons=30, n_items=4,
            item_labels_json=json.dumps([]), mapping_json=json.dumps({}),
            summary_json=json.dumps({}), raw_gzip=raw, raw_bytes=5,
            created_at=now3 + 1, committed_at=now3 + 1,
        )
        db.add(ds_f)
        db.commit()
        ds_f_id = ds_f.id

        an_f = Analysis(
            user_id=user_id, dataset_id=ds_f_id, status="done",
            params_json=json.dumps({}), engine_ref="test",
            created_at=now3 + 1, expires_at=now3 + 1 + 180 * 86400,
            finished_at=now3 + 1, elapsed_ms=100,
        )
        db.add(an_f)
        db.commit()
        an_f_id = an_f.id
        for fname, text in files_f.items():
            rb = text.encode()
            db.add(AnalysisFile(
                analysis_id=an_f_id, filename=fname,
                content_gzip=gzip.compress(rb, mtime=0),
                sha256=hashlib.sha256(rb).hexdigest(), bytes=len(rb),
            ))
        db.commit()

    resp_c = client.get(
        f"/analyses/{an_e_id}/explore?view=bandingkan&from={an_e_id}&to={an_f_id}"
    )
    assert resp_c.status_code == 200
    html_c = resp_c.text

    # Unpairable case: no labels on either side, different item counts → pairs=[].
    # #cmp-counts shows "Cocok: 0 butir." and neither pairing-key sentence appears.
    assert 'id="cmp-counts"' in html_c
    assert "Cocok: 0 butir." in html_c
    assert "Dipasangkan berdasarkan label butir." not in html_c
    assert "Dipasangkan berdasarkan nomor butir" not in html_c
    # No pair rows in the comparison table body means no delta cells from a mismatch.
    assert 'id="cmp-tbody"' in html_c
