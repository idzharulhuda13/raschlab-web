"""Tests for the anchor upload, the inherit option, and the engine call (F19).

Every POST drives the real route with a monkeypatched app.analysis.run_analyze that records its
call, including the bytes of the anchor file it was handed while the run's temp dir was alive.
No engine run happens here; tests/test_anchor_engine.py covers the real engine.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import analysis as analysis_module
from tests.test_analysis_settings import _create_authenticated_user, _upload_and_commit_sample
from tests.test_delete_list_inputs import _build_test_files
from tests.test_delete_list_settings import (
    FORM,
    _analysis_count,
    _analysis_id_from,
    _post_analyze,
    _recorded_params,
)

ANCHOR_UPLOAD = b"1 0.50\n5 -1.25\n"
ANCHOR_FILE_TEXT = b"1 0.5\n5 -1.25\n"


def _install_anchor_recording_engine(monkeypatch) -> list[dict]:
    """Like the delete-list fake, but it also reads the anchor file before the temp dir goes away."""
    calls: list[dict] = []

    def fake_run_analyze(*args, **kwargs) -> None:
        captured = dict(kwargs)
        anchors_path = kwargs.get("anchors_path")
        if anchors_path is not None:
            captured["anchors_bytes"] = Path(anchors_path).read_bytes()
            captured["anchors_name"] = Path(anchors_path).name
        calls.append(captured)

        out_dir = kwargs["out_dir"]
        for name, text in _build_test_files().items():
            Path(out_dir, name).write_bytes(text.encode("utf-8"))

    monkeypatch.setattr(analysis_module, "run_analyze", fake_run_analyze)
    return calls


def _post_with_form(client: TestClient, dataset_id: int, extra: dict, **kwargs):
    form = dict(FORM)
    form.update(extra)
    return client.post(
        f"/datasets/{dataset_id}/analyze", data=form, follow_redirects=False, **kwargs
    )


def test_anchor_upload_is_stored_and_passed_to_the_engine(client: TestClient, monkeypatch):
    calls = _install_anchor_recording_engine(monkeypatch)
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = _post_analyze(client, dataset_id, files={"anchors": ("jangkar.txt", ANCHOR_UPLOAD)})

    assert resp.status_code == 303
    entry = _recorded_params(_analysis_id_from(resp))["anchors"]
    assert entry["name"] == "jangkar.txt"
    assert entry["requested"] == 2
    assert entry["used"] == 2
    assert entry["anchors"] == {"1": 0.5, "5": -1.25}
    assert entry["by_position"] == 2
    assert entry["by_label"] == 0
    assert len(calls) == 1
    assert calls[0]["anchors_name"] == "anchors_input.TXT"
    assert calls[0]["anchors_bytes"] == ANCHOR_FILE_TEXT


def test_a_run_without_an_anchor_upload_stays_unanchored(client: TestClient, monkeypatch):
    calls = _install_anchor_recording_engine(monkeypatch)
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = _post_analyze(client, dataset_id)

    assert resp.status_code == 303
    assert _recorded_params(_analysis_id_from(resp))["anchors"] is None
    assert calls[0]["anchors_path"] is None


def test_invalid_anchor_upload_stops_before_the_engine(client: TestClient, monkeypatch):
    calls = _install_anchor_recording_engine(monkeypatch)
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    resp = _post_analyze(client, dataset_id, files={"anchors": ("jangkar.txt", b"nope 0.5\n")})

    assert resp.status_code == 422
    assert "tidak ada pada kolom butir dataset" in resp.text
    assert calls == []
    assert _analysis_count(dataset_id) == 0


def test_inherited_anchors_are_used_again_without_a_new_upload(client: TestClient, monkeypatch):
    calls = _install_anchor_recording_engine(monkeypatch)
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    first = _post_analyze(client, dataset_id, files={"anchors": ("jangkar.txt", ANCHOR_UPLOAD)})
    first_id = _analysis_id_from(first)
    assert calls[0]["anchors_bytes"] == ANCHOR_FILE_TEXT
    calls.clear()

    second = _post_with_form(client, dataset_id, {"inherit_anchors": str(first_id)})

    assert second.status_code == 303
    entry = _recorded_params(_analysis_id_from(second))["anchors"]
    assert entry["name"] == "jangkar.txt"
    assert entry["anchors"] == {"1": 0.5, "5": -1.25}
    assert entry["used"] == 2
    assert len(calls) == 1
    assert calls[0]["anchors_bytes"] == ANCHOR_FILE_TEXT


def test_a_new_upload_wins_over_the_inherited_anchors(client: TestClient, monkeypatch):
    calls = _install_anchor_recording_engine(monkeypatch)
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    first = _post_analyze(client, dataset_id, files={"anchors": ("jangkar.txt", ANCHOR_UPLOAD)})
    calls.clear()

    second = _post_with_form(
        client,
        dataset_id,
        {"inherit_anchors": str(_analysis_id_from(first))},
        files={"anchors": ("jangkar-baru.txt", b"7 -0.75\n")},
    )

    assert second.status_code == 303
    entry = _recorded_params(_analysis_id_from(second))["anchors"]
    assert entry["name"] == "jangkar-baru.txt"
    assert entry["anchors"] == {"7": -0.75}
    assert calls[0]["anchors_bytes"] == b"7 -0.75\n"


def test_inherit_from_another_dataset_is_refused(client: TestClient, monkeypatch):
    calls = _install_anchor_recording_engine(monkeypatch)
    _create_authenticated_user(client)
    dataset_a = _upload_and_commit_sample(client)
    dataset_b = _upload_and_commit_sample(client)

    other = _post_analyze(client, dataset_b, files={"anchors": ("jangkar.txt", ANCHOR_UPLOAD)})
    other_id = _analysis_id_from(other)
    calls.clear()

    resp = _post_with_form(client, dataset_a, {"inherit_anchors": str(other_id)})

    assert resp.status_code == 303
    assert _recorded_params(_analysis_id_from(resp))["anchors"] is None
    assert calls[0]["anchors_path"] is None


def test_settings_page_offers_inheritance_only_after_an_anchored_run(
    client: TestClient, monkeypatch
):
    _install_anchor_recording_engine(monkeypatch)
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    before = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert before.status_code == 200
    assert 'name="inherit_anchors"' not in before.text

    resp = _post_analyze(client, dataset_id, files={"anchors": ("jangkar.txt", ANCHOR_UPLOAD)})
    anchored_id = _analysis_id_from(resp)

    after = client.get(f"/datasets/{dataset_id}/analysis-settings")
    assert after.status_code == 200
    assert f'name="inherit_anchors" value="{anchored_id}"' in after.text
    assert "jangkar.txt" in after.text


def test_a_non_finite_stored_anchor_is_refused(client: TestClient, monkeypatch):
    """A hand-corrupted params_json must fail loudly instead of reaching the engine (review fix)."""
    import pytest
    from sqlalchemy import select

    from app.analysis import AnalysisError, run_for_dataset
    from app.db import SessionLocal
    from app.models import Dataset

    calls = _install_anchor_recording_engine(monkeypatch)
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    bad_values = [float("nan"), float("inf"), "NaN", "inf"]
    with SessionLocal() as db:
        dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
        assert dataset is not None
        for bad in bad_values:
            with pytest.raises(AnalysisError):
                run_for_dataset(
                    db,
                    dataset,
                    params={
                        "anchors": {
                            "name": "x.txt",
                            "requested": 1,
                            "anchors": {"1": bad},
                        }
                    },
                )

    assert _analysis_count(dataset_id) == 0
    assert calls == []
