"""Module for exporting RaschLab analysis tables to XLSX format."""

import io
import openpyxl
from openpyxl.cell import WriteOnlyCell
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.analysis import load_tables
from app.auth import _current_user, _gate_closed
from app.db import get_session
from app.explore import (
    ANALYSIS_NOT_FOUND_MSG,
    DATASET_NOT_FOUND_MSG,
    PAGE_NOT_FOUND_MSG,
    build_compare_pairs,
)
from app.models import Analysis, Dataset
from app.ratelimit import check_limit, client_ip
from raschlab.report import (
    ITEM_HEADER_ROW_2,
    coerce_cell,
    number_format_for_header,
    summary_value_format,
    write_workbook,
)
from raschlab.wright import FREQ_HEADER_ROW_1, MEASURE_HEADER_ROW_1

TABLE_KEYS = {"butir": "item_table_15.1.csv", "opsi": "option_table_15.3.csv", "responden": "person_table.csv", "ringkasan": "summary_table.csv", "wright": "wright_map_measure.csv", "frekuensi": "wright_map_frequency.csv"}
HEADER_ROWS = {"butir": 2, "opsi": 2, "responden": 2, "ringkasan": 1, "wright": 2, "bandingkan": 1, "frekuensi": 2}
SHEET_TITLES = {"butir": "butir", "opsi": "opsi", "responden": "responden", "ringkasan": "ringkasan", "wright": "wright", "bandingkan": "bandingkan", "frekuensi": "frekuensi"}
COMPARE_HEADER = ["Nomor", "Butir", "Measure analisis pertama", "Measure analisis kedua", "Selisih (kedua − pertama)"]
COMPARE_NUMERIC = {0: "int", 2: "float", 3: "float", 4: "float"}
SUMMARY_NUMERIC = {2: "summary"}
WRIGHT_NUMERIC = {0: "raw", 1: "raw", 3: "raw"}
FREQ_NUMERIC = {0: "float", 1: "int", 2: "int", 5: "int"}
TABLE_NUMERIC = {"ringkasan": SUMMARY_NUMERIC, "wright": WRIGHT_NUMERIC, "frekuensi": FREQ_NUMERIC}
EXPORT_MAX_ROWS = 1_048_000
EXPORT_MAX_CELLS = 2_500_000
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXPORT_TABLE_NOT_FOUND_MSG = "Tabel unduhan tidak tersedia untuk analisis ini."
EXPORT_RATE_MSG = "Batasan unduhan Excel tercapai (30 unduhan per jam). Silakan coba lagi nanti."
EXPORT_RATE_LIMIT = 30
EXPORT_RATE_WINDOW_S = 3600


def build_xlsx(sheet_title: str, rows: list[list[str]], header_rows: int, numeric: dict[int, str] | None = None) -> bytes:
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet(title=sheet_title)
    labels = rows[header_rows - 1] if rows and header_rows >= 1 else []
    for r_idx, row in enumerate(rows):
        row_cells = []
        for c_idx, raw in enumerate(row):
            value = "" if raw is None else str(raw)
            if r_idx < header_rows:
                row_cells.append(WriteOnlyCell(ws, value=value or None))
                continue
            fmt = None
            mode = None if numeric is None else numeric.get(c_idx)
            if mode == "raw":
                value, _ = coerce_cell(value, "0.00" if "." in value else "0")
            elif mode == "summary":
                fmt = summary_value_format(value)
                if fmt is not None:
                    value, fmt = coerce_cell(value, fmt)
            elif mode == "int":
                value, fmt = coerce_cell(value, "0")
            elif mode == "float":
                value, fmt = coerce_cell(value, "0.00")
            else:
                fmt = number_format_for_header(labels[c_idx] if c_idx < len(labels) else "")
                if fmt is not None:
                    value, fmt = coerce_cell(value, fmt)
            if value == "":
                value = None
            cell = WriteOnlyCell(ws, value=value)
            if fmt:
                cell.number_format = fmt
            row_cells.append(cell)
        ws.append(row_cells)
    ws.freeze_panes = "A" + str(header_rows + 1)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def place_by_header(stored_names: list[str], row: list[str], engine_names: list[str]) -> dict[int, str]:
    """Map one stored row onto the engine's own column positions, by header name.

    The combined workbook lets the engine write its own item header, and the engine
    appends rows as ``list(row.values())``, so the dict order IS the column order and
    every engine column has to be present. Reading positions instead breaks the
    moment a column is added: after the engine gained SUBSUBTES, an analysis stored
    before that bump still has STATUS at index 14, and the positional write put
    "kept"/"deleted" under the SUBSUBTES header. Matching names (repeated names in
    order, so INFIT/OUTFIT MNSQ stay apart) keeps an older file readable, leaves a
    column the file does not have empty, and is the identity for a file written by
    the current engine.
    """
    if not stored_names:
        # No header row to match against: keep the old positional behaviour rather
        # than dropping every value of the file.
        return dict(enumerate(row))
    placed: dict[int, str] = {idx: "" for idx in range(len(engine_names))}
    used: set[int] = set()
    for pos, name in enumerate(stored_names):
        if pos >= len(row):
            break
        key = str(name).strip()
        for idx, engine_name in enumerate(engine_names):
            if idx in used or engine_name != key:
                continue
            placed[idx] = row[pos]
            used.add(idx)
            break
    return placed


