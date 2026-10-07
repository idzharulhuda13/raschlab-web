from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME
from app.db import SessionLocal
from app.models import SessionRow, User
from app.security import hash_password, hash_token, new_token, now_epoch

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


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


def _upload_and_commit_sample(client: TestClient, fixture_name: str = "sample_300x40.csv") -> int:
    csv_bytes = (FIXTURES_DIR / fixture_name).read_bytes()
    upload_resp = client.post(
        "/datasets",
        files={"data": (fixture_name, csv_bytes, "text/csv")},
        follow_redirects=False,
    )
    assert upload_resp.status_code == 303
    dataset_id = int(upload_resp.headers["location"].split("/")[-1].split("?")[0])

    commit_resp = client.post(
        f"/datasets/{dataset_id}/commit",
        data={
            "t0": "1",
            "m0": "correct",
            "t1": "0",
            "m1": "incorrect",
            "t2": "NA",
            "m2": "missing",
            "t3": "",
            "m3": "missing",
        },
        follow_redirects=False,
    )
    assert commit_resp.status_code == 303
    return dataset_id


def test_anonymous_request_is_guarded_with_no_json_leak(client: TestClient):
    # 1. anonymous -> the guard answer, no JSON leak (redirect 303 to /login)
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    client.cookies.clear()
    resp = client.get(f"/datasets/{dataset_id}/picker?kind=persons", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
    assert "items" not in resp.text
    assert "P0001" not in resp.text


def test_another_users_dataset_returns_404(client: TestClient):
    # 2. another user's dataset -> 404, not an empty list
    _create_authenticated_user(client, email="owner@example.test")
    dataset_id = _upload_and_commit_sample(client)

    client.cookies.clear()
    _create_authenticated_user(client, email="intruder@example.test")

    resp = client.get(f"/datasets/{dataset_id}/picker?kind=persons")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Dataset tidak ditemukan."


def test_kind_persons_with_300_fixture(client: TestClient):
    # 3. kind=persons with a 300-person fixture -> 5 items, correct pos/label, total and has_more true
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/picker?kind=persons")
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "persons"
    assert data["total"] == 300
    assert data["offset"] == 0
    assert data["limit"] == 5
    assert data["has_more"] is True
    assert len(data["items"]) == 5
    assert data["items"][0] == {"pos": 1, "label": "P0001"}
    assert data["items"][1] == {"pos": 2, "label": "P0002"}
    assert data["items"][4] == {"pos": 5, "label": "P0005"}


def test_offset_pagination_and_past_the_end(client: TestClient):
    # 4. offset=295 -> 5 items, has_more false; offset=500 -> empty list, has_more false
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/picker?kind=persons&offset=295")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 300
    assert data["offset"] == 295
    assert data["limit"] == 5
    assert data["has_more"] is False
    assert len(data["items"]) == 5
    assert data["items"][0] == {"pos": 296, "label": "P0296"}
    assert data["items"][4] == {"pos": 300, "label": "P0300"}

    resp_past = client.get(f"/datasets/{dataset_id}/picker?kind=persons&offset=500")
    assert resp_past.status_code == 200
    data_past = resp_past.json()
    assert data_past["total"] == 300
    assert data_past["offset"] == 500
    assert data_past["limit"] == 5
    assert data_past["has_more"] is False
    assert data_past["items"] == []


def test_query_filter_label_substring_and_position_ranking(client: TestClient):
    # 5. q filters by label substring (case-insensitive) and by position number,
    # and the position match ranks first
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    # Substring search case-insensitive: "p0002" should match P0002
    resp_label = client.get(f"/datasets/{dataset_id}/picker?kind=persons&q=p0002")
    assert resp_label.status_code == 200
    data_label = resp_label.json()
    assert data_label["total"] >= 1
    assert data_label["items"][0] == {"pos": 2, "label": "P0002"}

    # Number search: "2". Exact position 2 (label P0002) must be ranked first,
    # ahead of other matches (e.g. pos 20, 21, etc.).
    resp_num = client.get(f"/datasets/{dataset_id}/picker?kind=persons&q=2")
    assert resp_num.status_code == 200
    data_num = resp_num.json()
    assert len(data_num["items"]) == 5
    assert data_num["items"][0]["pos"] == 2
    assert data_num["items"][0]["label"] == "P0002"
    # Ensure remaining returned items are also matches
    for it in data_num["items"]:
        assert "2" in str(it["pos"]) or "2" in it["label"].lower()


def test_query_matching_nothing(client: TestClient):
    # 6. a q that matches nothing -> empty items, total 0, has_more false, HTTP 200
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/picker?kind=persons&q=nonexistent_xyz_9999")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["has_more"] is False
    assert data["offset"] == 0
    assert data["limit"] == 5


def test_kind_bogus_returns_400(client: TestClient):
    # 7. kind=bogus -> 400
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/picker?kind=bogus")
    assert resp.status_code == 400
    assert "detail" in resp.json()
    assert "persons atau items" in resp.json()["detail"]


def test_kind_items_works_against_item_labels(client: TestClient):
    # 8. kind=items works the same way against the item labels
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/picker?kind=items")
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "items"
    assert data["total"] == 40  # 40 items in sample_300x40.csv
    assert data["offset"] == 0
    assert data["limit"] == 5
    assert data["has_more"] is True
    assert len(data["items"]) == 5
    assert data["items"][0] == {"pos": 1, "label": "I01"}
    assert data["items"][1] == {"pos": 2, "label": "I02"}

    # Search items by label substring case-insensitive
    resp_q = client.get(f"/datasets/{dataset_id}/picker?kind=items&q=i05")
    assert resp_q.status_code == 200
    data_q = resp_q.json()
    assert data_q["total"] == 1
    assert data_q["items"][0] == {"pos": 5, "label": "I05"}


def test_limit_is_fixed_server_side_never_exceeds_5(client: TestClient):
    # 9. assert the response never carries more than 5 items even when a caller sends limit=1000
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = client.get(f"/datasets/{dataset_id}/picker?kind=persons&limit=1000")
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit"] == 5
    assert len(data["items"]) == 5
