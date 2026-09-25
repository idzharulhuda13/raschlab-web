"""Response-size and latency budget for a large dataset.

The 25 Sep 2026 incident: the mapping page enumerated every distinct cell value, so a
45.832 x 15 upload produced a 33 MiB response and the platform returned HTTP 500. These
tests pin the budgets that keep any page small, whatever the dataset size.
"""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.analysis import RENDER_PAGE
from app.db import SessionLocal
from app.models import Dataset

# Hard ceiling for any HTML response the app renders for one dataset or analysis.
PAGE_BYTE_BUDGET = 2_000_000
# A large upload (parse + summary + store) must stay well inside the request timeout.
UPLOAD_MS_BUDGET = 20_000

LARGE_PERSONS = 12_000
LARGE_ITEMS = 15


def _large_csv() -> bytes:
    """LARGE_PERSONS x LARGE_ITEMS matrix with an identity column and an answer key.

    Scores spread across the scale: a person hitting every item or none is extreme and is
    dropped from the person table by the engine, so the fixture keeps most scores interior.
    """
    letters = "ABCD"
    lines = ["username," + ",".join(f"I{i:02d}" for i in range(LARGE_ITEMS))]
    lines.append("kunci," + ",".join(letters[i % 4] for i in range(LARGE_ITEMS)))
    for p in range(LARGE_PERSONS):
        if p % 97 == 0:  # a slice with no answers at all
            cells = [""] * LARGE_ITEMS
        elif p % 41 == 0:
            cells = ["X"] * LARGE_ITEMS
        else:
            hits = 2 + (p % 7)  # two to eight chance-in-ten of answering an item correctly
            cells = []
            for i in range(LARGE_ITEMS):
                if (p * 7 + i * 13) % 10 < hits:
                    cells.append(letters[i % 4])
                else:
                    cells.append(letters[(i + 1 + (p % 3)) % 4])
        lines.append(f"P{p:013d}," + ",".join(cells))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _upload(client: TestClient, filename: str, payload: bytes, email: str) -> int:
    from tests.test_ingest_routes import _create_authenticated_user

    _create_authenticated_user(client, email=email)
    started = time.perf_counter()
    resp = client.post(
        "/datasets", files={"data": (filename, payload, "text/csv")}, follow_redirects=False
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert resp.status_code == 303, resp.text[:300]
    assert elapsed_ms < UPLOAD_MS_BUDGET, f"upload took {elapsed_ms:.0f} ms"
    return int(resp.headers["location"].split("/")[-1])


def test_large_dataset_pages_stay_inside_the_byte_budget(client: TestClient):
    dataset_id = _upload(client, "large.csv", _large_csv(), "budget@example.test")

    with SessionLocal() as db:
        row = db.execute(select(Dataset).where(Dataset.id == dataset_id)).scalar_one()
        assert row.n_persons == LARGE_PERSONS
        assert row.n_items == LARGE_ITEMS
        assert len(json.loads(row.item_labels_json)) == LARGE_ITEMS

    sizes = {}
    for path in (
        f"/datasets/{dataset_id}",
        "/datasets",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, path
        sizes[path] = len(resp.content)
        assert len(resp.content) < PAGE_BYTE_BUDGET, f"{path} rendered {len(resp.content)} bytes"

    # The full mapping table renders one row per distinct token, never one row per cell.
    assert sizes[f"/datasets/{dataset_id}"] < 250_000
    assert client.get(f"/datasets/{dataset_id}").text.count("<option") <= 64 * 4


def test_large_dataset_analysis_pages_stay_inside_the_byte_budget(client: TestClient):
    dataset_id = _upload(client, "large.csv", _large_csv(), "budget2@example.test")
    with SessionLocal() as db:
        key = json.loads(
            db.execute(select(Dataset).where(Dataset.id == dataset_id)).scalar_one().mapping_json
        )["key"]

    commit = client.post(f"/datasets/{dataset_id}/commit", data={"key": key}, follow_redirects=False)
    assert commit.status_code == 303

    analyze = client.post(f"/datasets/{dataset_id}/analyze", follow_redirects=False)
    assert analyze.status_code in (200, 303), analyze.text[:300]

    with SessionLocal() as db:
        from app.models import Analysis

        analysis = (
            db.execute(select(Analysis).where(Analysis.dataset_id == dataset_id).order_by(Analysis.id.desc()))
            .scalars()
            .first()
        )
        assert analysis is not None
        assert analysis.status == "done", analysis.error
        analysis_id = analysis.id
        persons = db.execute(select(Dataset).where(Dataset.id == dataset_id)).scalar_one().n_persons

    assert persons == LARGE_PERSONS

    for path in (
        f"/analyses/{analysis_id}",
        f"/analyses/{analysis_id}?page_person=2",
        f"/analyses/{analysis_id}/explore?view=wright",
        f"/analyses/{analysis_id}/explore?view=butir",
        f"/analyses/{analysis_id}/explore?view=partisipan",
        f"/analyses/{analysis_id}/explore?view=ringkasan",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert len(resp.content) < PAGE_BYTE_BUDGET, f"{path} rendered {len(resp.content)} bytes"

    # Server-side pagination stays the mechanism: every page of the person table is
    # rendered on demand, and no page can approach the byte budget.
    for page_no in (1, 2):
        page = client.get(f"/analyses/{analysis_id}?page_person={page_no}")
        assert page.status_code == 200
        assert len(page.content) < PAGE_BYTE_BUDGET
    first = client.get(f"/analyses/{analysis_id}?page_person=1").text
    assert f"page_person=2" in first, "pagination control missing for a multi-page person table"