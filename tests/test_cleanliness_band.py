"""F14: the Kebersihan Data band on the analysis page (PLAN_F14.md).

Five checks over the frozen contract:
1. A completed analysis whose respondent table carries STATUS renders the exact
   counts of the fixture rows and draws the band from the context geometry.
2. The same page carries no em dash.
3. A result whose respondent table lacks the STATUS header renders the honest note
   and no chips.
4. An analysis still running renders neither the band nor the note.
5. The band's aria-label carries the three counts as words.

The analysis rows are seeded the same way tests/test_explorer_routes.py seeds them
(no engine run); only the respondent table changes, to carry or omit the STATUS column.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from tests.test_analysis_routes import _create_authenticated_user
from tests.test_explorer_routes import (
    _ITEM_HEADER_ROW0,
    _ITEM_HEADER_ROW1,
    _PERSON_HEADER_ROW0,
    _PERSON_HEADER_ROW1,
    _WRIGHT_HEADER_ROW0,
    _WRIGHT_HEADER_ROW1,
    _csv,
    _make_item_row,
    _make_person_row,
    _seed_done,
)

# One completed run: 3 kept, 1 deleted, 1 extreme low, 1 extreme high, out of 6 rows.
_STATUSES = ["kept", "kept", "kept", "deleted", "extreme_min", "extreme_max"]
_TOTAL = len(_STATUSES)
_KEPT = 3
_DELETED = 1
_EKSTREM = 2
_BUTIR_DIHAPUS = 2
_BAND_X0, _BAND_X1 = 10.0, 550.0


def _width(value: int) -> float:
    """Same proportional rule as app.analyze._clean_audit, in a 0 0 560 76 box."""
    return round((_BAND_X1 - _BAND_X0) * value / _TOTAL, 2)


def _person_table(with_status: bool) -> list[list[str]]:
    if with_status:
        rows = [_PERSON_HEADER_ROW0 + ["STATUS"], _PERSON_HEADER_ROW1 + ["STATUS"]]
        for i, status in enumerate(_STATUSES):
            rows.append(_make_person_row(i + 1, "0.00", f"P{i + 1}") + [status])
        return rows
    rows = [list(_PERSON_HEADER_ROW0), list(_PERSON_HEADER_ROW1)]
    for i in range(_KEPT):
        rows.append(_make_person_row(i + 1, "0.00", f"P{i + 1}"))
    return rows


def _files(with_status: bool) -> dict[str, str]:
    return {
        "item_table_15.1.csv": _csv(
            [_ITEM_HEADER_ROW0, _ITEM_HEADER_ROW1, _make_item_row(1, "0.00", "I1")]
        ),
        "option_table_15.3.csv": _csv([["ENTRY", "DATA"], ["", ""]]),
        "person_table.csv": _csv(_person_table(with_status)),
        "summary_table.csv": _csv(
            [
                ["SECTION", "STATISTIC", "VALUE"],
                ["PERSON", "COUNT", str(_KEPT)],
                ["COUNTS", "ITEM DELETED", str(_BUTIR_DIHAPUS)],
            ]
        ),
        "wright_map_measure.csv": _csv([_WRIGHT_HEADER_ROW0, _WRIGHT_HEADER_ROW1]),
        "wright_map_frequency.csv": _csv([_WRIGHT_HEADER_ROW0, _WRIGHT_HEADER_ROW1]),
    }


def _seed_completed(
    client: TestClient,
    email: str,
    *,
    with_status: bool = True,
    status: str = "done",
) -> int:
    user_id = _create_authenticated_user(client, email=email)
    return _seed_done(user_id, "verba_bersih.csv", _files(with_status), status=status)


def _band_section(html: str) -> str:
    start = html.index('id="kebersihan"')
    end = html.index("</section>", start)
    return html[start:end]


def test_completed_analysis_renders_counts_and_context_geometry(client: TestClient):
    analysis_id = _seed_completed(client, "kebersihan_bersih@example.test")

    resp = client.get(f"/analyses/{analysis_id}/explore?view=ringkasan")
    assert resp.status_code == 200
    section = _band_section(resp.text)

    assert "Kebersihan Data" in section
    assert f"Komposisi {_TOTAL} baris yang dibaca mesin." in section

    # The three chips, in order, with the exact counts of the fixture rows.
    assert f"{_KEPT} dipakai" in section
    assert f"{_DELETED} dihapus" in section
    assert f"{_EKSTREM} ekstrem" in section
    assert section.index(f"{_KEPT} dipakai") < section.index(f"{_DELETED} dihapus")
    assert section.index(f"{_DELETED} dihapus") < section.index(f"{_EKSTREM} ekstrem")

    # The band's rect widths and x offsets are the context geometry, nothing invented.
    segments = re.findall(r'<rect[^>]*x="([^"]+)"[^>]*width="([^"]+)"', section)
    assert segments == [
        (str(_BAND_X0), str(_width(_KEPT))),
        (str(round(_BAND_X0 + _width(_KEPT), 2)), str(_width(_DELETED))),
        (str(round(_BAND_X1 - _width(_EKSTREM), 2)), str(_width(_EKSTREM))),
    ]

    # Percentages come straight from the context, comma separator.
    assert "50,0%" in section
    assert "16,7%" in section
    assert "33,3%" in section

    # The alert states what was removed and what was excluded, plus the dropped items.
    assert "alert alert--warn" in section
    assert (
        f"{_DELETED} baris dihapus lewat daftar hapus dan {_EKSTREM} baris dikecualikan "
        f"sebagai ekstrem (1 bawah, 1 atas). {_BUTIR_DIHAPUS} butir dibuang sebelum penilaian."
    ) in section


def test_band_carries_no_em_dash(client: TestClient):
    analysis_id = _seed_completed(client, "kebersihan_dash@example.test")

    resp = client.get(f"/analyses/{analysis_id}/explore?view=ringkasan")
    assert resp.status_code == 200
    assert "\u2014" not in resp.text


def test_without_status_header_renders_honest_note_and_no_chips(client: TestClient):
    analysis_id = _seed_completed(
        client, "kebersihan_tanpa_status@example.test", with_status=False
    )

    resp = client.get(f"/analyses/{analysis_id}/explore?view=ringkasan")
    assert resp.status_code == 200
    section = _band_section(resp.text)

    assert "Kebersihan Data" in section
    assert "Analisis ini dijalankan sebelum mesin mencatat kolom status" in section
    assert "Jalankan ulang analisis untuk melihatnya." in section

    # No zeros invented: no chips and no band when the column never existed.
    assert "chip--fit" not in section
    assert "chip--misfit" not in section
    assert "chip--warn" not in section
    assert "<rect" not in section


def test_running_analysis_renders_no_band_and_no_note(client: TestClient):
    analysis_id = _seed_completed(
        client, "kebersihan_berjalan@example.test", status="running"
    )

    resp = client.get(f"/analyses/{analysis_id}")
    assert resp.status_code == 200
    assert "Kebersihan Data" not in resp.text
    assert 'id="kebersihan"' not in resp.text
    assert "Analisis ini dijalankan sebelum mesin mencatat kolom status" not in resp.text


def test_band_aria_label_carries_the_three_counts_as_words(client: TestClient):
    analysis_id = _seed_completed(client, "kebersihan_aria@example.test")

    resp = client.get(f"/analyses/{analysis_id}/explore?view=ringkasan")
    assert resp.status_code == 200
    section = _band_section(resp.text)

    match = re.search(r'<svg[^>]*aria-label="([^"]+)"', section)
    assert match is not None
    label = match.group(1)
    assert f"{_KEPT} dipakai" in label
    assert f"{_DELETED} dihapus" in label
    assert f"{_EKSTREM} ekstrem" in label
