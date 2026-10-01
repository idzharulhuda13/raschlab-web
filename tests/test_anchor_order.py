"""Pin the item-order chain: dataset columns -> items.lbl -> engine data columns -> anchor positions (F19).

A silent reorder anywhere in that chain would attach anchors to the wrong items without any error, so
the order is asserted at every step using a deliberately unsorted column order.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from app.analysis import build_matrix_gzip, effective_item_labels, parse_anchors, write_inputs
from app.parsers import parse_delimited

CSV = b"id,zeta,alpha,mike\nP1,1,0,1\nP2,0,1,1\nP3,1,1,0\nP4,0,0,1\n"
LABELS = ["zeta", "alpha", "mike"]
MAPPING = {"1": "correct", "0": "incorrect"}


class _StubDataset:
    """Only the fields write_inputs and effective_item_labels read."""

    def __init__(self, labels: list[str]) -> None:
        self.item_labels_json = json.dumps(labels)
        self.n_items = len(labels)
        self.summary_json = "{}"


def _matrix() -> bytes:
    parsed = parse_delimited(CSV)
    return build_matrix_gzip(
        "delimited", parsed.person_labels, parsed.item_labels, parsed.rows, mapping=MAPPING
    )


def test_item_labels_keep_the_column_order():
    parsed = parse_delimited(CSV)

    assert parsed.item_labels == LABELS
    assert effective_item_labels(_StubDataset(parsed.item_labels)) == LABELS


def test_engine_data_columns_follow_the_column_order():
    parsed = parse_delimited(CSV)
    meta = json.loads(gzip.decompress(_matrix()).decode("utf-8"))
    lines = [line for line in meta["prn"].splitlines() if line.strip()]
    codes = meta["codes"]
    correct_code, incorrect_code = codes[0], codes[1]

    assert len(lines) == len(parsed.rows)
    expected = [
        "".join(correct_code if token == "1" else incorrect_code for token in row)
        for row in parsed.rows
    ]
    width = len(parsed.item_labels)
    responses = [line.strip()[-width:] for line in lines]

    assert responses == expected, (
        f"kolom data bergeser; namlen={meta.get('namlen')} baris={lines}"
    )


def test_written_label_file_matches_the_column_order(tmp_path: Path):
    write_inputs(tmp_path, _StubDataset(LABELS), _matrix())

    written = Path(tmp_path, "items.lbl").read_text(encoding="utf-8").splitlines()

    assert written == LABELS


def test_anchor_positions_agree_with_the_column_order():
    assert parse_anchors("a.txt", b"zeta 0.5\n", LABELS)["anchors"] == {1: 0.5}
    assert parse_anchors("a.txt", b"alpha -0.25\n", LABELS)["anchors"] == {2: -0.25}
    assert parse_anchors("a.txt", b"mike 0.5\n", LABELS)["anchors"] == {3: 0.5}
