"""The version-in-use mark: one marked analysis per dataset, chosen explicitly.

Covers:
- marking sets the mark on that analysis and clears it on a previously marked sibling of the same
  dataset, including siblings that are not done;
- marking never touches an analysis of another dataset;
- unmarking clears that analysis and leaves its siblings' marks standing;
- marking an already marked analysis is idempotent (the timestamp is kept, nothing raised);
- marked_analysis_id reads the mark, answers None for a dataset without one, and picks the newest
  by primary_at then id when a legacy store somehow holds two;
- the POST route refuses an anonymous caller and a foreign owner without writing anything.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.analysis import mark_analysis, marked_analysis_id
from app.auth import COOKIE_NAME
from app.db import SessionLocal
from app.models import Analysis, Dataset, SessionRow, User
from app.security import hash_token, new_token, now_epoch

LEGACY_MARK = 1_600_000_000


def _create_user(email: str = "penanda@example.test") -> int:
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
        return user.id


def _create_dataset(user_id: int, filename: str = "instrumen_ujian.csv") -> int:
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


def _create_analysis(
    user_id: int,
    dataset_id: int,
    status: str = "done",
    primary_at: int | None = None,
) -> int:
    with SessionLocal() as db:
        now = now_epoch()
        analysis = Analysis(
            user_id=user_id,
            dataset_id=dataset_id,
            status=status,
            params_json="{}",
            engine_ref="raschlab-engine-test",
            created_at=now,
            expires_at=now + 180 * 86400,
            primary_at=primary_at,
        )
        db.add(analysis)
        db.commit()
        return analysis.id


def _primary_at(analysis_id: int) -> int | None:
    with SessionLocal() as db:
        return db.scalar(select(Analysis.primary_at).where(Analysis.id == analysis_id))


def _mark(analysis_id: int, marked: bool) -> None:
    with SessionLocal() as db:
        analysis = db.scalar(select(Analysis).where(Analysis.id == analysis_id))
        assert analysis is not None
        mark_analysis(db, analysis, marked)


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


def test_marking_sets_the_mark_and_clears_a_previously_marked_sibling():
    user_id = _create_user()
    dataset_id = _create_dataset(user_id)
    first_id = _create_analysis(user_id, dataset_id)
    second_id = _create_analysis(user_id, dataset_id)
    failed_id = _create_analysis(user_id, dataset_id, status="failed")

    # A sibling that is not done can still hold the mark, and marking another run must clear it.
    _mark(failed_id, True)
    assert _primary_at(failed_id) is not None

    _mark(first_id, True)
    first_mark = _primary_at(first_id)
    assert first_mark is not None and first_mark > 0
    assert _primary_at(second_id) is None
    assert _primary_at(failed_id) is None

    _mark(second_id, True)
    assert _primary_at(second_id) is not None
    assert _primary_at(first_id) is None


def test_marking_never_touches_an_analysis_of_another_dataset():
    user_id = _create_user()
    dataset_a = _create_dataset(user_id, "berkas_a.csv")
    dataset_b = _create_dataset(user_id, "berkas_b.csv")
    analysis_a = _create_analysis(user_id, dataset_a)
    analysis_b = _create_analysis(user_id, dataset_b, primary_at=LEGACY_MARK)

    _mark(analysis_a, True)

    assert _primary_at(analysis_a) is not None
    assert _primary_at(analysis_b) == LEGACY_MARK


def test_unmarking_clears_that_analysis_and_leaves_the_siblings_alone():
    user_id = _create_user()
    dataset_id = _create_dataset(user_id)
    first_id = _create_analysis(user_id, dataset_id, primary_at=LEGACY_MARK)
    second_id = _create_analysis(user_id, dataset_id, primary_at=LEGACY_MARK + 100)

    _mark(first_id, False)

    assert _primary_at(first_id) is None
    assert _primary_at(second_id) == LEGACY_MARK + 100


def test_marking_an_already_marked_analysis_is_idempotent():
    user_id = _create_user()
    dataset_id = _create_dataset(user_id)
    analysis_id = _create_analysis(user_id, dataset_id, primary_at=LEGACY_MARK)

    _mark(analysis_id, True)
    assert _primary_at(analysis_id) == LEGACY_MARK

    # A second call, from a fresh session, still changes nothing and raises nothing.
    _mark(analysis_id, True)
    assert _primary_at(analysis_id) == LEGACY_MARK


def test_marked_analysis_id_answers_the_mark_none_and_the_newest_of_two():
    user_id = _create_user()
    dataset_id = _create_dataset(user_id, "berkas_dipakai.csv")
    other_dataset_id = _create_dataset(user_id, "berkas_lain.csv")
    first_id = _create_analysis(user_id, dataset_id)
    second_id = _create_analysis(user_id, dataset_id)

    with SessionLocal() as db:
        assert marked_analysis_id(db, dataset_id) is None
        assert marked_analysis_id(db, other_dataset_id) is None

    _mark(second_id, True)
    with SessionLocal() as db:
        assert marked_analysis_id(db, dataset_id) == second_id
        assert marked_analysis_id(db, other_dataset_id) is None

    # A legacy store with two marked rows answers with the newest, and the higher id breaks a tie.
    with SessionLocal() as db:
        first = db.scalar(select(Analysis).where(Analysis.id == first_id))
        second = db.scalar(select(Analysis).where(Analysis.id == second_id))
        assert first is not None and second is not None
        first.primary_at = LEGACY_MARK
        second.primary_at = LEGACY_MARK + 500
        db.commit()

    with SessionLocal() as db:
        assert marked_analysis_id(db, dataset_id) == second_id

    with SessionLocal() as db:
        first = db.scalar(select(Analysis).where(Analysis.id == first_id))
        assert first is not None
        first.primary_at = LEGACY_MARK + 500
        db.commit()

    with SessionLocal() as db:
        assert marked_analysis_id(db, dataset_id) == second_id


def test_mark_route_refuses_anonymous_and_foreign_without_writing(client: TestClient):
    owner_id = _create_user("pemilik@example.test")
    dataset_id = _create_dataset(owner_id)
    unmarked_id = _create_analysis(owner_id, dataset_id)
    marked_id = _create_analysis(owner_id, dataset_id, primary_at=LEGACY_MARK)

    anonymous = client.post(
        f"/analyses/{unmarked_id}/mark", data={"primary": "1"}, follow_redirects=False
    )
    assert anonymous.status_code == 303
    assert anonymous.headers["location"] == "/login"
    assert _primary_at(unmarked_id) is None

    _login(client, "penyusup@example.test")
    foreign = client.post(
        f"/analyses/{marked_id}/mark", data={"primary": "0"}, follow_redirects=False
    )
    assert foreign.status_code == 404
    assert foreign.json()["detail"] == "Analisis tidak ditemukan."
    assert _primary_at(marked_id) == LEGACY_MARK

    missing = client.post("/analyses/999999/mark", data={"primary": "1"}, follow_redirects=False)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Analisis tidak ditemukan."


def test_mark_route_marks_and_demotes_the_sibling(client: TestClient):
    """The positive path of the route, which the refusals-only test above never exercises."""
    user_id = _login(client, "penanda@example.test")
    dataset_id = _create_dataset(user_id)
    first = _create_analysis(user_id, dataset_id)
    second = _create_analysis(user_id, dataset_id)

    marked = client.post(f"/analyses/{first}/mark", data={"primary": "1"}, follow_redirects=False)
    assert marked.status_code == 303
    assert marked.headers["location"] == f"/analyses/{first}"
    assert _primary_at(first) is not None
    assert _primary_at(second) is None

    moved = client.post(f"/analyses/{second}/mark", data={"primary": "1"}, follow_redirects=False)
    assert moved.status_code == 303
    assert moved.headers["location"] == f"/analyses/{second}"
    assert _primary_at(first) is None
    assert _primary_at(second) is not None


def test_mark_route_clears_the_mark(client: TestClient):
    user_id = _login(client, "penanda@example.test")
    dataset_id = _create_dataset(user_id)
    analysis_id = _create_analysis(user_id, dataset_id)

    client.post(f"/analyses/{analysis_id}/mark", data={"primary": "1"}, follow_redirects=False)
    assert _primary_at(analysis_id) is not None

    cleared = client.post(f"/analyses/{analysis_id}/mark", data={"primary": "0"}, follow_redirects=False)
    assert cleared.status_code == 303
    assert cleared.headers["location"] == f"/analyses/{analysis_id}"
    assert _primary_at(analysis_id) is None
