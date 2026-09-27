import pytest
from app.parsers import parse_control

def test_codes_spelling_01():
    content = b"&INST\nNI=4\nKEY1=1111\nCODES = 01\n&END\n"
    res = parse_control(content)
    assert res["CODES"] == "01"
    assert isinstance(res["CODES"], str)

def test_codes_spelling_10():
    content = b"&INST\nNI=4\nKEY1=1111\nCODES = 10\n&END\n"
    res = parse_control(content)
    assert res["CODES"] == "10"
    assert isinstance(res["CODES"], str)

def test_codes_spelling_1234():
    content = b"&INST\nNI=4\nKEY1=1111\nCODES = 1234\n&END\n"
    res = parse_control(content)
    assert res["CODES"] == "1234"
    assert isinstance(res["CODES"], str)

def test_codes_spelling_ab():
    content = b"&INST\nNI=4\nKEY1=1111\nCODES = AB\n&END\n"
    res = parse_control(content)
    assert res["CODES"] == "AB"
    assert isinstance(res["CODES"], str)

def test_codes_spelling_quoted_01():
    content = b'&INST\nNI=4\nKEY1=1111\nCODES = "01"\n&END\n'
    res = parse_control(content)
    assert res["CODES"] == '"01"'
    assert isinstance(res["CODES"], str)

def test_misscore_spelling_neg_one():
    content = b"&INST\nNI=4\nKEY1=1111\nMISSCORE = -1\n&END\n"
    res = parse_control(content)
    assert res["MISSCORE"] == -1
    assert isinstance(res["MISSCORE"], int)

def test_misscore_spelling_neg_half():
    content = b"&INST\nNI=4\nKEY1=1111\nMISSCORE = -0.5\n&END\n"
    res = parse_control(content)
    assert res["MISSCORE"] == -0.5
    assert isinstance(res["MISSCORE"], float)

def test_misscore_spelling_na():
    content = b"&INST\nNI=4\nKEY1=1111\nMISSCORE = NA\n&END\n"
    res = parse_control(content)
    assert res["MISSCORE"] == "NA"
    assert isinstance(res["MISSCORE"], str)

def test_key1_ni_mismatch_indonesian():
    content = f"&INST\nNI=99\nKEY1={'1' * 40}\n&END\n".encode()
    with pytest.raises(ValueError) as exc_info:
        parse_control(content)
    msg = str(exc_info.value)
    assert "tidak sama dengan NI" in msg
    assert "does not match" not in msg

def test_missing_inst_indonesian():
    content = b"NI=4\nKEY1=1111\n&END\n"
    with pytest.raises(ValueError) as exc_info:
        parse_control(content)
    msg = str(exc_info.value)
    assert "&INST" in msg
    assert "Missing" not in msg

def test_missing_end_indonesian():
    content = b"&INST\nNI=4\nKEY1=1111\n"
    with pytest.raises(ValueError) as exc_info:
        parse_control(content)
    msg = str(exc_info.value)
    assert "&END" in msg
    assert "Missing" not in msg