def build_workbook_bytes(analysis: Analysis, tables: dict[str, list[list[str]]] | None = None) -> bytes:
    """Build the combined 6-sheet XLSX workbook and return its bytes."""
    if tables is None:
        tables = load_tables(analysis)

    def _get_stored(table_key: str) -> list[list[str]] | None:
        filename = TABLE_KEYS.get(table_key)
        if not filename:
            return None
        stored = tables.get(filename) or []
        if not stored or all(not any(str(cell).strip() for cell in row) for row in stored):
            return None
        return stored

    item_stored = _get_stored("butir")
    person_stored = _get_stored("responden")
    option_stored = _get_stored("opsi")
    summary_stored = _get_stored("ringkasan")
    wright_stored = _get_stored("wright")
    freq_stored = _get_stored("frekuensi")

    # The engine writes its own item header, so the stored values are placed by
    # header name: an analysis stored before a column was added stays aligned.
    item_names = item_stored[1] if item_stored and len(item_stored) > 1 else []
    item_rows = [
        place_by_header(item_names, r, ITEM_HEADER_ROW_2)
        for r in (item_stored[HEADER_ROWS["butir"]:] if item_stored else [])
    ]
    person_rows = [dict(enumerate(r)) for r in person_stored[HEADER_ROWS["responden"]:]] if person_stored else []
    option_rows = [dict(enumerate(r)) for r in option_stored[HEADER_ROWS["opsi"]:]] if option_stored else []

    summary_rows = []
    if summary_stored:
        for r in summary_stored:
            if not any(str(c).strip() for c in r):
                continue
            if [str(c).strip() for c in r[:3]] == ["SECTION", "STATISTIC", "VALUE"]:
                continue
            summary_rows.append(list(r))

    wright_measure_rows = (
        [dict(zip(MEASURE_HEADER_ROW_1, r)) for r in wright_stored[HEADER_ROWS["wright"]:]]
        if wright_stored
        else None
    )
    wright_frequency_rows = (
        [dict(zip(FREQ_HEADER_ROW_1, r)) for r in freq_stored[HEADER_ROWS["frekuensi"]:]]
        if freq_stored
        else None
    )

    buf = io.BytesIO()
    write_workbook(
        buf,
        item_rows,
        person_rows,
        option_rows,
        summary_rows,
        wright_measure_rows=wright_measure_rows,
        wright_frequency_rows=wright_frequency_rows,
    )
    return buf.getvalue()


def message_page(text: str, status_code: int, extra_headers: dict[str, str] | None = None) -> Response:
    body = "<!doctype html><html lang=\"id\"><head><meta charset=\"utf-8\"><title>Unduhan Excel: RaschLab</title></head><body><p>" + text + "</p><p><a href=\"/analyses\">Kembali ke daftar hasil analisis</a></p></body></html>"
    return Response(content=body, status_code=status_code, media_type="text/html", headers=extra_headers)


def _compare_rows(db: Session, user, request: Request) -> list[list[str]] | None:
    """Rows of the comparison sheet, mirroring the pairing the explore view renders."""
    from_val = request.query_params.get("from")
    to_val = request.query_params.get("to")
    if not from_val or not to_val:
        return None
    try:
        from_id = int(from_val)
        to_id = int(to_val)
    except (TypeError, ValueError):
        return None
    if from_id == to_id:
        return None
    from_analysis = db.scalar(select(Analysis).where(Analysis.id == from_id))
    if from_analysis is None or from_analysis.user_id != user.id or from_analysis.status != "done":
        return None
    to_analysis = db.scalar(select(Analysis).where(Analysis.id == to_id))
    if to_analysis is None or to_analysis.user_id != user.id or to_analysis.status != "done":
        return None
    items_from = load_tables(from_analysis).get("item_table_15.1.csv", [])
    items_to = load_tables(to_analysis).get("item_table_15.1.csv", [])
    cmp_result = build_compare_pairs(items_from, items_to)
    pairs = cmp_result["pairs"]
    if request.query_params.get("over_se") is not None:
        pairs = [pair for pair, over in zip(pairs, cmp_result["over_se"]) if over]
    return [COMPARE_HEADER] + [[pair[0], pair[1], pair[2], pair[3], pair[4]] for pair in pairs]


