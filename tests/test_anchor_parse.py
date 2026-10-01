import pytest

from app.analysis import AnalysisError, parse_anchors

LABELS = ["zeta", "alpha", "mike"]


def _call(content: bytes, labels=None, filename="jangkar.txt"):
    return parse_anchors(filename, content, list(LABELS if labels is None else labels))


def test_position_form():
    labels = ["item1", "item2", "item3", "item4", "item5"]
    res = _call(b"1 0.50\n5 -1.25\n", labels=labels)
    assert res["anchors"] == {1: 0.5, 5: -1.25}
    assert res["requested"] == 2
    assert res["by_position"] == 2
    assert res["by_label"] == 0
    assert res["name"] == "jangkar.txt"


def test_label_form():
    res = _call(b"mike 0.7\n")
    assert res["anchors"] == {3: 0.7}
    assert res["requested"] == 1
    assert res["by_position"] == 0
    assert res["by_label"] == 1


def test_mixed_form():
    res = _call(b"zeta 0.5\n2 -0.4\n")
    assert res["anchors"] == {1: 0.5, 2: -0.4}
    assert res["by_position"] == 1
    assert res["by_label"] == 1


def test_position_wins_over_label():
    res = _call(b"zeta 0.5\n1 -0.4\n")
    assert res["anchors"] == {1: -0.4}
    assert res["by_position"] == 1
    assert res["by_label"] == 0


def test_duplicate_within_one_form_last_wins():
    res = _call(b"1 0.5\n1 0.9\n")
    assert res["anchors"] == {1: 0.9}


def test_unknown_label():
    with pytest.raises(AnalysisError) as exc:
        _call(b"nope 0.5\n")
    assert "Nama butir 'nope' tidak ada" in str(exc.value)


def test_position_out_of_range():
    with pytest.raises(AnalysisError) as exc:
        _call(b"4 0.5\n")
    assert "Nomor butir 4 di luar rentang 1 sampai 3" in str(exc.value)


def test_non_numeric_value():
    with pytest.raises(AnalysisError) as exc:
        _call(b"1 abc\n")
    assert "bukan angka" in str(exc.value)


def test_empty_upload():
    with pytest.raises(AnalysisError) as exc:
        _call(b"")
    assert "Berkas jangkar kosong" in str(exc.value)


def test_only_comments_and_blank_lines():
    with pytest.raises(AnalysisError) as exc:
        _call(b"# satu\n\n# dua\n")
    assert "Tidak ada baris jangkar yang dapat dibaca" in str(exc.value)


def test_oversized_upload():
    with pytest.raises(AnalysisError) as exc:
        _call(b"1 0.5\n" * 20000)
    assert "terlalu besar" in str(exc.value)


def test_too_many_lines_but_small():
    with pytest.raises(AnalysisError) as exc:
        _call(b"1 0.5\n" * 5001)
    assert "terlalu banyak baris" in str(exc.value)


def test_incomplete_line():
    with pytest.raises(AnalysisError) as exc:
        _call(b"1\n")
    assert "tidak lengkap" in str(exc.value)


def test_extra_tokens_after_value_ignored():
    res = _call(b"1 0.5 extra\n")
    assert res["anchors"] == {1: 0.5}


def test_label_containing_space():
    res = _call(b"a b 1.5\n", labels=["a b", "c"])
    assert res["anchors"] == {1: 1.5}


def test_duplicate_label_in_dataset_columns():
    with pytest.raises(AnalysisError) as exc:
        _call(b"x 1.0\n", labels=["x", "x"])
    assert "ganda pada kolom butir" in str(exc.value)


def test_binary_upload():
    with pytest.raises(AnalysisError) as exc:
        _call(b"\x00\x01\x02\x03")
    assert "bukan berkas biner" in str(exc.value)


def test_non_finite_value():
    with pytest.raises(AnalysisError) as exc:
        _call(b"1 nan\n")
    assert "bukan angka" in str(exc.value)


def test_long_filename_truncated():
    res = _call(b"1 0.5\n", filename="a" * 200 + ".txt")
    assert len(res["name"]) == 120


def test_longest_label_match_wins():
    """A label that is a prefix of another label must not swallow the longer one (review fix)."""
    res = parse_anchors("a.txt", b"foo 2 0.5\n", ["foo", "foo 2"])

    assert res["anchors"] == {2: 0.5}
    assert res["by_label"] == 1


def test_shorter_label_still_resolves_when_it_is_the_only_match():
    res = parse_anchors("a.txt", b"foo 1.5\n", ["foo", "foo 2"])

    assert res["anchors"] == {1: 1.5}
