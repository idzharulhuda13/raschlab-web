"""F17-B: the Dipakai / Arsip mark on the pages that show it (PLAN_F17.md section 7).

Six checks over the frozen contract:
1. the analysis page of a marked run renders the Dipakai chip and a button whose hidden primary is 0;
2. the analysis page of an unmarked run whose sibling is marked renders Arsip and a hidden primary of 1;
3. the analysis page of a run whose dataset has no mark renders neither chip word;
4. the analyses list page marks exactly the marked row and gives the sibling's row the Arsip chip;
5. the compare view's options carry the Dipakai suffix on the marked run and Arsip on its sibling;
6. the three pages stay free of an em dash.

The rows are seeded straight from the models, the same way tests/test_mark_primary.py seeds them, and
the mark is written through the committed mark_analysis helper instead of being set by hand.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.analysis import mark_analysis
from app.auth import COOKIE_NAME
from app.db import SessionLocal
from app.models import Analysis, Dataset, SessionRow, User
from app.security import hash_token, new_token, now_epoch

DIPAKAI_CHIP = '<span class="chip chip--accent">Dipakai</span>'
ARSIP_CHIP = '<span class="chip chip--warn">Arsip</span>'
MIDDLE_DOT = "\u00b7"


def _login(client: TestClient, email: str) -> int:
    with SessionLocal() as db:
        now = now_epoch()
        user = User(
            email=email,
            email_normalized=email.lower().strip(),
            password_hash="hash-tiruan",
            created_at=now,
            verified_at=now,
        )
        db.add(user)
        db.commit()
        user_id = user.id

        token = new_token()
        db.add(
            SessionRow(
                user_id=user_id,
                token_hash=hash_token(token),
                created_at=now,
                expires_at=now + 86400 * 30,
            )
        )
        db.commit()

    client.cookies.set(COOKIE_NAME, token)
    return user_id


def _create_dataset(user_id: int, filename: str = "verba_ujian.csv") -> int:
    with SessionLocal() as db:
        now = now_epoch()
        dataset = Dataset(
            user_id=user_id,
            filename=filename,
            kind="delimited",
            format="csv",
            status="ready",
            n_persons=10,
            n_items=5,
            item_labels_json="[]",
            mapping_json="{}",
            summary_json="{}",
            raw_gzip=b"x",
            raw_bytes=1,
            created_at=now,
        )
        db.add(dataset)
        db.commit()
        return dataset.id


def _create_analysis(user_id: int, dataset_id: int, status: str = "done") -> int:
    with SessionLocal() as db:
        now = now_epoch()
        analysis = Analysis(
            user_id=user_id,
            dataset_id=dataset_id,
            status=status,
            params_json="{}",
            engine_ref="test-ref",
            created_at=now,
            expires_at=now + 180 * 86400,
            finished_at=now if status == "done" else None,
        )
        db.add(analysis)
        db.commit()
        return analysis.id


def _mark(analysis_id: int) -> None:
    with SessionLocal() as db:
        analysis = db.scalar(select(Analysis).where(Analysis.id == analysis_id))
        assert analysis is not None
        mark_analysis(db, analysis, True)


def _marked_pair(client: TestClient, email: str) -> tuple[int, int, int]:
    """A dataset with two completed runs, the older one marked as the version in use."""
    user_id = _login(client, email)
    dataset_id = _create_dataset(user_id)
    marked_id = _create_analysis(user_id, dataset_id)
    sibling_id = _create_analysis(user_id, dataset_id)
    _mark(marked_id)
    return dataset_id, marked_id, sibling_id


def test_marked_run_page_shows_dipakai_and_a_clear_button(client: TestClient):
    dataset_id, marked_id, sibling_id = _marked_pair(client, "tanda_dipakai@example.test")

    resp = client.get(f"/analyses/{marked_id}")
    assert resp.status_code == 200
    assert DIPAKAI_CHIP in resp.text

    # The button carries the mark already, so pressing it clears the mark (primary 0).
    assert 'name="primary" value="0"' in resp.text
    assert "Batalkan tanda dipakai" in resp.text
    assert ">Arsip<" not in resp.text


def test_sibling_of_a_marked_run_page_shows_arsip_and_a_mark_button(client: TestClient):
    dataset_id, marked_id, sibling_id = _marked_pair(client, "tanda_arsip@example.test")

    resp = client.get(f"/analyses/{sibling_id}")
    assert resp.status_code == 200
    assert ARSIP_CHIP in resp.text

    # This run is not the marked one, so pressing the button marks it (primary 1).
    assert 'name="primary" value="1"' in resp.text
    assert "Tandai sebagai versi dipakai" in resp.text
    assert ">Dipakai<" not in resp.text


def test_run_of_an_unmarked_dataset_page_shows_no_mark_chip(client: TestClient):
    user_id = _login(client, "tanda_belum@example.test")
    dataset_id = _create_dataset(user_id)
    analysis_id = _create_analysis(user_id, dataset_id)

    resp = client.get(f"/analyses/{analysis_id}")
    assert resp.status_code == 200
    assert "Dipakai" not in resp.text
    assert "Arsip" not in resp.text

    # The button is still there: nothing is marked, so it offers to mark this run.
    assert 'name="primary" value="1"' in resp.text


def test_analyses_list_chips_the_marked_row_and_the_sibling(client: TestClient):
    dataset_id, marked_id, sibling_id = _marked_pair(client, "daftar_tanda@example.test")

    resp = client.get("/analyses")
    assert resp.status_code == 200
    table = resp.text[resp.text.index("<table"): resp.text.index("</table>")]

    rows = table.split("<tr>")
    marked_row = next(r for r in rows if f'href="/analyses/{marked_id}"' in r)
    sibling_row = next(r for r in rows if f'href="/analyses/{sibling_id}"' in r)

    assert DIPAKAI_CHIP in marked_row
    assert ">Arsip<" not in marked_row
    assert ">Dipakai<" not in sibling_row
    assert ARSIP_CHIP in sibling_row

    # One query drives both views of the page: the table and the card list for narrow screens.
    assert table.count(">Dipakai<") == 1
    assert table.count(">Arsip<") == 1
    assert resp.text.count(">Dipakai<") == 2
    assert resp.text.count(">Arsip<") == 2


def test_compare_options_carry_the_mark_suffix(client: TestClient):
    dataset_id, marked_id, sibling_id = _marked_pair(client, "bandingkan_tanda@example.test")

    resp = client.get(f"/analyses/{marked_id}/explore?view=bandingkan")
    assert resp.status_code == 200

    marked_option = re.search(r'<option value="%d"[^>]*>([^<]*)</option>' % marked_id, resp.text)
    sibling_option = re.search(r'<option value="%d"[^>]*>([^<]*)</option>' % sibling_id, resp.text)
    assert marked_option is not None and sibling_option is not None
    assert marked_option.group(1).endswith(f"{MIDDLE_DOT} Dipakai")
    assert sibling_option.group(1).endswith(f"{MIDDLE_DOT} Arsip")

    # Both selects carry the suffix, the first and the second one.
    assert resp.text.count(f" {MIDDLE_DOT} Dipakai</option>") == 2
    assert resp.text.count(f" {MIDDLE_DOT} Arsip</option>") == 2


def test_the_three_pages_carry_no_em_dash(client: TestClient):
    dataset_id, marked_id, sibling_id = _marked_pair(client, "tanda_tanpa_dash@example.test")

    for url in (
        f"/analyses/{marked_id}",
        "/analyses",
        f"/analyses/{marked_id}/explore?view=bandingkan",
    ):
        resp = client.get(url)
        assert resp.status_code == 200
        assert "\u2014" not in resp.text
