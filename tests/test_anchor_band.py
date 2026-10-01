"""Tests for the anchored state on the run page (F19).

Rows are seeded directly so every anchor shape can be rendered without an engine run: fully
applied, partially dropped, fully dropped, a legacy row without the key, a legacy None, and a
legacy list-shaped value. Each case asserts on the rendered text of the page.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Analysis
from app.security import now_epoch
from tests.test_analysis_settings import _create_authenticated_user, _upload_and_commit_sample

ANCHORS_FILE = "jangkar-tbs.txt"


def _seed_done(user_id: int, dataset_id: int, params: dict) -> int:
    now = now_epoch()
    with SessionLocal() as db:
        analysis = Analysis(
            user_id=user_id,
            dataset_id=dataset_id,
            status="done",
            params_json=json.dumps(params),
            engine_ref="test-ref",
            created_at=now,
            expires_at=now + 180 * 86400,
            finished_at=now,
            elapsed_ms=100,
        )
        db.add(analysis)
        db.commit()
        return analysis.id


def _params(anchors: object, with_key: bool = True) -> dict:
    params: dict = {"misfit": 1.5, "mode": "compat", "digits": 2}
    if with_key:
        params["anchors"] = anchors
    return params


def _page(client: TestClient, analysis_id: int) -> str:
    resp = client.get(f"/analyses/{analysis_id}")
    assert resp.status_code == 200
    return resp.text


def _anchors(used: int, requested: int = 2) -> dict:
    return {
        "name": ANCHORS_FILE,
        "requested": requested,
        "used": used,
        "anchors": {"1": 0.5, "5": -1.25},
    }


def test_fully_applied_anchors_show_the_anchored_band(client: TestClient):
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)
    analysis_id = _seed_done(user_id, dataset_id, _params(_anchors(used=2)))

    page = _page(client, analysis_id)

    assert "Jangkar Aktif (Anchored)" in page
    assert ANCHORS_FILE in page
    assert "2 butir dikunci" in page
    assert "Hasil Tanpa Jangkar" not in page
    assert "jangkar yang diminta" not in page


def test_partially_dropped_anchors_disclose_the_real_count(client: TestClient):
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)
    analysis_id = _seed_done(user_id, dataset_id, _params(_anchors(used=1)))

    page = _page(client, analysis_id)

    assert "Jangkar Aktif (Anchored)" in page
    assert "jangkar yang diminta" in page
    assert "1 dipakai" in page
    assert "Hasil Tanpa Jangkar" not in page


def test_all_anchors_dropped_warns_unanchored_and_says_why(client: TestClient):
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)
    analysis_id = _seed_done(user_id, dataset_id, _params(_anchors(used=0)))

    page = _page(client, analysis_id)

    assert "Hasil Tanpa Jangkar" in page
    assert "0 dipakai" in page
    assert ANCHORS_FILE in page
    assert "Jangkar Aktif (Anchored)" not in page


def test_legacy_row_without_the_key_stays_unanchored(client: TestClient):
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)
    analysis_id = _seed_done(user_id, dataset_id, _params(None, with_key=False))

    page = _page(client, analysis_id)

    assert "Hasil Tanpa Jangkar" in page
    assert "Jangkar Aktif (Anchored)" not in page
    assert "butir dikunci" not in page


def test_legacy_row_with_a_null_value_stays_unanchored(client: TestClient):
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)
    analysis_id = _seed_done(user_id, dataset_id, _params(None))

    page = _page(client, analysis_id)

    assert "Hasil Tanpa Jangkar" in page
    assert "Jangkar Aktif (Anchored)" not in page


def test_legacy_list_shaped_value_renders_without_a_band(client: TestClient):
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)
    analysis_id = _seed_done(user_id, dataset_id, _params([{"name": "x"}]))

    page = _page(client, analysis_id)

    assert "Jangkar Aktif (Anchored)" not in page
    assert "butir dikunci" not in page
    assert "jangkar yang diminta" not in page
    assert "0 dipakai" not in page


def test_partial_copy_counts_only_the_applied_anchors_as_locked(client: TestClient):
    """The first clause must state how many anchors are really locked (review fix)."""
    user_id = _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)
    analysis_id = _seed_done(user_id, dataset_id, _params(_anchors(used=1)))

    page = _page(client, analysis_id)

    assert "1 butir dikunci" in page
    assert "2 butir dikunci" not in page
    assert "Dari 2 jangkar yang diminta, 1 dipakai" in page
