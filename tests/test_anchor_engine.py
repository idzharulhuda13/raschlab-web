"""Real-engine proof that anchors actually bite (F19). Slow: it runs the engine twice.

The anchored run must report the requested anchor values on the pinned items (so the wiring reaches
the estimator) and must move at least one unpinned item (so it is not a no-op). A params-only check
would not prove any of this.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.analysis import effective_item_labels, load_tables
from app.db import SessionLocal
from app.models import Analysis, AnalysisFile, Dataset
from tests.test_analysis_settings import _create_authenticated_user, _upload_and_commit_sample
from tests.test_delete_list_settings import _analysis_id_from, _post_analyze

MEASURE_TOLERANCE = 0.005
MIN_UNPINNED_SHIFT = 0.05
PINNED_ITEMS = 6
ANCHOR_OFFSET = 0.6


def _item_rows(analysis_id: int) -> list[list[str]]:
    with SessionLocal() as db:
        analysis = db.scalar(select(Analysis).where(Analysis.id == analysis_id))
        assert analysis is not None
        return load_tables(analysis)["item_table_15.1.csv"]


def _file_names(analysis_id: int) -> set[str]:
    with SessionLocal() as db:
        rows = db.scalars(select(AnalysisFile).where(AnalysisFile.analysis_id == analysis_id)).all()
        return {row.filename for row in rows}


def _labels(dataset_id: int) -> list[str]:
    with SessionLocal() as db:
        dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
        assert dataset is not None
        return effective_item_labels(dataset)


def _column(header_rows: list[list[str]], name: str) -> int:
    for row in header_rows:
        for index, cell in enumerate(row):
            if str(cell).strip().upper() == name:
                return index
    raise AssertionError(f"kolom {name} tidak ditemukan; header={header_rows}")


def test_anchored_run_pins_measures_and_moves_the_rest(client: TestClient):
    _create_authenticated_user(client)
    dataset_id = _upload_and_commit_sample(client)

    plain = _post_analyze(client, dataset_id)
    assert plain.status_code == 303
    plain_id = _analysis_id_from(plain)
    plain_rows = _item_rows(plain_id)
    header = plain_rows[:2]
    measure_at = _column(header, "MEASURE")
    item_at = _column(header, "ITEM")
    plain_data = plain_rows[2:]
    labels = _labels(dataset_id)

    picked: list[tuple[int, str, float]] = []
    for offset, row in enumerate(plain_data):
        try:
            measure = float(str(row[measure_at]).replace(",", "."))
        except (TypeError, ValueError):
            continue
        if abs(measure) >= 2.0:
            continue
        picked.append((offset + 1, str(row[item_at]).strip(), measure))
        if len(picked) == PINNED_ITEMS:
            break
    assert len(picked) == PINNED_ITEMS, f"tidak dapat {PINNED_ITEMS} butir non-ekstrem; header={header}"
    for position, label, _measure in picked:
        assert label == labels[position - 1], (
            f"posisi {position} menunjuk label {label!r}, kolom dataset {labels[position - 1]!r}"
        )

    requested = [(position, label, round(measure + ANCHOR_OFFSET, 2)) for position, label, measure in picked]
    anchor_text = "".join(f"{position} {value}\n" for position, _label, value in requested).encode()

    anchored = _post_analyze(
        client, dataset_id, files={"anchors": ("jangkar_uji.txt", anchor_text)}
    )
    assert anchored.status_code == 303
    anchored_id = _analysis_id_from(anchored)
    anchored_rows = _item_rows(anchored_id)
    anchored_data = anchored_rows[2:]
    print(f"\nheader baris 1: {header[0]}")
    print(f"header baris 2: {header[1]}")
    print(f"jangkar diminta: {requested}")

    assert len(anchored_data) == len(plain_data)

    pinned_positions = {position for position, _label, _value in requested}
    checked = 0
    for offset, row in enumerate(anchored_data):
        position = offset + 1
        measured = float(str(row[measure_at]).replace(",", "."))
        if position in pinned_positions:
            want = next(value for pos, _label, value in requested if pos == position)
            want_label = next(label for pos, label, _value in requested if pos == position)
            print(f"  butir {position}: diminta {want} terukur {measured}")
            assert abs(measured - want) <= MEASURE_TOLERANCE, (
                f"butir {position} terukur {measured} tidak sama dengan jangkar {want}"
            )
            assert str(row[item_at]).strip() == want_label
            checked += 1
    assert checked == len(requested)

    shifts = []
    for offset, (new_row, old_row) in enumerate(zip(anchored_data, plain_data)):
        if offset + 1 in pinned_positions:
            continue
        try:
            new_measure = float(str(new_row[measure_at]).replace(",", "."))
            old_measure = float(str(old_row[measure_at]).replace(",", "."))
        except (TypeError, ValueError):
            continue
        shifts.append((offset + 1, abs(new_measure - old_measure)))
    assert shifts, "tidak ada butir tak-terpaku yang bisa dibandingkan"
    worst = max(shifts, key=lambda item: item[1])
    print(f"  geser terbesar butir tak-terpaku: butir {worst[0]} sebesar {worst[1]:.4f}")
    assert worst[1] >= MIN_UNPINNED_SHIFT, (
        f"tidak ada butir tak-terpaku yang bergeser; geser maksimum {worst[1]:.4f}"
    )

    assert _file_names(anchored_id) == _file_names(plain_id)
