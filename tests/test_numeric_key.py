import gzip
import json
import pytest

from app.analysis import AnalysisError, build_matrix_gzip


def test_numeric_key_basic():
    payload_bytes = build_matrix_gzip(
        kind="delimited",
        person_labels=["P1", "P2"],
        item_labels=["I1", "I2", "I3"],
        rows=[["1", "0", ""], ["0", "1", "0"]],
        mapping={"1": "correct", "0": "incorrect", "": "missing"},
        key="110",
    )
    assert isinstance(payload_bytes, bytes)
    text = gzip.decompress(payload_bytes).decode("utf-8")
    payload = json.loads(text)
    assert payload["codes"] == "01" or "CODES=01" in text


def test_numeric_key_two_character_token():
    with pytest.raises(AnalysisError) as exc_info:
        build_matrix_gzip(
            kind="delimited",
            person_labels=["P1", "P2"],
            item_labels=["I1", "I2", "I3"],
            rows=[["AB", "0", ""], ["0", "1", "0"]],
            mapping={"1": "correct", "0": "incorrect", "": "missing"},
            key="110",
        )
    err = str(exc_info.value)
    assert "AB" in err
    assert "01AB" in err or "AB" in err


def test_numeric_key_outside_alphabet():
    with pytest.raises(AnalysisError) as exc_info:
        build_matrix_gzip(
            kind="delimited",
            person_labels=["P1", "P2"],
            item_labels=["I1", "I2", "I3"],
            rows=[["1", "0", "2"], ["0", "1", "0"]],
            mapping={"1": "correct", "0": "incorrect", "2": "incorrect", "": "missing"},
            control={"CODES": "01"},
            key="110",
        )
    err = str(exc_info.value)
    assert "2" in err
    assert "01" in err


def test_numeric_key_winsteps_control_codes():
    payload_bytes = build_matrix_gzip(
        kind="winsteps",
        person_labels=["P1", "P2"],
        item_labels=["I1", "I2"],
        rows=["01", "10"],
        control={"CODES": "01", "KEY1": "01", "NI": 2},
    )
    assert isinstance(payload_bytes, bytes)
    text = gzip.decompress(payload_bytes).decode("utf-8")
    payload = json.loads(text)
    assert payload["codes"] == "01" or "CODES=01" in text


def test_numeric_key_winsteps_invalid_codes():
    for bad_codes in ("0 1", "0 10"):
        with pytest.raises(AnalysisError) as exc_info:
            build_matrix_gzip(
                kind="winsteps",
                person_labels=["P1", "P2"],
                item_labels=["I1", "I2"],
                rows=["01", "10"],
                control={"CODES": bad_codes, "KEY1": "01", "NI": 2},
            )
        err = str(exc_info.value)
        assert "satu karakter" in err
        assert "huruf A-E" not in err