router = APIRouter()


@router.get("/analyses/{id}/export")
def export_table(id: int, request: Request, table: str | None = None,
                 db: Session = Depends(get_session)) -> Response:
    """Download one result table of one finished analysis as an XLSX workbook."""
    if _gate_closed():
        raise HTTPException(status_code=404, detail=PAGE_NOT_FOUND_MSG)
    user = _current_user(request, db)
    if user is None:
        raise HTTPException(status_code=404, detail=PAGE_NOT_FOUND_MSG)

    analysis = db.scalar(select(Analysis).where(Analysis.id == id))
    if analysis is None or analysis.user_id != user.id:
        raise HTTPException(status_code=404, detail=ANALYSIS_NOT_FOUND_MSG)

    dataset = db.scalar(select(Dataset).where(Dataset.id == analysis.dataset_id))
    if dataset is None or dataset.user_id != user.id:
        raise HTTPException(status_code=404, detail=DATASET_NOT_FOUND_MSG)

    if analysis.status != "done":
        return RedirectResponse(f"/analyses/{analysis.id}", status_code=303)

    table = (table or "").strip()
    if table != "semua" and table not in SHEET_TITLES:
        raise HTTPException(status_code=404, detail=EXPORT_TABLE_NOT_FOUND_MSG)

    allowed, retry_after = check_limit(
        "export:" + client_ip(request) + ":" + str(user.id),
        EXPORT_RATE_LIMIT,
        EXPORT_RATE_WINDOW_S,
    )
    if not allowed:
        return message_page(EXPORT_RATE_MSG, 429, {"Retry-After": str(retry_after)})

    if table == "semua":
        tables = load_tables(analysis)
        total_rows = 0
        total_cells = 0
        has_any = False
        for key, filename in TABLE_KEYS.items():
            stored = tables.get(filename) or []
            if stored and any(any(str(cell).strip() for cell in row) for row in stored):
                has_any = True
                total_rows += len(stored)
                total_cells += sum(len(row) for row in stored)
        if not has_any:
            raise HTTPException(status_code=404, detail=EXPORT_TABLE_NOT_FOUND_MSG)
        if total_rows > EXPORT_MAX_ROWS or total_cells > EXPORT_MAX_CELLS:
            message = (
                f"Tabel ini memuat {total_rows} baris dan {total_cells} sel, melebihi batas unduhan Excel"
                f" ({EXPORT_MAX_ROWS} baris dan {EXPORT_MAX_CELLS} sel)."
            )
            return message_page(message, 413)
        body = build_workbook_bytes(analysis, tables=tables)
        filename = f"raschlab-{id}-{table}.xlsx"
        return Response(
            content=body,
            media_type=XLSX_MEDIA_TYPE,
            headers={
                "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{filename}",
                "Cache-Control": "no-store",
            },
        )

    if table == "bandingkan":
        rows = _compare_rows(db, user, request)
        if rows is None:
            raise HTTPException(status_code=404, detail=EXPORT_TABLE_NOT_FOUND_MSG)
        numeric = COMPARE_NUMERIC
        header_rows = HEADER_ROWS["bandingkan"]
    else:
        stored = load_tables(analysis).get(TABLE_KEYS[table]) or []
        rows = [row for row in stored]
        if not rows or all(not any(str(cell).strip() for cell in row) for row in rows):
            raise HTTPException(status_code=404, detail=EXPORT_TABLE_NOT_FOUND_MSG)
        numeric = TABLE_NUMERIC.get(table)
        header_rows = HEADER_ROWS[table]

    cells = sum(len(row) for row in rows)
    if len(rows) > EXPORT_MAX_ROWS or cells > EXPORT_MAX_CELLS:
        message = (
            f"Tabel ini memuat {len(rows)} baris dan {cells} sel, melebihi batas unduhan Excel"
            f" ({EXPORT_MAX_ROWS} baris dan {EXPORT_MAX_CELLS} sel)."
        )
        return message_page(message, 413)

    body = build_xlsx(SHEET_TITLES[table], rows, header_rows, numeric)
    filename = f"raschlab-{id}-{table}.xlsx"
    return Response(
        content=body,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{filename}",
            "Cache-Control": "no-store",
        },
    )
