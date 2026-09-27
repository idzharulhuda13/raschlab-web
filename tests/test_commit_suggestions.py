"""Tests for commit screen suggestion per distinct token (B1 contract)."""

from __future__ import annotations

from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient

from tests.test_analysis_settings import _create_authenticated_user

SUGGESTION_LINE = "Saran otomatis berdasarkan isi berkas. Periksa sebelum konfirmasi."


def _extract_select_selected_value(select_html: str) -> str | None:
    """Return the value of the option marked selected in a select element."""
    match = re.search(r'<option\s+value="([^"]*)"\s+selected>', select_html)
    if match:
        return match.group(1)
    match = re.search(r'<option\s+selected\s+value="([^"]*)">', select_html)
    if match:
        return match.group(1)
    return None


def _token_select_map(html: str) -> dict[str, str | None]:
    """Map token string -> selected option value from the rendered token table."""
    token_inputs = dict(re.findall(r'<input\s+type="hidden"\s+name="t(\d+)"\s+value="([^"]*)">', html))
    select_matches = re.findall(r'<select\s+name="m(\d+)"[^>]*>(.*?)</select>', html, re.DOTALL)
    selects = {idx_str: content for idx_str, content in select_matches}

    result: dict[str, str | None] = {}
    for idx_str, token in token_inputs.items():
        select_content = selects[idx_str]
        selected_val = _extract_select_selected_value(select_content)
        result[token] = selected_val
    return result


def test_suggested_classification_preselects_options_per_token(client: TestClient, tmp_path: Path):
    """1. Upload fixture with tokens '1', '0', and empty value, assert per select preselection."""
    _create_authenticated_user(client)

    csv_content = (
        "id,I01,I02,I03\n"
        "P01,1,0,\n"
        "P02,0,1,1\n"
        "P03,,0,0\n"
    )
    csv_file = tmp_path / "scored_1_0_empty.csv"
    csv_file.write_text(csv_content)

    upload_resp = client.post(
        "/datasets",
        files={"data": ("scored_1_0_empty.csv", csv_file.read_bytes(), "text/csv")},
        follow_redirects=False,
    )
    assert upload_resp.status_code == 303
    dataset_id = int(upload_resp.headers["location"].split("/")[-1].split("?")[0])

    commit_page_resp = client.get(f"/datasets/{dataset_id}")
    assert commit_page_resp.status_code == 200
    html = commit_page_resp.text

    selected_per_token = _token_select_map(html)
    assert "1" in selected_per_token
    assert "0" in selected_per_token
    assert "" in selected_per_token

    # Assert per select that exact option is selected
    assert selected_per_token["1"] == "correct"
    assert selected_per_token["0"] == "incorrect"
    assert selected_per_token[""] == "missing"


def test_suggestion_line_present_on_scored_commit_page(client: TestClient, tmp_path: Path):
    """2. The suggestion line is present on the scored commit page."""
    _create_authenticated_user(client)

    csv_content = (
        "id,I01,I02,I03\n"
        "P01,1,0,\n"
        "P02,0,1,1\n"
    )
    csv_file = tmp_path / "scored_1_0.csv"
    csv_file.write_text(csv_content)

    upload_resp = client.post(
        "/datasets",
        files={"data": ("scored_1_0.csv", csv_file.read_bytes(), "text/csv")},
        follow_redirects=False,
    )
    assert upload_resp.status_code == 303
    dataset_id = int(upload_resp.headers["location"].split("/")[-1].split("?")[0])

    commit_page_resp = client.get(f"/datasets/{dataset_id}")
    assert commit_page_resp.status_code == 200
    assert SUGGESTION_LINE in commit_page_resp.text


def test_key_row_detected_renders_suggestion_line_absent_and_no_preselected(client: TestClient, tmp_path: Path):
    """3. Dataset whose key row was detected renders suggestion line ABSENT and selects without preselection."""
    _create_authenticated_user(client)

    csv_content = (
        "id,I01,I02,I03\n"
        "kunci,A,B,A\n"
        "P01,A,B,B\n"
        "P02,B,A,A\n"
    )
    csv_file = tmp_path / "key_row_data.csv"
    csv_file.write_text(csv_content)

    upload_resp = client.post(
        "/datasets",
        files={"data": ("key_row_data.csv", csv_file.read_bytes(), "text/csv")},
        follow_redirects=False,
    )
    assert upload_resp.status_code == 303
    dataset_id = int(upload_resp.headers["location"].split("/")[-1].split("?")[0])

    commit_page_resp = client.get(f"/datasets/{dataset_id}")
    assert commit_page_resp.status_code == 200
    html = commit_page_resp.text

    # Suggestion line must be ABSENT
    assert SUGGESTION_LINE not in html

    # Selects must keep "Pilih status..." (value="") without a preselected classification
    selected_per_token = _token_select_map(html)
    assert len(selected_per_token) > 0
    for token, selected_val in selected_per_token.items():
        assert selected_val == "", f"Token {token!r} unexpectedly had preselected classification {selected_val!r}"
